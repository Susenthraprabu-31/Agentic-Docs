import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import Frame, Locator

from app.config.florida_portals import (
    format_florida_pa_address_for_search,
    is_florida_pa_assessor,
    normalize_florida_pa_parcel,
    resolve_florida_assessor_url,
)
from app.drivers.assessor.florida_assessor import (
    _click_florida_pa_run_search,
    _dismiss_florida_pa_disclaimer,
    _dismiss_florida_pa_disclaimer_in_frame,
    _fill_florida_pa_input,
    _open_florida_pa_detail,
    _wait_for_florida_pa_frame,
)
from app.drivers.base.base_driver import BaseDriver
from app.extraction.schemas import QueryType

logger = logging.getLogger(__name__)

MAP_SELECTORS = [
    "canvas",
    "#map",
    "#mapDiv",
    ".mapDiv",
    'iframe[src*="map" i]',
    'div[id*="mapviewer" i]',
    'div[class*="mapviewer" i]',
]


class GilaGisDriver(BaseDriver):
    async def capture_parcel_map(
        self,
        gis_url: str,
        parcel: Optional[str] = None,
        query_type: Optional[QueryType] = None,
        query_value: Optional[str] = None,
    ) -> Optional[str]:
        if "floridapa.com" in gis_url.lower() or is_florida_pa_assessor(gis_url):
            return await self._capture_florida_pa_map(gis_url, parcel, query_type, query_value)

        await self.page.goto(gis_url, wait_until="domcontentloaded")
        await self.polite_delay(2.0)
        await self.dismiss_netronline_modals()

        if parcel:
            search = self.page.locator('input[type="text"], input[type="search"]').first
            try:
                if await search.count() > 0 and await search.is_visible(timeout=2_000):
                    await search.fill(parcel)
                    await self.page.keyboard.press("Enter")
                    await self.polite_delay(2.0)
            except Exception:
                pass

        path = self.screenshot_dir / f"gis_map_{parcel or 'overview'}.png"
        await self.page.screenshot(path=str(path), full_page=True)
        return str(path.resolve())

    async def _capture_florida_pa_map(
        self,
        gis_url: str,
        parcel: Optional[str],
        query_type: Optional[QueryType],
        query_value: Optional[str],
    ) -> Optional[str]:
        search_url = resolve_florida_assessor_url(gis_url)
        parcel_id = normalize_florida_pa_parcel(parcel) if parcel else None
        safe_name = (parcel_id or "overview").replace("/", "-")

        if not await self._navigate_to_florida_pa_detail(
            search_url, parcel_id, query_type, query_value
        ):
            return None

        path = self.screenshot_dir / f"gis_map_{safe_name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        if await self._screenshot_florida_pa_map(path):
            return str(path.resolve())

        await self._emit_status("Could not capture parcel map image.")
        return None

    async def _navigate_to_florida_pa_detail(
        self,
        search_url: str,
        parcel: Optional[str],
        query_type: Optional[QueryType],
        query_value: Optional[str],
    ) -> bool:
        existing = await _wait_for_florida_pa_frame(self, "recordSearch_3_Details", timeout_ms=2_000)
        if existing and parcel and await self._detail_contains_parcel(existing, parcel):
            await self._emit_status("Parcel details already open — capturing GIS map...")
            return True

        await self._emit_status("Opening Property Appraiser GIS to load parcel map...")
        await self.page.goto(search_url, wait_until="networkidle", timeout=90_000)
        await _dismiss_florida_pa_disclaimer(self)

        search_frame = await _wait_for_florida_pa_frame(self, "recordSearch_1_Form", timeout_ms=25_000)
        if not search_frame:
            await self._emit_status("Could not load GIS search form.")
            return False

        await _dismiss_florida_pa_disclaimer_in_frame(search_frame)

        filled = False
        if parcel:
            await self._emit_status(f"Searching parcel {parcel} for GIS map...")
            filled = await _fill_florida_pa_input(search_frame, "#PIN", parcel)
        elif query_type == QueryType.ADDRESS and query_value:
            address = format_florida_pa_address_for_search(query_value)
            await self._emit_status(f"Searching address {address} for GIS map...")
            filled = await _fill_florida_pa_input(search_frame, 'input[name="StreetName"]', address)
        elif query_type == QueryType.OWNER and query_value:
            await self._emit_status(f"Searching owner {query_value} for GIS map...")
            filled = await _fill_florida_pa_input(search_frame, "#OwnerName", query_value)

        if not filled:
            await self._emit_status("Could not fill GIS search form.")
            return False

        await _click_florida_pa_run_search(search_frame)
        await self.page.wait_for_timeout(2_500)

        results_frame = await _wait_for_florida_pa_frame(self, "recordSearch_2_Results", timeout_ms=20_000)
        if not results_frame:
            await self._emit_status("No GIS search results found.")
            return False

        await self._emit_status("Opening parcel details for GIS map...")
        if not await _open_florida_pa_detail(self, results_frame):
            await self._emit_status("Could not open parcel details page.")
            return False

        await self.page.wait_for_timeout(3_000)
        detail_frame = await _wait_for_florida_pa_frame(self, "recordSearch_3_Details", timeout_ms=20_000)
        return detail_frame is not None

    async def _detail_contains_parcel(self, frame: Frame, parcel: str) -> bool:
        try:
            body = await frame.inner_text("body")
            normalized = parcel.replace("-", "").replace(" ", "")
            return normalized in body.replace("-", "").replace(" ", "")
        except Exception:
            return False

    async def _screenshot_florida_pa_map(self, output_path: Path) -> bool:
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        detail_frame = await _wait_for_florida_pa_frame(self, "recordSearch_3_Details", timeout_ms=15_000)
        if not detail_frame:
            logger.warning("GIS screenshot: parcel detail frame not found")
            return False

        await self._emit_status("Waiting for aerial parcel map to render...")
        await self.page.wait_for_timeout(8_000)

        map_locator = await self._find_best_map_locator(detail_frame)
        if not map_locator:
            for frame in self.page.frames:
                map_locator = await self._find_best_map_locator(frame)
                if map_locator:
                    break

        if map_locator:
            try:
                await map_locator.screenshot(path=str(output_path), timeout=30_000)
                await self._emit_status("Captured parcel map from Property Appraiser.")
                return True
            except Exception as exc:
                logger.warning("GIS map element screenshot failed: %s", exc)

        for iframe_sel in [
            'iframe[src*="recordSearch_3_Details"]',
            'iframe[src*="recordSearch_3"]',
        ]:
            try:
                iframe_loc = self.page.locator(iframe_sel).first
                if await iframe_loc.count() > 0 and await iframe_loc.is_visible(timeout=2_000):
                    await iframe_loc.screenshot(path=str(output_path), timeout=30_000)
                    await self._emit_status("Captured parcel details map from Property Appraiser.")
                    return True
            except Exception as exc:
                logger.warning("GIS iframe locator screenshot failed for %s: %s", iframe_sel, exc)

        try:
            frame_el = await detail_frame.frame_element()
            await frame_el.screenshot(path=str(output_path), timeout=30_000)
            await self._emit_status("Captured parcel details map from Property Appraiser.")
            return True
        except Exception as exc:
            logger.warning("GIS detail iframe screenshot failed: %s", exc)

        clip = await self._find_map_clip_box(detail_frame)
        if clip:
            try:
                await self.page.screenshot(path=str(output_path), clip=clip, timeout=30_000)
                await self._emit_status("Captured parcel map from Property Appraiser.")
                return True
            except Exception as exc:
                logger.warning("GIS clipped screenshot failed: %s", exc)

        try:
            await self.page.screenshot(path=str(output_path), full_page=True, timeout=30_000)
            await self._emit_status("Captured GIS page from Property Appraiser.")
            return True
        except Exception as exc:
            logger.warning("GIS full-page screenshot failed: %s", exc)

        return False

    async def _find_best_map_locator(self, frame: Frame | None) -> Locator | None:
        if not frame:
            return None

        best: Locator | None = None
        best_area = 0.0

        for sel in MAP_SELECTORS:
            try:
                locs = frame.locator(sel)
                count = await locs.count()
                for index in range(count):
                    loc = locs.nth(index)
                    if not await loc.is_visible(timeout=500):
                        continue

                    if sel.startswith("iframe"):
                        handle = await loc.element_handle()
                        if handle:
                            inner = await handle.content_frame()
                            inner_loc = await self._find_best_map_locator(inner)
                            if inner_loc:
                                inner_box = await inner_loc.bounding_box()
                                if inner_box:
                                    area = inner_box["width"] * inner_box["height"]
                                    if area > best_area:
                                        best_area = area
                                        best = inner_loc
                        continue

                    box = await loc.bounding_box()
                    if not box or box["width"] < 200 or box["height"] < 200:
                        continue
                    area = box["width"] * box["height"]
                    if area > best_area:
                        best_area = area
                        best = loc
            except Exception:
                continue

        return best

    async def _find_map_clip_box(self, detail_frame: Frame | None) -> dict[str, float] | None:
        frames: list[Frame] = []
        if detail_frame:
            frames.append(detail_frame)
        frames.extend(frame for frame in self.page.frames if frame not in frames)

        best_box: dict[str, float] | None = None
        best_area = 0.0
        for frame in frames:
            try:
                inner_box = await frame.evaluate(
                    """() => {
                      let best = null;
                      let bestArea = 0;
                      for (const el of document.querySelectorAll('canvas, iframe, #map, #mapDiv, .mapDiv')) {
                        const rect = el.getBoundingClientRect();
                        const area = rect.width * rect.height;
                        if (rect.width >= 200 && rect.height >= 200 && area > bestArea) {
                          bestArea = area;
                          best = { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
                        }
                      }
                      return best;
                    }"""
                )
                if not inner_box:
                    continue

                area = inner_box["width"] * inner_box["height"]
                if area <= best_area:
                    continue

                offset_x = 0.0
                offset_y = 0.0
                if frame != self.page.main_frame:
                    frame_el = await frame.frame_element()
                    outer = await frame_el.bounding_box()
                    if not outer:
                        continue
                    offset_x = outer["x"]
                    offset_y = outer["y"]

                best_area = area
                best_box = {
                    "x": offset_x + inner_box["x"],
                    "y": offset_y + inner_box["y"],
                    "width": inner_box["width"],
                    "height": inner_box["height"],
                }
            except Exception:
                continue
        return best_box
