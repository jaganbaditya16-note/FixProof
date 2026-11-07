from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "FixProof"
    app_version: str = "0.1.0"
    environment: str = "development"
    database_path: Path = PROJECT_ROOT / ".fixproof" / "fixproof.db"

    model_config = SettingsConfigDict(
        env_prefix="FIXPROOF_",
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
