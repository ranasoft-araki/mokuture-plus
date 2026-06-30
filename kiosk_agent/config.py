import json
import platform
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    tenant_slug: str = ""
    remote_api_url: str = "https://mokuture-plus-api.onrender.com/api"
    media_dir: Path = Path.home() / "kiosk-media"
    static_dir: Path = Path(__file__).parent / "static"
    port: int = 8080
    sync_interval_sec: int = 60
    mock_gpio: bool = False
    # フロントを実バックエンド無しのモックで動かす。既定は Windows(開発機)で True。
    # 環境変数 KIOSK_MOCK=true/false で明示的に上書き可能(例: 本番Piでは自動的に False)。
    kiosk_mock: bool = platform.system() == "Windows"

    # GPIO pin numbers (BCM)
    pir_pin: int = 4
    door_pin: int | None = None
    # JSON string: {"1": 12, "2": 16, "3": 26}  (door_id -> GPIO pin)
    door_pins_json: str = '{"1": 12, "2": 16, "3": 26}'
    # JSON string: {"1": 14, "2": 15, "3": 18}  (locker_id -> GPIO pin)
    locker_pins_json: str = '{"1": 14, "2": 15, "3": 18}'
    camera_device: str = "/dev/video0"

    @property
    def locker_pins(self) -> dict[str, int]:
        return {str(locker_id): int(pin) for locker_id, pin in json.loads(self.locker_pins_json).items()}

    @property
    def door_pins(self) -> dict[str, int]:
        pins = json.loads(self.door_pins_json)
        if pins:
            return {str(door_id): int(pin) for door_id, pin in pins.items()}
        if self.door_pin is None:
            return {}
        return {"1": int(self.door_pin)}


settings = Settings()
