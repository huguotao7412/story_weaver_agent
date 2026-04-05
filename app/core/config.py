# 环境变量与番茄爽文公式参数配置
# app/core/config.py
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field

# 动态获取项目根目录 (假设此文件位于 app/core/config.py，向上退三级即为项目根目录)
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    # === API Keys 配置 ===
    OPENAI_API_KEY: str = Field(default="")
    DEEPSEEK_API_KEY: str = Field(default="")
    ANTHROPIC_API_KEY: str = Field(default="")

    # === 模型基座配置 ===
    # 重文本生成模型：负责主笔/文风解构
    HEAVY_TEXT_MODEL: str = Field(default="claude-3-5-sonnet-20240620")
    # 重逻辑判断模型：负责逻辑审查/规划
    LOGIC_REASON_MODEL: str = Field(default="gpt-4o")

    # === 🌟 数据存储与目录配置 (升级版沙盒隔离) ===
    DATA_DIR: Path = Field(default=BASE_DIR / "data", description="全局数据根目录")
    REFERENCES_DIR: Path = Field(default=BASE_DIR / "data" / "references", description="参考神作文本目录")

    # === 番茄爽文公式全局参数 ===
    MAX_WORDS_PER_CHAPTER: int = Field(default=2500, description="单章字数上限")
    CLIFFHANGER_REQUIREMENT: bool = Field(default=True, description="强制章末悬念钩子")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # 忽略 .env 中可能存在的多余非规范环境变量


# 全局单例配置对象
settings = Settings()

# 🌟 系统启动时自动创建所需的基础数据目录
_directories_to_create = [
    settings.DATA_DIR,
    settings.REFERENCES_DIR
]

for d in _directories_to_create:
    os.makedirs(d, exist_ok=True)