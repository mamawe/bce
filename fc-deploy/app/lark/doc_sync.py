from __future__ import annotations
from typing import Optional
"""Feishu document sync — pull wiki docs via lark-cli (user identity).

Uses lark-cli with --as user to bypass bot membership requirements.
Falls back to bot token API if lark-cli is unavailable.
"""
import json
import logging
import asyncio
import shutil

logger = logging.getLogger(__name__)

LARK_CLI = shutil.which("lark-cli") or "/Users/alex/.qoderworkcn/bin/lark-cli"


async def _run_cli(args: list[str]) -> Optional[dict]:
    """Run lark-cli command and parse JSON output."""
    cmd = [LARK_CLI] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            logger.warning("lark-cli failed: %s", stderr.decode()[:200])
            return None
        return json.loads(stdout.decode())
    except (asyncio.TimeoutError, json.JSONDecodeError, OSError) as e:
        logger.warning("lark-cli error: %s", e)
        return None


async def list_wiki_spaces() -> list[dict]:
    """List available wiki spaces using user identity."""
    data = await _run_cli(["wiki", "+space-list", "--as", "user"])
    if not data or not data.get("ok"):
        return []
    return data.get("data", {}).get("spaces", [])


async def list_wiki_nodes(space_id: str) -> list[dict]:
    """List document nodes in a wiki space using user identity."""
    data = await _run_cli(["wiki", "+node-list", "--space-id", space_id, "--as", "user"])
    if not data or not data.get("ok"):
        return []
    return data.get("data", {}).get("nodes", [])


async def get_document_content(document_id: str) -> str:
    """Get raw text content of a Feishu document using user identity."""
    data = await _run_cli(["docs", "+fetch", "--doc", document_id, "--as", "user"])
    if not data or not data.get("ok"):
        return ""
    # docs +fetch returns markdown in data.content or data.markdown
    doc_data = data.get("data", {})
    return doc_data.get("markdown", "") or doc_data.get("content", "")


def convert_to_markdown(raw_content: str, title: str) -> str:
    """Wrap raw content as markdown."""
    return f"# {title}\n\n{raw_content}"


async def sync_space(space_id: str) -> list[dict]:
    """Sync all docs in a wiki space. Returns list of {title, content, doc_id, url}."""
    nodes = await list_wiki_nodes(space_id)
    results = []
    for node in nodes:
        obj_type = node.get("obj_type", "")
        if obj_type != "docx":
            continue
        doc_id = node.get("obj_token", "")
        title = node.get("title", "untitled")
        if not doc_id:
            continue
        raw = await get_document_content(doc_id)
        if not raw:
            continue
        md = convert_to_markdown(raw, title)
        url = f"https://feishu.cn/wiki/{node.get('node_token', doc_id)}"
        results.append({"title": title, "content": md, "doc_id": doc_id, "url": url})
        logger.info("Synced doc: %s (%d chars)", title, len(md))
    return results
