from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    public_base_url: str = "http://localhost:8080"
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8080"])
    cookie_secure: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    demo_user_password: SecretStr | None = None
    csrf_signing_key: SecretStr
    client_session_absolute_ttl_seconds: int = Field(default=28800, gt=0)
    client_session_idle_ttl_seconds: int = Field(default=3600, gt=0)
    bank_session_absolute_ttl_seconds: int = Field(default=14400, gt=0)
    bank_session_idle_ttl_seconds: int = Field(default=900, gt=0)
    login_rate_limit: int = Field(default=10, gt=0)
    login_rate_window_seconds: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        key = self.csrf_signing_key.get_secret_value()
        if len(key) < 32 or key.startswith("replace-"):
            raise ValueError("Generate CSRF_SIGNING_KEY (32+ random characters)")
        driver = make_url(self.database_url.get_secret_value()).drivername
        if driver != "postgresql+psycopg" and not (self.app_env == "test" and driver == "sqlite"):
            raise ValueError("Use postgresql+psycopg (SQLite is allowed only for tests)")
        origins = list(dict.fromkeys([self.public_base_url, *self.allowed_origins]))
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Origins must be exact http(s) origins without paths or credentials"
                )
            if self.app_env == "production" and parsed.scheme != "https":
                raise ValueError("Production origins must use HTTPS")
        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("Production session cookies require COOKIE_SECURE=true")
        if self.client_session_idle_ttl_seconds > self.client_session_absolute_ttl_seconds:
            raise ValueError("Client idle TTL must not exceed absolute TTL")
        if self.bank_session_idle_ttl_seconds > self.bank_session_absolute_ttl_seconds:
            raise ValueError("Bank idle TTL must not exceed absolute TTL")
        self.allowed_origins = origins
        return self
