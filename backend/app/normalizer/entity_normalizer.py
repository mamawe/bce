"""
实体标准化器 - 将 LLM 提取的原始实体名映射到已有实体或创建新实体
维护别名表，支持大小写不敏感匹配
"""
from app import database as db

# ─── 模块级缓存 ─────────────────────────────────────────────────
# 缓存结构: {entity_id: {"entity_name": str, "category": str, "aliases": [str, ...]}}
_entity_cache: dict[str, dict] | None = None


def _load_cache() -> dict[str, dict]:
    """从数据库加载所有实体及其别名到缓存"""
    global _entity_cache
    if _entity_cache is not None:
        return _entity_cache

    cache: dict[str, dict] = {}
    all_entities = db.list_entities()
    for ent in all_entities:
        eid = ent["entity_id"]
        cache[eid] = {
            "entity_name": ent["entity_name"],
            "category": ent["category"],
            "aliases": db.get_entity_aliases(eid),
        }
    _entity_cache = cache
    return _entity_cache


def invalidate_cache():
    """清除实体缓存（在导入新数据后调用）"""
    global _entity_cache
    _entity_cache = None


# 预置别名映射：标准化名称 -> 别名列表
# 格式: (entity_name, category, description, [aliases])
SEED_ALIASES = [
    ("GMV", "METRIC", "成交总额", ["成交总额", "流水", "交易额", "日均 GMV", "日均GMV"]),
    ("CTR", "METRIC", "点击率", ["点击率", "点击通过率"]),
    ("DAU", "METRIC", "日活跃用户数", ["日活", "日活跃用户"]),
    ("CAC", "METRIC", "获客成本", ["获客成本", "用户获取成本"]),
    ("转化率", "METRIC", "转化率", ["CVR", "Conversion Rate"]),
    # 商户类型：标准化名称不带"店"后缀，别名包含带"店"的变体
    ("沙县小吃", "OWNER", "沙县小吃商户类型", ["沙县小吃店", "沙县小吃商户"]),
    ("酸辣粉", "OWNER", "酸辣粉商户类型", ["酸辣粉店", "酸辣粉商户"]),
    ("兰州拉面", "OWNER", "兰州拉面商户类型", ["兰州拉面店", "兰州拉面商户"]),
    ("黄焖鸡", "OWNER", "黄焖鸡商户类型", ["黄焖鸡店", "黄焖鸡商户"]),
    ("麻辣烫", "OWNER", "麻辣烫商户类型", ["麻辣烫店", "麻辣烫商户"]),
]


def seed_aliases():
    """初始化预置别名（仅在表为空时执行）"""
    conn = db.get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM entity_aliases").fetchone()
        if row["cnt"] > 0:
            return  # 已有数据，跳过
    finally:
        conn.close()

    for name, category, desc, aliases in SEED_ALIASES:
        entity_id = f"{category}_{name.upper()}"
        db.upsert_entity(entity_id, name, category, desc)
        # 实体名本身也作为别名
        db.add_alias(entity_id, name)
        for alias in aliases:
            db.add_alias(entity_id, alias)


def normalize_entity(raw_text: str, category: str) -> str:
    """
    将原始实体文本标准化为 entity_id
    1. 先查别名表（大小写不敏感）
    2. 子串匹配：检查已有实体的名称/别名是否是 raw_text 的子串
       （处理 "GMV 1,847 万元" → 匹配 "GMV" → METRIC_GMV 的情况）
    3. 找不到则创建新实体
    返回 entity_id
    """
    # Step 1: 尝试通过别名精确匹配
    entity_id = db.find_entity_by_alias(raw_text)
    if entity_id:
        return entity_id

    # Step 2: 尝试用 cleaned 文本匹配
    cleaned = raw_text.strip()
    entity_id = db.find_entity_by_alias(cleaned)
    if entity_id:
        return entity_id

    # Step 3: 双向子串匹配（带空格归一化和前缀约束）
    # 正向：已有实体名称是 raw_text 的子串（如 "GMV" in "GMV 1,847 万元"）
    #   约束：实体名必须是 raw 的前缀，避免 "蔬菜 日均 GMV（万元）271" 误匹配到 GMV
    # 反向：raw_text 是已有实体名称的子串（如 "沙县小吃" in "沙县小吃店"）
    # 空格归一化：比较前去除所有空格，解决 "SKU宽度" 无法匹配 "SKU 宽度 7.8" 的问题
    cache = _load_cache()
    candidates = []
    for eid, ent_info in cache.items():
        names = [ent_info["entity_name"]]
        names.extend(ent_info["aliases"])
        for name in names:
            if len(name) < 2:
                continue
            name_ns = name.lower().replace(" ", "")
            cleaned_ns = cleaned.lower().replace(" ", "")
            if not name_ns or not cleaned_ns:
                continue
            # 反向匹配：raw 是实体名的子串（raw 是简称，实体是全称）—— 安全
            if cleaned_ns in name_ns:
                candidates.append((len(name), eid))
                continue
            # 正向匹配：实体名是 raw 的子串
            # 约束：实体名必须是 raw 的前缀（如 "GMV" 是 "GMV 1,847 万元" 的前缀）
            # 这样 "蔬菜 日均 GMV（万元）271" 不会因为包含 "GMV" 就匹配到 GMV
            if name_ns in cleaned_ns and cleaned_ns.startswith(name_ns):
                candidates.append((len(name), eid))

    if candidates:
        # 取最长匹配（最具体的）
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_id = candidates[0][1]
        db.add_alias(best_id, raw_text)
        # 更新缓存
        if best_id in cache:
            cache[best_id]["aliases"].append(raw_text)
        return best_id

    # Step 4: 创建新实体
    safe_name = cleaned.upper().replace(" ", "_").replace("（", "").replace("）", "")
    new_id = f"{category}_{safe_name}"

    # 检查是否已存在同名实体
    existing = db.get_entity(new_id)
    if existing:
        db.add_alias(new_id, raw_text)
        # 更新缓存
        if new_id in cache:
            cache[new_id]["aliases"].append(raw_text)
        return new_id

    db.upsert_entity(new_id, cleaned, category, "")
    db.add_alias(new_id, raw_text)
    # 更新缓存
    cache[new_id] = {"entity_name": cleaned, "category": category, "aliases": [raw_text]}
    return new_id


def get_entity_display_name(entity_id: str) -> str:
    """获取实体的显示名称"""
    entity = db.get_entity(entity_id)
    return entity["entity_name"] if entity else entity_id
