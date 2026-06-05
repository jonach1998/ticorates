from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    bccr_api_key: str
    bccr_base_url: str
    metrics_trusted_header: str | None = None


settings = Settings()  # type: ignore[call-arg]
