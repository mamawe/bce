from __future__ import annotations
"""Feishu app configuration."""
import os

LARK_APP_ID = os.environ.get("LARK_APP_ID", "cli_xxxxxxxxxxxxxxxx")
LARK_APP_SECRET = os.environ.get("LARK_APP_SECRET", "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
LARK_BASE_URL = "https://open.feishu.cn/open-apis"
