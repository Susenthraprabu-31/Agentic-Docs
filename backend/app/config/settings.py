from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    openai_api_key: str = ""
    openai_browser_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    mistral_api_key: str = ""
    mistral_ocr_model: str = "mistral-ocr-4-1"
    mistral_ocr_max_retries: int = 3
    mistral_ocr_retry_base_seconds: float = 2.0
    port: int = 8000
    environment: str = "development"
    playwright_headless: bool = True
    playwright_channel: str = "chrome"
    playwright_user_data_dir: str = ".playwright-profile"
    playwright_cloudflare_wait_seconds: int = 180
    # Do not repeatedly request a portal after it has returned a hard access denial.
    # The portal owner must clear/allowlist access before the cooldown expires.
    portal_hard_block_cooldown_minutes: int = 1440
    # Connect to your own Chrome (bypasses Cloudflare). Auto-launched when set.
    playwright_cdp_url: str = ""
    # When true, never fall back to Playwright-launched Chrome (avoids Cloudflare blocks).
    playwright_cdp_required: bool = True
    # CDP Chrome profile directory (default: %LOCALAPPDATA%/DonoChromeProfile on Windows).
    playwright_cdp_profile_dir: str = ""
    # Copy Cloudflare cookies from the user's regular Chrome before county portal navigation.
    # Cloudflare bypass toggles (see app/drivers/browser_factory.py)
    use_human_delays: bool = True
    # FlareSolverr API (e.g. http://localhost:8191) — automatic Cloudflare bypass.
    supabase_storage_bucket: str = "dono-mvp"
    cors_origins: str = "http://localhost:5173"
    # Feature flag for county portal automation: "legacy" | "ai_dynamic"
    automation_mode: str = "legacy"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def groq_configured(self) -> bool:
        return bool(self.groq_api_key)

    @property
    def mistral_configured(self) -> bool:
        return bool(self.mistral_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
