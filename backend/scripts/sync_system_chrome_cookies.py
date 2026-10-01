#!/usr/bin/env python3
"""Copy schneidercorp.com cookies from regular Chrome into local_storage/browser_sessions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.drivers.browser_sessions import SESSION_DIR, portal_session_key
from app.drivers.chrome_cookie_import import read_system_chrome_cookies

URL = "https://qpublic.schneidercorp.com/Application.aspx?AppID=1081"


def main() -> int:
    cookies = read_system_chrome_cookies()
    if not cookies:
        print("No cookies found. Open the county site in regular Chrome first, then run again.")
        return 1

    host = portal_session_key(URL)
    path = SESSION_DIR / f"{host}.json"
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"domain": host, "cookies": cookies}, indent=2), encoding="utf-8")
    print(f"Saved {len(cookies)} cookie(s) to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
