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

    # Telegram bot
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    # Hermes (OpenAI-compatible inference endpoint, e.g. self-hosted on Railway)
    hermes_base_url: str = ""
    hermes_api_key: str = ""
    hermes_model: str = "hermes-3-llama-3.1-8b"
    hermes_max_tokens: int = 220
    hermes_temperature: float = 0.3

    # Google Maps Platform — used by /route/drive (traffic-aware ETA) and
    # /route/transit (SEPTA-aware door-to-door). Without this both endpoints
    # return 502; the rest of the app continues to work.
    google_maps_api_key: str = ""


settings = Settings()
