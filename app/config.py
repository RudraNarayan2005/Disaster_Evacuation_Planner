"""
Central config, loaded once from environment variables (.env file
locally, or Render's injected environment variables in production).
"""
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "disaster_evac_planner"
    db_user: str = "postgres"
    db_password: str = ""

    openweather_api_key: str = ""
    weather_poll_interval_minutes: int = 15

    admin_username: str = "admin"
    admin_password: str = "ChangeMe123!"

    @property
    def database_url(self) -> str:
        url = os.environ.get("DATABASE_URL")
        if url:
            for prefix in ("postgres://", "postgresql://",
                           "postgresql+psycopg://", "postgresql+psycopg2://"):
                if url.startswith(prefix):
                    url = "postgresql+psycopg2://" + url[len(prefix):]
                    break
            if "sslmode" not in url:
                url += ("&" if "?" in url else "?") + "sslmode=require"
            return url

        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"


settings = Settings()
