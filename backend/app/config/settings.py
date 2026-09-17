from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    openai_api_key: str = ""
    openai_browser_model: str = "gpt-4o-mini"
    mistral_api_key: str = ""
    port: int = 8000
    environment: str = "development"
    playwright_headless: bool = True
    playwright_channel: str = "chrome"
    playwright_user_data_dir: str = ".playwright-profile"
    playwright_cloudflare_wait_seconds: int = 180
    supabase_storage_bucket: str = "dono-mvp"
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
