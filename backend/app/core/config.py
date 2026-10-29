import re
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnvironment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: AppEnvironment = "development"

    database_url: SecretStr

    # Optional until authenticated operator endpoints are configured.
    operator_token_sha256: SecretStr | None = None
    operator_id: str | None = None

    # Benchmark manifests (relative paths resolve from the project root).
    benchmark_data_dir: str = "data/benchmarks/runs"

    # Comma-separated browser origins allowed to call the API directly.
    # Empty means same-origin only (the default behind the Vite or nginx proxy).
    cors_origins: str = ""

    def allowed_origins(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


class ConfigurationError(RuntimeError):
    """The process must not start with this configuration."""


def validate_runtime_settings(settings: Settings) -> None:
    """Fail fast on configuration that is unsafe for the selected environment."""
    origins = settings.allowed_origins()
    if "*" in origins:
        raise ConfigurationError("Wildcard CORS origins are not allowed")
    for origin in origins:
        if re.fullmatch(r"https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?", origin) is None:
            raise ConfigurationError(f"Invalid CORS origin: {origin}")

    if settings.app_env != "production":
        return

    digest = (
        settings.operator_token_sha256.get_secret_value()
        if settings.operator_token_sha256
        else ""
    )
    if re.fullmatch(r"[0-9a-fA-F]{64}", digest) is None or not settings.operator_id:
        raise ConfigurationError(
            "Production requires OPERATOR_TOKEN_SHA256 (64 hex characters) and OPERATOR_ID"
        )
    if any(origin.startswith("http://") for origin in origins):
        raise ConfigurationError("Production CORS origins must use https")
