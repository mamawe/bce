"""
BCE - Business Context Engine
FastAPI 主入口，含生命周期管理和样本数据自动导入
"""
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

from app.database import create_tables, is_db_empty, migrate_hierarchy_fields, migrate_evidence_fields, migrate_push_events_table
from app.normalizer.entity_normalizer import seed_aliases
from app.api.routes import router
from app.lark.routes import router as lark_router

# 样本文件目录（相对于 backend/）
SAMPLES_DIR = Path(__file__).parent.parent.parent / "samples"


async def auto_ingest_samples():
    """首次启动时自动导入样本周报（使用 pipeline 编排器）"""
    from app.pipeline import run_ingest_pipeline
    import re

    if not SAMPLES_DIR.exists():
        logger.warning(f"样本目录不存在: {SAMPLES_DIR}，跳过自动导入")
        return

    sample_files = sorted(SAMPLES_DIR.glob("*.md"))
    if not sample_files:
        return

    logger.info(f"首次启动，自动导入 {len(sample_files)} 个样本文件...")

    for filepath in sample_files:
        try:
            content = filepath.read_text(encoding="utf-8")

            # 从内容中提取标题
            title = filepath.stem
            for line in content.split("\n"):
                if line.startswith("# ") and not line.startswith("## "):
                    title = line[2:].strip()
                    break

            result = await run_ingest_pipeline(
                title=title,
                content=content,
                source_url=f"/samples/{filepath.name}",
            )

            logger.info(f"已导入: {title} ({result['doc_id']}) - "
                        f"{result['entities_found']} 实体, {result['events_extracted']} 事件")

        except Exception as e:
            logger.error(f"导入失败 {filepath.name}: {e}")

    logger.info("样本导入完成")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表、种子数据、自动导入"""
    # Startup
    create_tables()
    migrate_hierarchy_fields()
    migrate_evidence_fields()
    migrate_push_events_table()
    seed_aliases()

    # 首次启动自动导入样本
    if is_db_empty():
        await auto_ingest_samples()

    logger.info("服务启动完成")
    yield
    # Shutdown（无需清理）


app = FastAPI(
    title="BCE - Business Context Engine",
    description="AI-native business context engine for weekly report analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: 从环境变量读取允许的前端域名，开发环境默认本地
_allowed_origins = os.environ.get(
    "BCE_ALLOWED_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _allowed_origins.split(",") if o.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router)
app.include_router(lark_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
