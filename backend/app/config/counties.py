"""County utility helpers."""


def get_county_key(state: str, county: str) -> str:
    """Build a state:county lookup key."""
    return f"{state.lower()}:{county.lower()}"
