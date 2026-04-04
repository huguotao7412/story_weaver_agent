# 环境变量与番茄爽文公式参数配置
# app/core/config.py
from pydantic_settings import BaseSettings
from pydantic import Field


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

    # === 番茄爽文公式全局参数 ===
    MAX_WORDS_PER_CHAPTER: int = Field(default=3000, description="单章字数上限")
    CLIFFHANGER_REQUIREMENT: bool = Field(default=True, description="强制章末悬念钩子")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# 全局单例配置对象
settings = Settings()