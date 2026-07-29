"""Feishu integration API routes."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .doc_sync import list_wiki_spaces, list_wiki_nodes, sync_space
from .im_push import send_text_message, send_push_notification

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/lark", tags=["lark"])


class SyncRequest(BaseModel):
    space_id: str


class PushTestRequest(BaseModel):
    receive_id: str
    text: str


class PushRequest(BaseModel):
    receive_id: str
    doc_title: str
    summary_lines: list[str]
    bce_link: str


@router.get("/spaces")
async def get_spaces():
    """List available Feishu wiki spaces."""
    spaces = await list_wiki_spaces()
    return {"spaces": spaces}


@router.get("/spaces/{space_id}/docs")
async def get_space_docs(space_id: str):
    """List documents in a wiki space."""
    nodes = await list_wiki_nodes(space_id)
    docs = [
        {"title": n.get("title", ""), "obj_token": n.get("obj_token", ""), "obj_type": n.get("obj_type", "")}
        for n in nodes
    ]
    return {"docs": docs}


@router.post("/sync")
async def sync_docs(req: SyncRequest):
    """Sync all docs in a wiki space and run ingest pipeline."""
    from app.pipeline import run_ingest_pipeline

    docs = await sync_space(req.space_id)
    if not docs:
        return {"synced": 0, "results": [], "message": "No docx documents found in space"}

    results = []
    for doc in docs:
        try:
            result = await run_ingest_pipeline(
                title=doc["title"],
                content=doc["content"],
                source_url=doc["url"],
            )
            results.append({"title": doc["title"], "status": "ok", "detail": result})
        except Exception as e:
            logger.error("Ingest failed for %s: %s", doc["title"], e)
            results.append({"title": doc["title"], "status": "error", "detail": str(e)})

    return {"synced": len(results), "results": results}


@router.post("/push-test")
async def push_test(req: PushTestRequest):
    """Send a test text message."""
    msg_id = await send_text_message(req.receive_id, req.text)
    if not msg_id:
        raise HTTPException(502, "Failed to send message")
    return {"message_id": msg_id}


@router.post("/push")
async def push_notification(req: PushRequest):
    """Send a rich-text push notification with BCE link."""
    msg_id = await send_push_notification(
        receive_id=req.receive_id,
        doc_title=req.doc_title,
        summary_lines=req.summary_lines,
        bce_link=req.bce_link,
    )
    if not msg_id:
        raise HTTPException(502, "Failed to send push notification")
    return {"message_id": msg_id}
