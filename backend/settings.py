import os

# Basic settings helper to read environment configuration.


def _as_bool(val: str | None, default: bool = False) -> bool:
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        self.PLACES_LOOKUP_ENABLED: bool = _as_bool(os.getenv("PLACES_LOOKUP_ENABLED"), False)


settings = Settings()
