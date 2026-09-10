from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DriverResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    screenshot_path: Optional[str] = None
