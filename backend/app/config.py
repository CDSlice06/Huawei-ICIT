"""应用配置：通过 pydantic-settings 读取环境变量（design.md §2.8.3 环境变量清单）。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 数据库
    DATABASE_URL: str = "mysql+aiomysql://memweave:memweave@127.0.0.1:3306/memweave"

    # Redis
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # 会话
    SESSION_TTL_HOURS: int = 24

    # 运维通道（演示账号远程重置，tasks.md 任务9.3）
    ADMIN_TOKEN: str = ""

    # MaaS 大模型
    MAAS_API_KEY: str = ""
    MAAS_ENDPOINT: str = ""
    MAAS_TEXT_TIMEOUT: float = 30.0
    MAAS_MULTIMODAL_TIMEOUT: float = 120.0

    # OBS
    OBS_AK: str = ""
    OBS_SK: str = ""
    OBS_BUCKET: str = "memweave-assets"
    OBS_ENDPOINT: str = ""

    # 演示账号
    DEMO_ACCOUNT_EMAIL: str = "demo@memweave.cn"
    DEMO_ACCOUNT_PASSWORD: str = "MemWeave2026"

    # 调度器
    ENABLE_SCHEDULER: bool = True

    # 异步任务
    TASK_MAX_WORKERS: int = 8
    TASK_RETRY_MAX: int = 2

    # 业务约束
    TEXT_MAX_CHARS: int = 5000
    SINGLE_USER_RUNNING_TASK_LIMIT: int = 2

    @property
    def session_ttl_seconds(self) -> int:
        return max(self.SESSION_TTL_HOURS, 24) * 3600


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()