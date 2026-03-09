"""
配置文件：从环境变量加载所有敏感配置
长连接模式下无需 Encrypt Key 和 Verification Token（SDK 内部处理加密鉴权）
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # ── 飞书应用凭证 ──────────────────────────────────────────
    FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")

    # ── 产品名称（用于 AI 过滤判断）──────────────────────────
    PRODUCT_NAME = os.getenv("PRODUCT_NAME", "本产品")

    # ── 文字对话：DeepSeek ────────────────────────────────────
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    OPENAI_API_URL = os.getenv("OPENAI_API_URL", "https://api.deepseek.com/v1/chat/completions")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "deepseek-chat")

    # ── 图片理解：Qwen-VL ─────────────────────────────────────
    VISION_API_KEY = os.getenv("VISION_API_KEY", "")
    VISION_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    VISION_MODEL = "qwen-vl-max"

    # ── 飞书多维表格（用户反馈收集）────────────────────────────
    BITABLE_APP_TOKEN = os.getenv("BITABLE_APP_TOKEN", "")
    BITABLE_TABLE_ID = os.getenv("BITABLE_TABLE_ID", "")
    FEEDBACK_DEFAULT_ASSIGNEE = os.getenv("FEEDBACK_DEFAULT_ASSIGNEE", "")

    # ── 飞书云文档知识库（逗号分隔多个文档 token）──────────────
    FEISHU_DOC_TOKENS = os.getenv("FEISHU_DOC_TOKENS", "")

    # ── 对话历史配置 ──────────────────────────────────────────
    MAX_HISTORY_TURNS = int(os.getenv("MAX_HISTORY_TURNS", "10"))
    HISTORY_TTL = int(os.getenv("HISTORY_TTL", "1800"))  # 秒，默认 30 分钟

    # ── 管理员（逗号分隔的 open_id，可使用 /reload 等指令）──
    ADMIN_OPEN_IDS: set[str] = {
        uid.strip()
        for uid in os.getenv("ADMIN_OPEN_IDS", "").split(",")
        if uid.strip()
    }

    @classmethod
    def validate(cls):
        """启动时校验必要配置是否齐全"""
        required = {
            "FEISHU_APP_ID": cls.FEISHU_APP_ID,
            "FEISHU_APP_SECRET": cls.FEISHU_APP_SECRET,
            "OPENAI_API_KEY": cls.OPENAI_API_KEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise EnvironmentError(
                f"缺少必要的环境变量，请检查 .env 文件：{', '.join(missing)}"
            )
