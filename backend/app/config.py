from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COCKPIT_", extra="ignore")
    env: str = "production"
    database_url: str
    secret_key: str
    allowed_origins: str = ""
    allowed_hosts: str = "localhost,127.0.0.1"
    cookie_secure: bool = True
    session_ttl_seconds: int = 28_800
    login_rate_limit: int = 5
    login_rate_window_seconds: int = 900
    infrastructure_mode: str = "live"
    release: str = "development"

    @model_validator(mode="after")
    def production_safety(self) -> "Settings":
        if len(self.secret_key) < 32:
            raise ValueError("COCKPIT_SECRET_KEY must contain at least 32 characters")
        if self.env == "production":
            if not self.cookie_secure:
                raise ValueError("Secure cookies are mandatory in production")
            if any(not value.startswith("https://") for value in self.cors_origins):
                raise ValueError("Production CORS origins must use HTTPS")
            if not self.cors_origins:
                raise ValueError("Production requires an explicit HTTPS origin")
            if self.infrastructure_mode == "fixture":
                raise ValueError("Fixture infrastructure is forbidden in production")
        if "*" in self.cors_origins or "*" in self.hosts:
            raise ValueError("Wildcard origins and hosts are not allowed")
        if self.infrastructure_mode not in {"live", "fixture"}:
            raise ValueError("COCKPIT_INFRASTRUCTURE_MODE must be live or fixture")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def hosts(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
