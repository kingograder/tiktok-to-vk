from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


class TikTokSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TIKTOK_", env_file=".env", extra="ignore")
    COLLECTION_URL: str
    COOKIES_FILE: str = "cookies.txt"
    PROXY: str | None = None

    @model_validator(mode="before")
    @classmethod
    def empty_str_to_none(cls, values):
        for key in ("PROXY",):
            if key in values and isinstance(values[key], str) and values[key].strip() == "":
                values[key] = None
        return values


class VKSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VK_", env_file=".env", extra="ignore")
    TOKEN: str
    API_VERSION: str = "5.199"
    CLIP_VISIBILITY: str = "all"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", env_file=".env", extra="ignore")
    DOWNLOAD_DIR: str = "downloads"
    CHECK_INTERVAL: int = 1800
    DB_PATH: str = "data/clips.db"
    LOG_DIR: str = ""
    ROTATE_VIDEO: bool = False
    CONCURRENT_DOWNLOADS: int = 3
    CONCURRENT_UPLOADS: int = 3
    MAX_RETRIES: int = 3


class VKUploadSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VK_", env_file=".env", extra="ignore")
    POLL_ATTEMPTS: int = 12
    POLL_INTERVAL: int = 5


class Config:
    tiktok = TikTokSettings()
    vk = VKSettings()
    vk_upload = VKUploadSettings()
    app = AppSettings()


config = Config()
