from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    jwt_secret_key: str = "dev_secret_change_in_production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 8
    admin_username: str = "admin"
    admin_password: str = "admin1234"

    class Config:
        env_file = ".env"


settings = Settings()
