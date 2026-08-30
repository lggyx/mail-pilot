"""应用配置：全部从 .env 读取（见 .env.example）。"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 会话签名密钥
    secret_key: str = "dev-secret-change-me"
    # 单用户登录
    app_username: str = "admin"
    app_password: str = "admin"

    # 存储
    data_dir: Path = Path("./data")

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    run_scheduler: bool = True
    static_dir: str | None = "../frontend/dist"
    log_level: str = "info"

    # 发送默认参数（活动可覆盖）
    default_batch_size: int = 50
    default_rate_per_minute: int = 60
    default_max_retries: int = 3


settings = Settings()
