from decimal import Decimal
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
    public_url: str = "https://cockpit.plenora.nl"
    notification_email_to: str = ""
    notification_email_from: str = ""
    notification_smtp_host: str = ""
    notification_smtp_port: int = 587
    notification_smtp_username: str = ""
    notification_smtp_password: str = ""
    notification_smtp_starttls: bool = True
    notification_max_attempts: int = 3
    analysis_enabled: bool = False
    analysis_provider: str = "openai"
    analysis_model: str = ""
    analysis_api_key: str = ""
    analysis_max_output_tokens: int = 800
    analysis_timeout_seconds: int = 20
    analysis_max_attempts: int = 2
    analysis_max_observations: int = 25
    analysis_max_history: int = 5
    ai_monthly_budget_eur: Decimal = Decimal("100.00")
    ai_usd_to_eur_rate: Decimal = Decimal("1.00")

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
        if self.notification_max_attempts < 1 or self.notification_max_attempts > 10:
            raise ValueError("COCKPIT_NOTIFICATION_MAX_ATTEMPTS must be between 1 and 10")
        if not self.public_url.startswith("https://cockpit.plenora.nl"):
            raise ValueError("Notification links must use cockpit.plenora.nl")
        if self.analysis_enabled and (
            self.analysis_provider != "openai"
            or not self.analysis_model
        ):
            raise ValueError(
                "Enabled analysis requires the configured OpenAI provider and model"
            )
        if not 100 <= self.analysis_max_output_tokens <= 2000:
            raise ValueError("COCKPIT_ANALYSIS_MAX_OUTPUT_TOKENS must be between 100 and 2000")
        if not 5 <= self.analysis_timeout_seconds <= 60:
            raise ValueError("COCKPIT_ANALYSIS_TIMEOUT_SECONDS must be between 5 and 60")
        if not 1 <= self.analysis_max_attempts <= 3:
            raise ValueError("COCKPIT_ANALYSIS_MAX_ATTEMPTS must be between 1 and 3")
        if not 1 <= self.analysis_max_observations <= 30 or not 0 <= self.analysis_max_history <= 5:
            raise ValueError("Analysis context limits are invalid")
        if self.ai_monthly_budget_eur <= 0 or self.ai_usd_to_eur_rate <= 0:
            raise ValueError("AI budget and accounting rate must be positive")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [item.strip() for item in self.allowed_origins.split(",") if item.strip()]

    @property
    def hosts(self) -> list[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

    @property
    def notifications_configured(self) -> bool:
        return all((self.notification_email_to, self.notification_email_from,
                    self.notification_smtp_host))


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
