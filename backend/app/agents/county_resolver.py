from app.drivers.netronline.netronline_driver import NetronlineDriver
from app.extraction.schemas import CountySources


class CountyResolver:
    def __init__(self, driver: NetronlineDriver) -> None:
        self.driver = driver
        self._cached: CountySources | None = None

    async def resolve(self, state: str, county: str) -> CountySources:
        if self._cached is None:
            self._cached = await self.driver.resolve_county_sources(state, county)
        return self._cached

    @property
    def sources(self) -> CountySources | None:
        return self._cached
