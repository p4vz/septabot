from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    pa511_api_key: str = ""

    default_lat: float = 39.9526
    default_lon: float = -75.1652

    nws_user_agent: str = "septabot (https://github.com/p4vz/septabot, contact@example.com)"

    cache_ttl_alerts: int = 60
    cache_ttl_trains: int = 20
    cache_ttl_weather: int = 600
    cache_ttl_traffic: int = 120

    http_timeout: float = 10.0


settings = Settings()
