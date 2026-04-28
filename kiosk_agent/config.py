import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    remote_api_url: str = "https://mokuture-plus-api.onrender.com/api"
    device_token: str = ""
    media_dir: Path = Path.home() / "kiosk-media"
    static_dir: Path = Path(__file__).parent / "static"
    port: int = 8080
    sync_interval_sec: int = 60
    mock_gpio: bool = False

    # GPIO pin numbers (BCM)
    pir_pin: int = 4
    # JSON string: {"1": 17, "2": 18}  (locker_id → GPIO pin)
    locker_pins_json: str = "{}"

    @property
    def locker_pins(self) -> dict[str, int]:
        return json.loads(self.locker_pins_json)


settings = Settings()
settings.media_dir.mkdir(parents=True, exist_ok=True)
