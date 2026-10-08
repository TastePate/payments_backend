from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: SecretStr = Field(min_length=16)

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=55432, ge=1, le=65535)
    postgres_db: str = Field(min_length=1)
    postgres_user: str = Field(min_length=1)
    postgres_password: SecretStr = Field(min_length=1)

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db
        )

    rabbitmq_host: str = "127.0.0.1"
    rabbitmq_port: int = Field(default=5672, ge=1, le=65535)
    rabbitmq_user: str = Field(min_length=1)
    rabbitmq_password: SecretStr = Field(min_length=1)
    
settings = Settings()