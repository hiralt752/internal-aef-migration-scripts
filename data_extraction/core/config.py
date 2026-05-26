from pydantic_settings import BaseSettings

class GlobalSetiings(BaseSettings):

    API_BASE_URL:str
    BEARER_TOKEN:str
    ASSETS_COOKIE:str

    class Config:
        env_file=".env"

settings = GlobalSetiings()
