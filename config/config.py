import os
import sys

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict  # noqa: I001

_ENV_HINT = {
    "COLLECTION_URL": "TIKTOK_COLLECTION_URL",
    "COOKIES_FILE": "TIKTOK_COOKIES_FILE",
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
    def clean_values(cls, values):
        for key in ("PROXY",):
            if key in values and isinstance(values[key], str):
                val = values[key].strip().strip("\"'")
                if not val:
                    values[key] = None
                elif val != values[key].strip():
                    values[key] = val
        for key in ("COLLECTION_URL", "COOKIES_FILE"):
            if key in values and isinstance(values[key], str):
                values[key] = values[key].split("#")[0].strip()
        return values

    @field_validator("COLLECTION_URL")
    @classmethod
    def non_empty_collection_url(cls, v):
        if not v or not v.strip():
            raise ValueError("TIKTOK_COLLECTION_URL must not be empty")
        return v

    @field_validator("COOKIES_FILE")
    @classmethod
    def cookies_file_exists(cls, v):
        if v and not os.path.isfile(v):
            raise ValueError(f"Cookies file not found: {v}")
        return v

    @field_validator("REQUEST_TIMEOUT", "RETRY_DELAY")
    @classmethod
    def positive_int(cls, v):
        if v <= 0:
            raise ValueError(f"Must be positive, got {v}")
        return v


class VKSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VK_", env_file=".env", extra="ignore")
    TOKEN: str
    API_VERSION: str = "5.199"
    CLIP_VISIBILITY: str = "all"
    UPLOAD_TIMEOUT: int = 300
    MIN_INTERVAL: float = 0.35
    POLL_ATTEMPTS: int = 12
    POLL_INTERVAL: int = 5

    @field_validator("TOKEN")
    @classmethod
    def non_empty_token(cls, v):
        if not v or not v.strip():
            raise ValueError("VK_TOKEN must not be empty")
        return v

    @field_validator("UPLOAD_TIMEOUT", "POLL_ATTEMPTS", "POLL_INTERVAL")
    @classmethod
    def positive_int(cls, v):
        if v <= 0:
            raise ValueError(f"Must be positive, got {v}")
        return v

    @field_validator("MIN_INTERVAL")
    @classmethod
    def non_negative_float(cls, v):
        if v < 0:
            raise ValueError(f"Must be non-negative, got {v}")
        return v


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")
    DOWNLOAD_DIR: str = "data/downloads"
    TEMP_DIR: str = "data/temp"
    CHECK_INTERVAL: int = 3600
    DB_PATH: str = "data/database.db"
    LOG_FILE: str = ""
    ROTATE_VIDEO: bool = False
    CONCURRENT_DOWNLOADS: int = 3
    MAX_RETRIES: int = 3
    CLEAR_DOWNLOADS: bool = True
    TARGET_WIDTH: int = 1080
    TARGET_HEIGHT: int = 1920

    @field_validator("CONCURRENT_DOWNLOADS", "MAX_RETRIES")
    @classmethod
    def positive_int(cls, v):
        if v <= 0:
            raise ValueError(f"Must be positive, got {v}")
        return v

    @field_validator("CHECK_INTERVAL")
    @classmethod
    def non_negative_int(cls, v):
        if v < 0:
            raise ValueError(f"Must be non-negative, got {v}")
        return v


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
