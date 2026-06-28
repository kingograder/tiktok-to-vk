import sys

from pydantic import ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_HINT = {
    "COLLECTION_URL": "TIKTOK_COLLECTION_URL",
    "TOKEN": "VK_TOKEN",
}


class TikTokSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TIKTOK_", env_file=".env", extra="ignore")
    COLLECTION_URL: str
    COOKIES_FILE: str = "cookies.txt"
    PROXY: str | None = None
    REQUEST_TIMEOUT: int = 30
    RETRY_DELAY: int = 2

    @model_validator(mode="before")
    @classmethod
    def empty_str_to_none(cls, values):
        for key in ("PROXY",):
            if key in values and isinstance(values[key], str):
                val = values[key].strip().strip("\"'")
                if not val:
                    values[key] = None
                elif val != values[key].strip():
                    values[key] = val
        return values


class VKSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VK_", env_file=".env", extra="ignore")
    TOKEN: str
    API_VERSION: str = "5.199"
    CLIP_VISIBILITY: str = "all"
    UPLOAD_TIMEOUT: int = 300
    MIN_INTERVAL: float = 0.35
    POLL_ATTEMPTS: int = 12
    POLL_INTERVAL: int = 5


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")
    DOWNLOAD_DIR: str = "data/downloads"
    CHECK_INTERVAL: int = 3600
    DB_PATH: str = "data/database.db"
    LOG_FILE: str = ""
    ROTATE_VIDEO: bool = False
    CONCURRENT_DOWNLOADS: int = 3
    MAX_RETRIES: int = 3
    CLEAR_DOWNLOADS: bool = True
    TARGET_WIDTH: int = 1080
    TARGET_HEIGHT: int = 1920


def _load_settings() -> tuple[TikTokSettings, VKSettings, AppSettings]:
    try:
        return TikTokSettings(), VKSettings(), AppSettings()
    except ValidationError as e:
        print("Configuration errors:", file=sys.stderr)
        for err in e.errors():
            field = "_".join(str(x) for x in err["loc"])
            env_var = _ENV_HINT.get(field, field)
            msg = err["msg"]
            if "Field required" in msg:
                msg = "is required but not set"
            print(f"  - {env_var}: {msg}", file=sys.stderr)
        print("\nCreate or fix your .env file based on .env.example", file=sys.stderr)
        sys.exit(1)


class Config:
    tiktok: TikTokSettings
    vk: VKSettings
    app: AppSettings


config = Config()
config.tiktok, config.vk, config.app = _load_settings()
