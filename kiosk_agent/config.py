import json
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": 同じ .env には、ここで宣言していない設定(ANALYTICS_* / LOCKER_OPEN_* /
    # KIOSK_OTA_DISABLE / KANA_DICT_EXTRA / VOICE_*__* / CARD_*__* ― それぞれのモジュールが
    # os.getenv 等で読む)も書く。既定の extra="forbid" だと、それらを1行書いただけで
    # エージェントが起動しなくなる。
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tenant_slug: str = ""
    remote_api_url: str = "https://mokuture-plus-api.onrender.com/api"
    media_dir: Path = Path.home() / "kiosk-media"
    static_dir: Path = Path(__file__).parent / "static"
    port: int = 8080
    sync_interval_sec: int = 60
    mock_gpio: bool = False
    locker_pulse_sec: float = 1.0
    systemd_watchdog_browser_required: bool = False
    systemd_watchdog_browser_startup_grace_sec: int = 300
    systemd_watchdog_browser_stale_sec: int = 45
    # 注: 旧 kiosk_mock(ブラウザ全スタブをWindowsで自動有効化)は廃止。ハードは agent 層で
    # 自動モック(main.py の _MOCK_DEVICE=非Linux / MOCK_GPIO env・gpio.py)、ブラウザは常に
    # 実経路を通す。バックエンド不要の完全オフラインUIプレビューは kiosk.html?mock=1 のみ。

    # GPIO pin numbers (BCM)
    pir_pin: int = 4
    # 来訪を検知するセンサー。pir=人感センサー(GPIO・既定) / vl53l0x・vl53l1x=距離センサー(I2C)
    presence_sensor: str = "pir"
    # 距離センサーのとき: この距離(mm)以内を来訪とみなす
    tof_threshold_mm: int = 1000
    # 距離センサーのとき: 近い(遠い)読みが何回続いたら検知(解除)にするか。読みは 1 秒に 8 回前後
    tof_confirm_reads: int = 3
    # 距離センサーのとき: 近いままがこの秒数続いたら、離れるまで検知を止める(置かれた物で起き続けない)
    tof_stale_sec: float = 60.0
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
