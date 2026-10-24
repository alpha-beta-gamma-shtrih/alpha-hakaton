from pathlib import Path
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
    demo_dataset_dir: Path = Path("demo_data/demo_0_3")
    documents_dir: Path = Path(".data/documents")
    llm_enabled: bool = True
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = Field(default="qwen3:4b", min_length=1, max_length=128)
    llm_model_digest: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    llm_timeout_seconds: float = Field(default=45, ge=1, le=120)
    llm_max_parallel: int = Field(default=1, ge=1, le=4)
    csrf_signing_key: SecretStr
    client_session_absolute_ttl_seconds: int = Field(default=28800, gt=0)
    client_session_idle_ttl_seconds: int = Field(default=3600, gt=0)
    bank_session_absolute_ttl_seconds: int = Field(default=14400, gt=0)
    bank_session_idle_ttl_seconds: int = Field(default=900, gt=0)
    login_rate_limit: int = Field(default=10, gt=0)
    login_rate_window_seconds: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_runtime(self) -> "Settings":
        llm_url = urlsplit(self.llm_base_url)
        if (
            llm_url.scheme != "http"
            or not llm_url.hostname
            or llm_url.username
            or llm_url.password
            or llm_url.path not in ("", "/")
            or llm_url.query
            or llm_url.fragment
        ):
            raise ValueError("LLM_BASE_URL must be an internal HTTP origin without credentials")
        if not self.llm_model.strip() or any(char.isspace() for char in self.llm_model):
            raise ValueError("LLM_MODEL must be an Ollama model identifier")
        self.llm_base_url = self.llm_base_url.rstrip("/")
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
