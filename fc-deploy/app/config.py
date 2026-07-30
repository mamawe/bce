from __future__ import annotations
"""
BCE 配置中心 — 模型降级链、API 端点、多模态模型
通过 .env 文件加载，支持模型自动降级
"""
import os
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()


# ─── API 端点 ──────────────────────────────────────────────────
LLM_ENDPOINT = os.environ.get(
    "LLM_ENDPOINT",
    "https://open.bigmodel.cn/api/paas/v4/chat/completions",
)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")


# ─── 文本模型降级链 ────────────────────────────────────────────
# 主选 → 备选 → 兜底，逐个尝试，全部失败才抛异常
TEXT_MODEL_CHAIN = [
    os.environ.get("LLM_MODEL", "glm-4.7-flash"),
    *[
        m.strip()
        for m in os.environ.get("LLM_FALLBACK_MODELS", "glm-4-flash-250414,glm-4-flash").split(",")
        if m.strip()
    ],
]

# ─── 多模态模型降级链 ──────────────────────────────────────────
VISION_MODEL_CHAIN = [
    os.environ.get("LLM_VISION_MODEL", "glm-4.6v-flash"),
    *[
        m.strip()
        for m in os.environ.get("LLM_VISION_FALLBACK", "glm-4.1v-thinking-flash,glm-4v-flash").split(",")
        if m.strip()
    ],
]

# ─── 图像/视频生成模型 ─────────────────────────────────────────
IMAGE_MODEL = os.environ.get("LLM_IMAGE_MODEL", "cogview-3-flash")
VIDEO_MODEL = os.environ.get("LLM_VIDEO_MODEL", "cogvideox-flash")


def get_text_models() -> list[str]:
    """获取文本模型降级链"""
    return TEXT_MODEL_CHAIN


def get_vision_models() -> list[str]:
    """获取多模态模型降级链"""
    return VISION_MODEL_CHAIN
