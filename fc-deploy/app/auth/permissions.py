"""Permission checking: event-level sensitivity + category scope filtering.

v5 修复记录：
- 新增 check_insight_access：复用实体权限，控制洞察的读/写
- 新增 get_user_from_request：从请求头解析用户身份（demo 用，与现有 X-User-Role 兼容）
- 新增 require_role_above：用于 distill 等管理类操作的简单角色门槛
"""
import os

from fastapi import HTTPException, Request

ROLE_SENSITIVITY = {
    "admin": 4,
    "executive": 4,
    "dept_lead": 3,
    "category_lead": 2,
    "analyst": 2,
    "guest": 1,
}

# 角色等级（用于管理类操作门槛，与 sensitivity 解耦）
_ROLE_LEVEL = {
    "admin": 5,
    "executive": 4,
    "dept_lead": 3,
    "category_lead": 2,
    "analyst": 2,
    "viewer": 1,
    "guest": 0,
}


def get_user_max_sensitivity(role: str) -> int:
    return ROLE_SENSITIVITY.get(role, 1)


def check_entity_access(user: dict, entity: dict) -> dict:
    """Entity-level gate check."""
    if not user:
        return {"allowed": True, "reason": "no_auth"}  # backward compatible
    entity_sensitivity = entity.get("default_sensitivity", 1)
    if entity_sensitivity > user.get("max_sensitivity", 1):
        return {"allowed": False, "reason": "level_denied"}
    if entity.get("is_overall") and not user.get("has_global_view"):
        return {"allowed": False, "reason": "category_denied"}
    return {"allowed": True, "reason": "ok"}


def check_insight_access(user: dict, insight: dict) -> dict:
    """
    检查用户是否有权限访问某条洞察。
    规则：
    - 用户未登录：拒绝（洞察含敏感业务判断，不公开）
    - 用户是作者本人：允许
    - 洞察无关联实体：允许（已通过登录校验）
    - 否则复用实体权限检查（敏感度+品类范围）
    返回：{"allowed": bool, "reason": str}
    """
    if not user:
        return {"allowed": False, "reason": "no_auth"}

    # 作者本人始终可见自己的洞察
    if insight.get("author_id") and insight.get("author_id") == user.get("user_id"):
        return {"allowed": True, "reason": "owner"}

    # 管理员/高管全可见
    if user.get("role") in ("admin", "executive"):
        return {"allowed": True, "reason": "admin"}

    # 无关联实体：默认允许（已登录即可）
    entity_id = insight.get("entity_id")
    if not entity_id:
        return {"allowed": True, "reason": "no_entity"}

    # 复用实体权限检查
    # 延迟导入避免循环依赖
    from app.database import get_entity
    entity = get_entity(entity_id)
    if not entity:
        # 实体已删除：允许查看洞察原文（保留业务上下文）
        return {"allowed": True, "reason": "entity_deleted"}
    return check_entity_access(user, entity)


def filter_events_by_sensitivity(events: list, user: dict) -> list:
    """Filter timeline events by user's sensitivity + category scope."""
    if not user:
        return events  # no auth = see everything (backward compatible)
    max_sens = user.get("max_sensitivity", 1)
    user_categories = user.get("categories", [])
    has_global = user.get("has_global_view", False)

    filtered = []
    for evt in events:
        evt_sens = evt.get("sensitivity_level", 1)
        if evt_sens > max_sens:
            continue
        # Category scope check would go here if events have category_scope
        filtered.append(evt)
    return filtered


def get_user_from_request(request: Request) -> dict | None:
    """
    从请求头解析用户身份（v5.2 增强）。

    优先级：
    1. Authorization: Bearer <jwt> — 生产模式，JWT 验证 + 从 DB 实时查询角色
    2. X-User-Role: <role> — demo/测试模式，直接信任请求头（仅限内网/开发环境）

    JWT 模式下，角色从 DB 实时查询（避免角色变更后旧 token 仍生效）。
    JWT 验证失败时回退到 X-User-Role（如果存在），否则返回 None。

    返回：
        {"user_id": str, "role": str, "max_sensitivity": int,
         "has_global_view": bool, "categories": list, "auth_method": "jwt" | "header"}
        或 None（未认证）
    """
    # 1. 优先尝试 JWT
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            from app.auth.jwt_links import validate_user_token
            from app.database import get_user, get_user_categories
            payload = validate_user_token(token)
            if payload:
                user_id = payload.get("user_id", "")
                if user_id:
                    user_row = get_user(user_id)
                    if user_row and user_row.get("is_active"):
                        role = user_row.get("role", "viewer")
                        categories = get_user_categories(user_id)
                        return {
                            "user_id": user_id,
                            "username": user_row.get("username") or user_row.get("display_name") or user_id,
                            "role": role,
                            "max_sensitivity": user_row.get("max_sensitivity") or get_user_max_sensitivity(role),
                            "has_global_view": bool(user_row.get("has_global_view")) or role in ("admin", "executive"),
                            "categories": categories,
                            "auth_method": "jwt",
                        }
        except Exception:
            pass  # JWT 验证失败，回退到 header 模式

    # 2. 回退到 X-User-Role（仅限开发环境）
    if os.environ.get("BCE_ENV", "production") != "development":
        return None  # 生产环境不信任 X-User-Role 请求头

    role = request.headers.get("X-User-Role")
    if not role:
        return None
    user_id = request.headers.get("X-User-Id") or role
    categories_header = request.headers.get("X-User-Categories", "")
    categories = [c.strip() for c in categories_header.split(",") if c.strip()] if categories_header else []
    return {
        "user_id": user_id,
        "role": role,
        "max_sensitivity": get_user_max_sensitivity(role),
        "has_global_view": role in ("admin", "executive"),
        "categories": categories,
        "auth_method": "header",
    }


def require_role_above(user: dict | None, min_role: str) -> None:
    """
    简单角色门槛校验。不通过则直接抛 403。
    用于 distill 等管理类操作（避免普通用户随意触发 LLM 归纳消耗资源）。
    """
    if not user:
        raise HTTPException(status_code=401, detail="需要登录")
    user_level = _ROLE_LEVEL.get(user.get("role", "guest"), 0)
    min_level = _ROLE_LEVEL.get(min_role, 99)
    if user_level < min_level:
        raise HTTPException(
            status_code=403,
            detail=f"需要 {min_role} 及以上角色（当前: {user.get('role')}）",
        )
