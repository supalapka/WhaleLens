from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

class Settings(BaseSettings):
    moralis_api_key: str = ""
    moralis_stream_id: str = ""
    moralis_pair_stream_id: str = ""
    moralis_webhook_secret: str = ""
    webhook_url: str = ""
    n_workers: int = 1
    min_score_to_alert: int = 70
    alert_cooldown_hours: int = 6
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    database_url: str = ""
    alchemy_api_key: str = ""

    model_config = {"env_file": BASE_DIR / ".env", "env_file_encoding": "utf-8"}

settings = Settings()
