"""Feishu IM push — send notifications with BCE links."""
import json
import logging
import httpx
from .auth import get_tenant_access_token, _headers
from .config import LARK_BASE_URL

logger = logging.getLogger(__name__)


async def send_text_message(receive_id: str, text: str, receive_id_type: str = "open_id", token: str | None = None):
    """Send a plain text message."""
    token = token or await get_tenant_access_token()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{LARK_BASE_URL}/im/v1/messages",
            headers=_headers(token),
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            },
        )
    data = resp.json()
    if data.get("code") != 0:
        logger.error("send_text_message failed: %s", data)
        return None
    return data.get("data", {}).get("message_id")


def build_push_content(doc_title: str, summary_lines: list[str], bce_link: str) -> dict:
    """Build Feishu rich-text (post) message content."""
    bullets = "\n".join(f"· {line}" for line in summary_lines)
    content = [
        [{"tag": "text", "text": f"《{doc_title}》\n\n关键发现：\n"}],
        [{"tag": "text", "text": f"{bullets}\n\n"}],
        [{"tag": "a", "text": "点击查看完整分析", "href": bce_link}],
    ]
    return {"zh_cn": {"title": "📊 新周报已分析完成", "content": content}}


async def send_push_notification(
    receive_id: str,
    doc_title: str,
    summary_lines: list[str],
    bce_link: str,
    receive_id_type: str = "open_id",
    token: str | None = None,
):
    """Send a rich-text push notification with BCE link."""
    token = token or await get_tenant_access_token()
    content = build_push_content(doc_title, summary_lines, bce_link)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{LARK_BASE_URL}/im/v1/messages",
            headers=_headers(token),
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "post",
                "content": json.dumps(content),
            },
        )
    data = resp.json()
    if data.get("code") != 0:
        logger.error("send_push_notification failed: %s", data)
        return None
    msg_id = data.get("data", {}).get("message_id")
    logger.info("Push sent: %s → %s", doc_title, receive_id)
    return msg_id
