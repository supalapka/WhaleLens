from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    moralis_webhook_secret: str = ""
    n_workers: int = 1
    min_score_to_alert: int = 70

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

settings = Settings()
