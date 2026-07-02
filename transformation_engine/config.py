from pydantic_settings import BaseSettings, SettingsConfigDict

class GlobalSetiings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    BEARER_TOKEN: str


settings = GlobalSetiings()
