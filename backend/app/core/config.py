from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr

    # Optional until authenticated operator endpoints are configured.
    operator_token_sha256: SecretStr | None = None
    operator_id: str | None = None

    # Benchmark manifests (relative paths resolve from the project root).
    benchmark_data_dir: str = "data/benchmarks/runs"
