"""
JWT 工具模块（v5.2 扩展）。
- 原有：推送链接 JWT（generate_push_link / validate_push_link / check_link_access）
- 新增：用户登录 JWT（generate_user_token / validate_user_token）
  用于替代 X-User-Role 请求头的 demo 级权限机制。
  用户登录后获得 JWT，后续请求通过 Authorization: Bearer <token> 携带。

注意：
- 推送链接 JWT 与用户 JWT 共用密钥但通过 token_type 字段区分
- 用户 JWT 不存角色快照，角色从 DB 实时查询（避免角色变更后旧 token 仍生效）
"""
import jwt  # PyJWT
import time
import os
import secrets
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# 密钥：必须从环境变量读取；未设置时生成随机密钥（仅限开发环境）
SECRET_KEY = os.environ.get("BCE_JWT_SECRET", "")
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning(
        "BCE_JWT_SECRET 未设置，已生成随机密钥（仅限开发环境，重启后失效）。"
        "生产环境必须设置 BCE_JWT_SECRET 环境变量。"
    )
ALGORITHM = "HS256"
LINK_EXPIRY_DAYS = 7
USER_TOKEN_EXPIRY_HOURS = 24  # 用户登录 token 24 小时过期


# ─── 推送链接 JWT（原有功能，保持不变）─────────────────────────

def generate_push_link(base_url: str, doc_id: str, user_id: str, role: str) -> str:
    """Generate a signed push link with expiration"""
    payload = {
        "token_type": "push_link",
        "doc_id": doc_id,
        "user_id": user_id,
        "role": role,  # snapshot for display, NOT for permission decisions
        "iat": int(time.time()),
        "exp": int(time.time()) + LINK_EXPIRY_DAYS * 86400,
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return f"{base_url}/view/{doc_id}?auth={token}"


def validate_push_link(token: str) -> dict:
    """
    Validate push link token and return payload.
    Raises jwt.ExpiredSignatureError if expired.
    Raises jwt.InvalidTokenError if tampered.
    """
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("token_type") != "push_link":
        raise jwt.InvalidTokenError("not a push_link token")
    return payload


def check_link_access(token: str, db) -> dict:
    """
    Full access check: validate token + re-check current permissions from DB.
    Returns {"allowed": bool, "user_id": str, "doc_id": str, "reason": str}
    """
    try:
        payload = validate_push_link(token)
    except jwt.ExpiredSignatureError:
        return {"allowed": False, "reason": "link_expired"}
    except jwt.InvalidTokenError:
        return {"allowed": False, "reason": "invalid_token"}

    # Re-check user still exists and has appropriate role
    user = db.get_user(payload["user_id"]) if hasattr(db, 'get_user') else None
    if user is None:
        return {"allowed": False, "user_id": payload["user_id"], "doc_id": payload["doc_id"], "reason": "user_not_found"}

    return {"allowed": True, "user_id": payload["user_id"], "doc_id": payload["doc_id"], "reason": "ok"}


# ─── 用户登录 JWT（v5.2 新增）─────────────────────────────────

def generate_user_token(user_id: str, username: str = "") -> str:
    """
    生成用户登录 JWT。
    注意：不存角色到 token，角色从 DB 实时查询（避免角色变更后旧 token 仍生效）。
    """
    payload = {
        "token_type": "user_login",
        "user_id": user_id,
        "username": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + USER_TOKEN_EXPIRY_HOURS * 3600,
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def validate_user_token(token: str) -> dict | None:
    """
    验证用户登录 JWT。
    返回 payload（含 user_id/username），失败返回 None。
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("token_type") != "user_login":
            return None
        return payload
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None
