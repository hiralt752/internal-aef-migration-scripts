from pydantic_settings import BaseSettings

class GlobalSetiings(BaseSettings):

    BEARER_TOKEN: str

    class Config:
        env_file = ".env"


settings = GlobalSetiings()