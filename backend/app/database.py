"""
BCE 数据库模块 - SQLite 存储层
负责建表、CRUD 操作
"""
import sqlite3
from pathlib import Path
import os

# 支持环境变量覆盖数据库路径（函数计算场景使用 /tmp/bce.db）
_db_env = os.environ.get("BCE_DB_PATH")
DB_PATH = Path(_db_env) if _db_env else Path(__file__).parent.parent / "bce.db"


def get_connection() -> sqlite3.Connection:
    """获取数据库连接，启用 WAL 模式和外键约束"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def create_tables():
    """启动时创建所有表"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                source_url TEXT,
                ingested_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                lark_user_id TEXT UNIQUE,
                username TEXT,
                display_name TEXT,
                role TEXT NOT NULL DEFAULT 'guest',
                max_sensitivity INTEGER NOT NULL DEFAULT 1,
                has_global_view BOOLEAN DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS user_category_permissions (
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                permission_type TEXT NOT NULL DEFAULT 'view',
                PRIMARY KEY (user_id, category)
            );

            CREATE TABLE IF NOT EXISTS entities (
                entity_id TEXT PRIMARY KEY,
                entity_name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                parent_entity_id TEXT,
                level INTEGER DEFAULT 0,
                sort_order INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS entity_aliases (
                alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                alias_name TEXT NOT NULL,
                FOREIGN KEY (entity_id) REFERENCES entities(entity_id)
            );

            CREATE TABLE IF NOT EXISTS timeline_events (
                event_id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                time_granularity TEXT DEFAULT 'WEEK',
                summary TEXT,
                event_type TEXT,
                attribution TEXT,
                document_id TEXT,
                FOREIGN KEY (entity_id) REFERENCES entities(entity_id),
                FOREIGN KEY (document_id) REFERENCES documents(doc_id)
            );

            CREATE TABLE IF NOT EXISTS decisions (
                decision_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                action_taken TEXT,
                owner TEXT,
                outcome TEXT DEFAULT 'PENDING',
                outcome_detail TEXT,
                FOREIGN KEY (event_id) REFERENCES timeline_events(event_id)
            );

            CREATE TABLE IF NOT EXISTS evidence_links (
                evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id TEXT NOT NULL,
                document_id TEXT,
                doc_title TEXT,
                doc_url TEXT,
                importance_score REAL DEFAULT 2.0,
                reason_code TEXT DEFAULT 'REGULAR',
                FOREIGN KEY (entity_id) REFERENCES entities(entity_id),
                FOREIGN KEY (document_id) REFERENCES documents(doc_id)
            );

            CREATE TABLE IF NOT EXISTS review_queue (
                review_id TEXT PRIMARY KEY,
                entity_id TEXT,
                conflict_type TEXT,
                description TEXT,
                old_value TEXT,
                new_value TEXT,
                status TEXT DEFAULT 'PENDING',
                resolved_by TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS entity_relationships (
                rel_id TEXT PRIMARY KEY,
                source_entity_id TEXT,
                target_entity_id TEXT,
                relation_type TEXT,
                confidence REAL,
                source TEXT,
                evidence_doc_id TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS relationship_candidates (
                candidate_id TEXT PRIMARY KEY,
                entity_a TEXT,
                entity_b TEXT,
                co_occurrence_count INTEGER DEFAULT 1,
                first_seen TEXT,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS push_events (
                event_id TEXT PRIMARY KEY,
                push_id TEXT NOT NULL,          -- identifies the push message
                doc_id TEXT NOT NULL,           -- which document was pushed
                user_id TEXT,                   -- who clicked (from JWT)
                event_type TEXT NOT NULL,       -- 'sent' / 'clicked' / 'viewed'
                created_at TEXT NOT NULL
            );

            -- 宽表：数据仓库产出的事实表，为 Ask 提供 SQL 查询基础
            CREATE TABLE IF NOT EXISTS metric_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                week_label TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT '总体',
                merchant_type TEXT,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                metric_unit TEXT,
                wow_change_pct REAL,
                yoy_change_pct REAL,
                source_doc_id TEXT,
                sensitivity_level INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_aliases_name ON entity_aliases(alias_name);
            CREATE INDEX IF NOT EXISTS idx_events_entity ON timeline_events(entity_id);
            CREATE INDEX IF NOT EXISTS idx_evidence_entity ON evidence_links(entity_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_source ON entity_relationships(source_entity_id);
            CREATE INDEX IF NOT EXISTS idx_relationships_target ON entity_relationships(target_entity_id);
            CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
            CREATE INDEX IF NOT EXISTS idx_push_events_push_id ON push_events(push_id);
            CREATE INDEX IF NOT EXISTS idx_push_events_type ON push_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_metric_facts_lookup ON metric_facts(category, metric_name, week_label);
            CREATE INDEX IF NOT EXISTS idx_metric_facts_merchant ON metric_facts(merchant_type, metric_name);

            CREATE TABLE IF NOT EXISTS insights (
                insight_id TEXT PRIMARY KEY,
                author_id TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                push_id TEXT,
                doc_id TEXT,
                entity_id TEXT,
                metric_snapshot TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS insight_fragments (
                fragment_id TEXT PRIMARY KEY,
                insight_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                entity_id TEXT,
                metric_snapshot TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (insight_id) REFERENCES insights(insight_id)
            );

            CREATE TABLE IF NOT EXISTS insight_distillations (
                distillation_id TEXT PRIMARY KEY,
                batch_source TEXT NOT NULL,
                sample_size INTEGER NOT NULL,
                category_breakdown TEXT,
                summary TEXT NOT NULL,
                raw_llm_output TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_insights_author ON insights(author_id);
            CREATE INDEX IF NOT EXISTS idx_insights_entity ON insights(entity_id);
            CREATE INDEX IF NOT EXISTS idx_fragments_category ON insight_fragments(category);
            CREATE INDEX IF NOT EXISTS idx_fragments_entity ON insight_fragments(entity_id);
            CREATE INDEX IF NOT EXISTS idx_fragments_insight ON insight_fragments(insight_id);
        """)
        conn.commit()
    finally:
        conn.close()

    # 列级迁移：确保旧数据库也具备新字段（每个 ALTER 内部都有存在性检查）
    migrate_hierarchy_fields()
    migrate_evidence_fields()
    migrate_push_events_table()
    migrate_metric_fields()
    migrate_sensitivity_fields()
    migrate_versioning_fields()
    migrate_insight_tables()
    migrate_aliases_unique()


def migrate_hierarchy_fields():
    """为已有数据库添加实体层级字段（ALTER TABLE 迁移）"""
    conn = get_connection()
    try:
        # 检查 parent_entity_id 是否已存在
        cols = conn.execute("PRAGMA table_info(entities)").fetchall()
        col_names = {c["name"] for c in cols}

        if "parent_entity_id" not in col_names:
            conn.execute("ALTER TABLE entities ADD COLUMN parent_entity_id TEXT")
        if "level" not in col_names:
            conn.execute("ALTER TABLE entities ADD COLUMN level INTEGER DEFAULT 0")
        if "sort_order" not in col_names:
            conn.execute("ALTER TABLE entities ADD COLUMN sort_order INTEGER DEFAULT 0")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_parent ON entities(parent_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_level ON entities(level)")
        conn.commit()
    finally:
        conn.close()


def migrate_evidence_fields():
    """为 evidence_links 添加新字段（ALTER TABLE 迁移）"""
    conn = get_connection()
    try:
        cols = conn.execute("PRAGMA table_info(evidence_links)").fetchall()
        col_names = {c["name"] for c in cols}

        if "superseded_by" not in col_names:
            conn.execute("ALTER TABLE evidence_links ADD COLUMN superseded_by TEXT")
        if "label_version" not in col_names:
            conn.execute("ALTER TABLE evidence_links ADD COLUMN label_version INTEGER DEFAULT 1")
        if "effective_score" not in col_names:
            conn.execute("ALTER TABLE evidence_links ADD COLUMN effective_score REAL")
        if "published_at" not in col_names:
            conn.execute("ALTER TABLE evidence_links ADD COLUMN published_at TEXT")

        conn.commit()
    finally:
        conn.close()


def migrate_push_events_table():
    """为已有数据库补建 push_events 表（埋点基础设施）"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS push_events (
                event_id TEXT PRIMARY KEY,
                push_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                user_id TEXT,
                event_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                role TEXT DEFAULT 'viewer',
                is_active INTEGER DEFAULT 1,
                created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_push_events_push_id ON push_events(push_id);
            CREATE INDEX IF NOT EXISTS idx_push_events_type ON push_events(event_type);
        """)
        conn.commit()
    finally:
        conn.close()


def migrate_metric_fields():
    """为 timeline_events 添加指标数值字段（v4 P0：存储真实数值，而非仅摘要文本）"""
    conn = get_connection()
    try:
        col_names = {c["name"] for c in conn.execute("PRAGMA table_info(timeline_events)").fetchall()}

        if "metric_value" not in col_names:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN metric_value REAL")
        if "metric_unit" not in col_names:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN metric_unit TEXT")
        if "metric_delta" not in col_names:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN metric_delta REAL")
        if "metric_delta_pct" not in col_names:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN metric_delta_pct REAL")

        conn.commit()
    finally:
        conn.close()


def migrate_sensitivity_fields():
    """
    事件级敏感度迁移（v4 P0）：
    - 同一实体（如 GMV）的不同事件可有不同敏感级（总 GMV=L1，成本拆解=L4）
    - 因此在 timeline_events 上标记 sensitivity_level
    - entities 上保留 default_sensitivity 作为新建事件的默认值
    - users 表已由 migrate_push_events_table 建立，这里补充 max_sensitivity
    - 新建 user_category_permissions 表（规划文档 8.6.2）控制可见品类
    """
    conn = get_connection()
    try:
        evt_cols = {c["name"] for c in conn.execute("PRAGMA table_info(timeline_events)").fetchall()}
        if "sensitivity_level" not in evt_cols:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN sensitivity_level INTEGER DEFAULT 1")

        ent_cols = {c["name"] for c in conn.execute("PRAGMA table_info(entities)").fetchall()}
        if "default_sensitivity" not in ent_cols:
            conn.execute("ALTER TABLE entities ADD COLUMN default_sensitivity INTEGER DEFAULT 1")
        if "is_overall" not in ent_cols:
            conn.execute("ALTER TABLE entities ADD COLUMN is_overall BOOLEAN DEFAULT 1")
        if "category_scope" not in ent_cols:
            conn.execute("ALTER TABLE entities ADD COLUMN category_scope TEXT")

        user_cols = {c["name"] for c in conn.execute("PRAGMA table_info(users)").fetchall()}
        if "max_sensitivity" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN max_sensitivity INTEGER DEFAULT 1")
        if "has_global_view" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN has_global_view BOOLEAN DEFAULT 0")
        if "lark_user_id" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN lark_user_id TEXT")
        if "username" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_category_permissions (
                permission_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL,
                permission_type TEXT NOT NULL DEFAULT 'view',
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        perm_cols = {c["name"] for c in conn.execute("PRAGMA table_info(user_category_permissions)").fetchall()}
        if "permission_type" not in perm_cols:
            conn.execute(
                "ALTER TABLE user_category_permissions ADD COLUMN permission_type TEXT NOT NULL DEFAULT 'view'"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_perms_user ON user_category_permissions(user_id)"
        )

        conn.commit()
    finally:
        conn.close()


def migrate_versioning_fields():
    """
    文档版本化迁移（v4 P0）：
    - documents.doc_version 记录版本号；superseded_by 指向新版本 doc_id
    - timeline_events.deprecated 标记旧版本事件；doc_version 记录事件所属版本
    """
    conn = get_connection()
    try:
        doc_cols = {c["name"] for c in conn.execute("PRAGMA table_info(documents)").fetchall()}
        if "doc_version" not in doc_cols:
            conn.execute("ALTER TABLE documents ADD COLUMN doc_version INTEGER DEFAULT 1")
        if "superseded_by" not in doc_cols:
            conn.execute("ALTER TABLE documents ADD COLUMN superseded_by TEXT")

        evt_cols = {c["name"] for c in conn.execute("PRAGMA table_info(timeline_events)").fetchall()}
        if "deprecated" not in evt_cols:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN deprecated BOOLEAN DEFAULT 0")
        if "doc_version" not in evt_cols:
            conn.execute("ALTER TABLE timeline_events ADD COLUMN doc_version INTEGER DEFAULT 1")

        conn.commit()
    finally:
        conn.close()


def migrate_insight_tables():
    """
    洞察收集表迁移（v5 预研 → v5.1 审计/状态字段补齐）：
    - insights：原始文本 + 写作上下文（谁、何时、看什么数据写的）
      + status: 处理状态（pending/processing/processed/failed）
      + updated_at: 最后状态变更时间（用于排查卡死任务）
      + error_msg: 失败原因（便于排查，不展示给用户原文）
    - insight_fragments：LLM 拆解后的分类片段（一对多）
    - insight_distillations：定期随机归纳产物（只入库，不接入生产流程）
      + sample_hash: 样本指纹（用于去重，避免短期重复归纳相同样本）
    """
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS insights (
                insight_id TEXT PRIMARY KEY,
                author_id TEXT NOT NULL,
                raw_text TEXT NOT NULL,
                push_id TEXT,
                doc_id TEXT,
                entity_id TEXT,
                metric_snapshot TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS insight_fragments (
                fragment_id TEXT PRIMARY KEY,
                insight_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                entity_id TEXT,
                metric_snapshot TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (insight_id) REFERENCES insights(insight_id)
            );
            CREATE TABLE IF NOT EXISTS insight_distillations (
                distillation_id TEXT PRIMARY KEY,
                batch_source TEXT NOT NULL,
                sample_size INTEGER NOT NULL,
                category_breakdown TEXT,
                summary TEXT NOT NULL,
                raw_llm_output TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_insights_author ON insights(author_id);
            CREATE INDEX IF NOT EXISTS idx_insights_entity ON insights(entity_id);
            CREATE INDEX IF NOT EXISTS idx_fragments_category ON insight_fragments(category);
            CREATE INDEX IF NOT EXISTS idx_fragments_entity ON insight_fragments(entity_id);
            CREATE INDEX IF NOT EXISTS idx_fragments_insight ON insight_fragments(insight_id);
        """)

        # 列级迁移：补齐审计字段（旧库 ALTER，新库 CREATE 已含则跳过）
        insight_cols = {c["name"] for c in conn.execute("PRAGMA table_info(insights)").fetchall()}
        if "status" not in insight_cols:
            conn.execute("ALTER TABLE insights ADD COLUMN status TEXT DEFAULT 'processed'")
        if "updated_at" not in insight_cols:
            conn.execute("ALTER TABLE insights ADD COLUMN updated_at TEXT")
        if "error_msg" not in insight_cols:
            conn.execute("ALTER TABLE insights ADD COLUMN error_msg TEXT")

        distill_cols = {c["name"] for c in conn.execute("PRAGMA table_info(insight_distillations)").fetchall()}
        if "sample_hash" not in distill_cols:
            conn.execute("ALTER TABLE insight_distillations ADD COLUMN sample_hash TEXT")
        if "time_range" not in distill_cols:
            conn.execute("ALTER TABLE insight_distillations ADD COLUMN time_range TEXT")
        if "author_count" not in distill_cols:
            conn.execute("ALTER TABLE insight_distillations ADD COLUMN author_count INTEGER DEFAULT 0")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_insights_status ON insights(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_distill_hash ON insight_distillations(sample_hash)")

        conn.commit()
    finally:
        conn.close()


def migrate_aliases_unique():
    """为 entity_aliases 添加唯一约束索引，防止重复别名"""
    conn = get_connection()
    try:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_aliases_unique ON entity_aliases(entity_id, alias_name)")
        conn.commit()
    finally:
        conn.close()


def is_db_empty() -> bool:
    """检查数据库是否为空（用于首次启动自动导入样本）"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM documents").fetchone()
        return row["cnt"] == 0
    except sqlite3.OperationalError:
        # 表还没创建
        return True
    finally:
        conn.close()


# ─── CRUD Helpers ───────────────────────────────────────────────

def insert_document(doc_id: str, title: str, content: str, source_url: str, ingested_at: str,
                    doc_version: int = 1):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO documents (doc_id, title, content, source_url, ingested_at, doc_version)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(doc_id) DO UPDATE SET
                   title=excluded.title, content=excluded.content,
                   source_url=excluded.source_url, ingested_at=excluded.ingested_at,
                   doc_version=excluded.doc_version""",
            (doc_id, title, content, source_url, ingested_at, doc_version),
        )
        conn.commit()
    finally:
        conn.close()


def get_document(doc_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_documents() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT doc_id, title, source_url, ingested_at FROM documents ORDER BY ingested_at").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def upsert_entity(entity_id: str, entity_name: str, category: str, description: str = ""):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO entities (entity_id, entity_name, category, description)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET
                   entity_name=excluded.entity_name, category=excluded.category,
                   description=excluded.description""",
            (entity_id, entity_name, category, description),
        )
        conn.commit()
    finally:
        conn.close()


def get_entity(entity_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_entities() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM entities ORDER BY entity_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_entity_aliases(entity_id: str) -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT alias_name FROM entity_aliases WHERE entity_id = ?", (entity_id,)).fetchall()
        return [r["alias_name"] for r in rows]
    finally:
        conn.close()


def get_all_aliases() -> dict:
    """Return {entity_id: [alias1, alias2, ...]} for all entities in one query."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT entity_id, alias_name FROM entity_aliases").fetchall()
        result = {}
        for r in rows:
            result.setdefault(r["entity_id"], []).append(r["alias_name"])
        return result
    finally:
        conn.close()


def add_alias(entity_id: str, alias_name: str):
    conn = get_connection()
    try:
        # 避免重复
        existing = conn.execute(
            "SELECT 1 FROM entity_aliases WHERE entity_id = ? AND alias_name = ?",
            (entity_id, alias_name),
        ).fetchone()
        if not existing:
            conn.execute("INSERT INTO entity_aliases (entity_id, alias_name) VALUES (?, ?)", (entity_id, alias_name))
            conn.commit()
    finally:
        conn.close()


def find_entity_by_alias(alias_name: str) -> str | None:
    """通过别名查找实体，返回 entity_id 或 None"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT entity_id FROM entity_aliases WHERE LOWER(alias_name) = LOWER(?)",
            (alias_name,),
        ).fetchone()
        return row["entity_id"] if row else None
    finally:
        conn.close()


def insert_event(event_id: str, entity_id: str, occurred_at: str, time_granularity: str,
                 summary: str, event_type: str, attribution: str, document_id: str,
                 metric_value: float | None = None, metric_unit: str | None = None,
                 metric_delta: float | None = None, metric_delta_pct: float | None = None,
                 sensitivity_level: int = 1, doc_version: int = 1):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO timeline_events
               (event_id, entity_id, occurred_at, time_granularity, summary, event_type,
                attribution, document_id, metric_value, metric_unit, metric_delta,
                metric_delta_pct, sensitivity_level, doc_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(event_id) DO UPDATE SET
                   summary=excluded.summary, event_type=excluded.event_type,
                   attribution=excluded.attribution, entity_id=excluded.entity_id,
                   occurred_at=excluded.occurred_at, time_granularity=excluded.time_granularity,
                   document_id=excluded.document_id, metric_value=excluded.metric_value,
                   metric_unit=excluded.metric_unit, metric_delta=excluded.metric_delta,
                   metric_delta_pct=excluded.metric_delta_pct,
                   sensitivity_level=excluded.sensitivity_level,
                   doc_version=excluded.doc_version""",
            (event_id, entity_id, occurred_at, time_granularity, summary, event_type,
             attribution, document_id, metric_value, metric_unit, metric_delta,
             metric_delta_pct, sensitivity_level, doc_version),
        )
        conn.commit()
    finally:
        conn.close()


def get_events_for_entity(entity_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM timeline_events WHERE entity_id = ? ORDER BY occurred_at",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_events_for_entity_and_related(entity_id: str) -> list[dict]:
    """
    获取实体的时间线事件，包括：
    1. 直接关联的事件
    2. 同名前缀的子实体事件（如 METRIC_GMV 查找 METRIC_GMV_* 的事件）
    3. 通过别名关联的实体事件
    """
    conn = get_connection()
    try:
        # 直接事件
        rows = conn.execute(
            "SELECT * FROM timeline_events WHERE entity_id = ? ORDER BY occurred_at",
            (entity_id,),
        ).fetchall()
        events = [dict(r) for r in rows]

        # 查找 ID 前缀匹配的子实体事件
        # 例如 METRIC_GMV → METRIC_GMV_1,847_万元
        related = conn.execute(
            "SELECT * FROM timeline_events WHERE entity_id LIKE ? ORDER BY occurred_at",
            (f"{entity_id}_%",),
        ).fetchall()
        for r in related:
            events.append(dict(r))

        # 再通过别名查找：查找与此实体同名的其他实体
        entity = conn.execute(
            "SELECT entity_name FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        if entity:
            alias_rows = conn.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias_name = ?",
                (entity["entity_name"],),
            ).fetchall()
            for ar in alias_rows:
                related_id = ar["entity_id"]
                if related_id != entity_id:
                    more = conn.execute(
                        "SELECT * FROM timeline_events WHERE entity_id = ? ORDER BY occurred_at",
                        (related_id,),
                    ).fetchall()
                    for r in more:
                        events.append(dict(r))

        return events
    finally:
        conn.close()


def insert_decision(decision_id: str, event_id: str, action_taken: str, owner: str,
                    outcome: str, outcome_detail: str):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO decisions
               (decision_id, event_id, action_taken, owner, outcome, outcome_detail)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (decision_id, event_id, action_taken, owner, outcome, outcome_detail),
        )
        conn.commit()
    finally:
        conn.close()


def get_decision_for_event(event_id: str) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM decisions WHERE event_id = ?", (event_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_decisions_for_events(event_ids: list[str]) -> dict[str, dict]:
    """批量获取多个事件的决策，返回 {event_id: decision_dict} 映射"""
    if not event_ids:
        return {}
    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(event_ids))
        rows = conn.execute(
            f"SELECT * FROM decisions WHERE event_id IN ({placeholders})", event_ids
        ).fetchall()
        return {row["event_id"]: dict(row) for row in rows}
    finally:
        conn.close()


def insert_evidence(entity_id: str, document_id: str, doc_title: str, doc_url: str,
                    importance_score: float, reason_code: str):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO evidence_links
               (entity_id, document_id, doc_title, doc_url, importance_score, reason_code)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (entity_id, document_id, doc_title, doc_url, importance_score, reason_code),
        )
        conn.commit()
    finally:
        conn.close()


def get_evidence_for_entity(entity_id: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM evidence_links WHERE entity_id = ? ORDER BY importance_score DESC",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Hierarchy CRUD ────────────────────────────────────────────

def upsert_entity_with_hierarchy(entity_id: str, entity_name: str, category: str,
                                  description: str = "", parent_entity_id: str | None = None,
                                  level: int = 0, sort_order: int = 0):
    """创建或更新实体（含层级信息）"""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO entities
               (entity_id, entity_name, category, description, parent_entity_id, level, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entity_id) DO UPDATE SET
                   entity_name=excluded.entity_name, category=excluded.category,
                   description=excluded.description, parent_entity_id=excluded.parent_entity_id,
                   level=excluded.level, sort_order=excluded.sort_order""",
            (entity_id, entity_name, category, description, parent_entity_id, level, sort_order),
        )
        conn.commit()
    finally:
        conn.close()


def update_entity_hierarchy(entity_id: str, parent_entity_id: str, level: int, sort_order: int = 0):
    """更新实体的层级关系"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE entities SET parent_entity_id = ?, level = ?, sort_order = ? WHERE entity_id = ?",
            (parent_entity_id, level, sort_order, entity_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_children(entity_id: str) -> list[dict]:
    """获取直接子实体"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM entities WHERE parent_entity_id = ? ORDER BY sort_order",
            (entity_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_parent(entity_id: str) -> dict | None:
    """获取父实体"""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT p.* FROM entities e
               JOIN entities p ON e.parent_entity_id = p.entity_id
               WHERE e.entity_id = ?""",
            (entity_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def has_children(entity_id: str) -> bool:
    """检查实体是否有子实体"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM entities WHERE parent_entity_id = ?",
            (entity_id,),
        ).fetchone()
        return row["cnt"] > 0
    finally:
        conn.close()


def list_entities_with_hierarchy() -> list[dict]:
    """列出所有实体（含层级字段）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM entities ORDER BY level, sort_order, entity_id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_document_by_title(title: str) -> dict | None:
    """通过标题查找文档（用于重复检查）"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT doc_id, title, ingested_at, doc_version, superseded_by FROM documents WHERE title = ?",
            (title,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_document_by_source(source_url: str) -> dict | None:
    """通过 source_url 查找文档（用于版本化重复检查）"""
    if not source_url:
        return None
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM documents WHERE source_url = ? ORDER BY doc_version DESC LIMIT 1",
            (source_url,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def increment_document_version(doc_id: str) -> int:
    """递增文档版本号并返回新版本号；文档不存在时返回 1"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(doc_version, 1) AS v FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        new_version = (row["v"] if row else 0) + 1
        if row:
            conn.execute(
                "UPDATE documents SET doc_version = ? WHERE doc_id = ?", (new_version, doc_id)
            )
            conn.commit()
        return new_version
    finally:
        conn.close()


def deprecate_events_for_doc(doc_id: str, version: int):
    """
    将文档旧版本（doc_version < version）的时间线事件标记为 deprecated=1。
    旧事件不删除，仅在查询时按 deprecated 过滤，保留历史可追溯。
    """
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE timeline_events SET deprecated = 1
               WHERE document_id = ? AND COALESCE(doc_version, 1) < ?""",
            (doc_id, version),
        )
        conn.commit()
    finally:
        conn.close()


def get_event_sensitivity(event_id: str) -> int:
    """获取单个事件的敏感级；事件不存在时返回 1（默认公开级）"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(sensitivity_level, 1) AS lvl FROM timeline_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return row["lvl"] if row else 1
    finally:
        conn.close()


def set_event_sensitivity(event_id: str, level: int):
    """设置单个事件的敏感级（事件级粒度，覆盖实体默认值）"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE timeline_events SET sensitivity_level = ? WHERE event_id = ?",
            (level, event_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_user_categories(user_id: str) -> list[str]:
    """获取用户被授权的品类列表（user_category_permissions）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT category FROM user_category_permissions WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [r["category"] for r in rows]
    finally:
        conn.close()


def delete_document(doc_id: str):
    """删除文档及其所有关联数据（证据、时间线、决策）"""
    conn = get_connection()
    try:
        # 先查出关联的 timeline_events 的 event_id
        event_ids = [
            r["event_id"]
            for r in conn.execute(
                "SELECT event_id FROM timeline_events WHERE document_id = ?", (doc_id,)
            ).fetchall()
        ]
        # 删除 decisions（通过 event_id 关联）
        if event_ids:
            placeholders = ",".join("?" * len(event_ids))
            conn.execute(f"DELETE FROM decisions WHERE event_id IN ({placeholders})", event_ids)
        # 删除证据、时间线、文档
        conn.execute("DELETE FROM evidence_links WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM timeline_events WHERE document_id = ?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        conn.commit()
    finally:
        conn.close()


def update_document(doc_id: str, title: str, content: str, source_url: str = ""):
    """更新文档标题和内容"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE documents SET title = ?, content = ?, source_url = ? WHERE doc_id = ?",
            (title, content, source_url, doc_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_entity_with_hierarchy(entity_id: str) -> dict | None:
    """获取实体（含层级字段）"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ─── Review Queue CRUD ─────────────────────────────────────────

def insert_review_queue(review_id: str, entity_id: str, conflict_type: str,
                        description: str, old_value: str, new_value: str,
                        status: str = "PENDING"):
    """插入审核队列条目"""
    from datetime import datetime, timezone
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO review_queue
               (review_id, entity_id, conflict_type, description, old_value, new_value, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (review_id, entity_id, conflict_type, description, old_value, new_value,
             status, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_pending_reviews() -> list[dict]:
    """获取所有待审核条目"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM review_queue WHERE status = 'PENDING' ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def resolve_review(review_id: str, resolved_by: str, status: str = "RESOLVED"):
    """解决审核条目"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE review_queue SET status = ?, resolved_by = ? WHERE review_id = ?",
            (status, resolved_by, review_id),
        )
        conn.commit()
    finally:
        conn.close()


# ─── Entity Relationships CRUD ─────────────────────────────────

def insert_entity_relationship(rel_id: str, source_entity_id: str, target_entity_id: str,
                               relation_type: str, confidence: float, source: str,
                               evidence_doc_id: str):
    """插入实体关系"""
    from datetime import datetime, timezone
    conn = get_connection()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO entity_relationships
               (rel_id, source_entity_id, target_entity_id, relation_type, confidence, source, evidence_doc_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (rel_id, source_entity_id, target_entity_id, relation_type, confidence,
             source, evidence_doc_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def get_entity_relationships(entity_id: str, min_confidence: float = 0.5) -> list[dict]:
    """获取实体的关系（双向）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM entity_relationships
               WHERE (source_entity_id = ? OR target_entity_id = ?) AND confidence >= ?
               ORDER BY confidence DESC""",
            (entity_id, entity_id, min_confidence),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Push Event Tracking (埋点) ─────────────────────────────────

def record_push_event(push_id: str, doc_id: str, user_id: str | None, event_type: str) -> str:
    """记录一条推送事件（sent / clicked / viewed），返回 event_id"""
    import uuid
    from datetime import datetime, timezone
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO push_events
               (event_id, push_id, doc_id, user_id, event_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (event_id, push_id, doc_id, user_id, event_type,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return event_id
    finally:
        conn.close()


def get_push_stats(push_id: str) -> dict:
    """统计单条推送的 sent / clicked / viewed 数量及点击率"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT event_type, COUNT(*) AS cnt FROM push_events WHERE push_id = ? GROUP BY event_type",
            (push_id,),
        ).fetchall()
        counts = {r["event_type"]: r["cnt"] for r in rows}
        sent = counts.get("sent", 0)
        clicked = counts.get("clicked", 0)
        viewed = counts.get("viewed", 0)
        rate = (clicked / sent) if sent > 0 else 0.0
        return {
            "push_id": push_id,
            "sent": sent,
            "clicked": clicked,
            "viewed": viewed,
            "rate": round(rate, 4),
        }
    finally:
        conn.close()


def get_push_summary() -> dict:
    """汇总所有推送的整体统计：总发送、总点击、平均点击率"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT event_type, COUNT(*) AS cnt FROM push_events GROUP BY event_type"
        ).fetchall()
        counts = {r["event_type"]: r["cnt"] for r in rows}
        sent = counts.get("sent", 0)
        clicked = counts.get("clicked", 0)
        viewed = counts.get("viewed", 0)

        # 按 push_id 分组计算各推送点击率，再取平均
        per_push = conn.execute(
            """SELECT push_id,
                      SUM(CASE WHEN event_type = 'sent' THEN 1 ELSE 0 END) AS sent,
                      SUM(CASE WHEN event_type = 'clicked' THEN 1 ELSE 0 END) AS clicked
               FROM push_events GROUP BY push_id"""
        ).fetchall()
        rates = [
            (p["clicked"] / p["sent"])
            for p in per_push
            if p["sent"] and p["sent"] > 0
        ]
        avg_rate = (sum(rates) / len(rates)) if rates else 0.0

        return {
            "total_sent": sent,
            "total_clicked": clicked,
            "total_viewed": viewed,
            "overall_rate": round((clicked / sent) if sent > 0 else 0.0, 4),
            "avg_rate": round(avg_rate, 4),
            "push_count": len(per_push),
        }
    finally:
        conn.close()


# ─── Users (推送链接权限实时校验) ────────────────────────────────

def upsert_user(user_id: str, display_name: str = "", role: str = "viewer",
                is_active: bool = True, max_sensitivity: int | None = None,
                has_global_view: bool = False, username: str = ""):
    """
    创建或更新用户。
    v5.2: 补齐 max_sensitivity / has_global_view / username 字段，供 JWT 登录流程使用。
    max_sensitivity 缺省时根据 role 自动推导。
    """
    from datetime import datetime, timezone
    from app.auth.permissions import get_user_max_sensitivity
    if max_sensitivity is None:
        max_sensitivity = get_user_max_sensitivity(role)
    conn = get_connection()
    try:
        # 用 INSERT OR REPLACE 会清空未指定的字段，改用 INSERT OR IGNORE + UPDATE
        conn.execute(
            """INSERT OR IGNORE INTO users (user_id, created_at)
               VALUES (?, ?)""",
            (user_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """UPDATE users SET
               display_name = COALESCE(NULLIF(?, ''), display_name),
               username = COALESCE(NULLIF(?, ''), username),
               role = ?,
               is_active = ?,
               max_sensitivity = ?,
               has_global_view = ?
               WHERE user_id = ?""",
            (display_name, username, role, 1 if is_active else 0,
             max_sensitivity, 1 if has_global_view else 0, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_user(user_id: str) -> dict | None:
    """获取活跃用户；不存在或已停用时返回 None（供 JWT 登录 + 推送链接权限校验）"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND is_active = 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ─── Insights (洞察收集与拆解) ──────────────────────────────────

def insert_insight(insight_id: str, author_id: str, raw_text: str,
                   push_id: str | None = None, doc_id: str | None = None,
                   entity_id: str | None = None, metric_snapshot: str | None = None,
                   status: str = "pending") -> str:
    """
    存储原始洞察文本及其写作上下文。
    status: pending（待 LLM 拆解）/ processing / processed / failed
    异步流程下先用 pending 入库，处理完成再 update_insight_status。
    """
    from datetime import datetime, timezone
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO insights
               (insight_id, author_id, raw_text, push_id, doc_id, entity_id, metric_snapshot, created_at, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (insight_id, author_id, raw_text, push_id, doc_id, entity_id,
             metric_snapshot, datetime.now(timezone.utc).isoformat(), status,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return insight_id
    finally:
        conn.close()


def update_insight_status(insight_id: str, status: str, error_msg: str | None = None):
    """更新洞察处理状态（异步任务追踪）"""
    from datetime import datetime, timezone
    conn = get_connection()
    try:
        conn.execute(
            """UPDATE insights SET status = ?, updated_at = ?, error_msg = ? WHERE insight_id = ?""",
            (status, datetime.now(timezone.utc).isoformat(), error_msg, insight_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_insight_fragments(insight_id: str, author_id: str,
                              fragments: list[dict],
                              entity_id: str | None = None,
                              metric_snapshot: str | None = None) -> int:
    """
    批量插入拆解后的片段。
    fragments: [{"category": "总结", "content": "..."}]
        （片段本身的 entity_id/metric_snapshot 缺省时回退到整个 insight 的上下文，
         保证片段不会丢失上下文关联）
    返回插入条数。
    """
    from datetime import datetime, timezone
    import uuid
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        for frag in fragments:
            frag_id = f"frag_{uuid.uuid4().hex[:12]}"
            # 优先用片段自带上下文，缺省则继承整个洞察的上下文
            frag_entity = frag.get("entity_id") or entity_id
            frag_snapshot = frag.get("metric_snapshot") or metric_snapshot
            conn.execute(
                """INSERT INTO insight_fragments
                   (fragment_id, insight_id, author_id, category, content, entity_id, metric_snapshot, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (frag_id, insight_id, author_id, frag["category"], frag["content"],
                 frag_entity, frag_snapshot, now),
            )
        conn.commit()
        return len(fragments)
    finally:
        conn.close()


def get_insight(insight_id: str) -> dict | None:
    """获取单条原始洞察及其拆解片段"""
    conn = get_connection()
    try:
        insight = conn.execute(
            "SELECT * FROM insights WHERE insight_id = ?", (insight_id,)
        ).fetchone()
        if not insight:
            return None
        fragments = conn.execute(
            "SELECT * FROM insight_fragments WHERE insight_id = ? ORDER BY created_at",
            (insight_id,),
        ).fetchall()
        return {
            **dict(insight),
            "fragments": [dict(f) for f in fragments],
        }
    finally:
        conn.close()


def list_insights_by_entity(entity_id: str, limit: int = 50) -> list[dict]:
    """列出某实体下的所有洞察（不含片段详情）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM insights WHERE entity_id = ? ORDER BY created_at DESC LIMIT ?",
            (entity_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_insights_by_author(author_id: str, limit: int = 50) -> list[dict]:
    """列出某人写的所有洞察"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM insights WHERE author_id = ? ORDER BY created_at DESC LIMIT ?",
            (author_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_random_fragments(sample_size: int = 30, category: str | None = None) -> list[dict]:
    """
    随机抽取片段用于归纳（简单 RANDOM() 版本，保留向后兼容）。
    可按分类筛选，也可全分类随机。
    """
    conn = get_connection()
    try:
        if category:
            rows = conn.execute(
                """SELECT * FROM insight_fragments
                   WHERE category = ?
                   ORDER BY RANDOM() LIMIT ?""",
                (category, sample_size),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM insight_fragments ORDER BY RANDOM() LIMIT ?",
                (sample_size,),
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_random_fragments_stratified(sample_size: int = 30,
                                      category: str | None = None) -> list[dict]:
    """
    按作者分层随机抽样，避免单人主导归纳结果。

    策略（两轮抽样，避免配额浪费）：
    1. 取所有作者列表
    2. 每位作者均匀分配 sample_size // 作者数 条
    3. 余数依次分配给前几位作者
    4. 第一轮抽样：按配额抽取，记录实际拿到数量（可能不足配额）
    5. 第二轮补抽：如果总抽样数不足 sample_size，把剩余配额均匀分给
       还有富余片段的作者，直到补满或所有作者都拿完
    6. 作者过少（=1）时退化为简单随机抽样

    如果没有片段，返回空列表。
    """
    conn = get_connection()
    try:
        # 取作者列表（按 category 过滤）
        if category:
            author_rows = conn.execute(
                "SELECT DISTINCT author_id FROM insight_fragments WHERE category = ?",
                (category,),
            ).fetchall()
        else:
            author_rows = conn.execute(
                "SELECT DISTINCT author_id FROM insight_fragments"
            ).fetchall()
        authors = [r["author_id"] for r in author_rows if r["author_id"]]

        if not authors:
            return []

        # 单作者时退化为简单随机
        if len(authors) == 1:
            return get_random_fragments(sample_size, category)

        def _query_author_fragments(author: str, limit: int, exclude_ids: set[str]) -> list[dict]:
            """抽取某作者的片段，排除已抽到的 fragment_id"""
            if not limit or limit <= 0:
                return []
            if exclude_ids:
                placeholders = ",".join("?" * len(exclude_ids))
                params = [author] + list(exclude_ids) + [limit]
                if category:
                    params = [author, category] + list(exclude_ids) + [limit]
                    sql = f"""SELECT * FROM insight_fragments
                              WHERE author_id = ? AND category = ?
                              AND fragment_id NOT IN ({placeholders})
                              ORDER BY RANDOM() LIMIT ?"""
                else:
                    sql = f"""SELECT * FROM insight_fragments
                              WHERE author_id = ?
                              AND fragment_id NOT IN ({placeholders})
                              ORDER BY RANDOM() LIMIT ?"""
            else:
                params = [author, limit] if not category else [author, category, limit]
                if category:
                    sql = """SELECT * FROM insight_fragments
                             WHERE author_id = ? AND category = ?
                             ORDER BY RANDOM() LIMIT ?"""
                else:
                    sql = """SELECT * FROM insight_fragments
                             WHERE author_id = ?
                             ORDER BY RANDOM() LIMIT ?"""
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

        # 第一轮：按配额抽样
        samples_per_author = max(1, sample_size // len(authors))
        remaining = sample_size % len(authors)

        fragments: list[dict] = []
        drawn_ids: set[str] = set()
        author_actual: dict[str, int] = {}  # 每位作者实际抽到的数量

        for i, author in enumerate(authors):
            limit = samples_per_author + (1 if i < remaining else 0)
            rows = _query_author_fragments(author, limit, set())
            for r in rows:
                fragments.append(r)
                drawn_ids.add(r["fragment_id"])
            author_actual[author] = len(rows)

        # 第二轮：补抽不足的部分
        deficit = sample_size - len(fragments)
        if deficit > 0:
            # 找出还有富余片段的作者（实际抽到的 < 配额的作者可能已拿完，跳过）
            # 简单策略：按作者顺序依次尝试补抽 1 条，循环直到补满或无人可补
            while deficit > 0:
                progress = False
                for author in authors:
                    if deficit <= 0:
                        break
                    rows = _query_author_fragments(author, 1, drawn_ids)
                    if rows:
                        fragments.append(rows[0])
                        drawn_ids.add(rows[0]["fragment_id"])
                        deficit -= 1
                        progress = True
                if not progress:
                    break  # 所有作者都拿完了

        return fragments
    finally:
        conn.close()


def get_recent_distillation_by_hash(sample_hash: str, within_hours: int = 24) -> dict | None:
    """
    归纳去重：检查最近 within_hours 小时内是否已对相同 sample_hash 做过归纳。
    存在则返回该记录，调用方可跳过重复归纳。
    sample_hash 由调用方根据样本 ID 集合生成（排序后哈希）。
    """
    from datetime import datetime, timezone, timedelta
    threshold = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT * FROM insight_distillations
               WHERE sample_hash = ? AND created_at >= ?
               ORDER BY created_at DESC LIMIT 1""",
            (sample_hash, threshold),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def count_fragments() -> dict:
    """统计各分类的片段数量"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM insight_fragments GROUP BY category ORDER BY cnt DESC"
        ).fetchall()
        return {r["category"]: r["cnt"] for r in rows}
    finally:
        conn.close()


def count_insights() -> int:
    """统计原始洞察总数"""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM insights").fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def insert_distillation(distillation_id: str, batch_source: str, sample_size: int,
                         category_breakdown: str, summary: str, raw_llm_output: str,
                         sample_hash: str | None = None,
                         time_range: str | None = None,
                         author_count: int = 0):
    """
    存储一次随机归纳的产出（只入库，不接入生产流程）。
    sample_hash: 样本指纹，用于去重（同一批样本短期内不重复归纳）
    time_range: 样本时间范围（用于展示与审计）
    author_count: 样本作者数（用于判断是否单人主导）
    """
    from datetime import datetime, timezone
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO insight_distillations
               (distillation_id, batch_source, sample_size, category_breakdown, summary,
                raw_llm_output, created_at, sample_hash, time_range, author_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (distillation_id, batch_source, sample_size, category_breakdown,
             summary, raw_llm_output, datetime.now(timezone.utc).isoformat(),
             sample_hash, time_range, author_count),
        )
        conn.commit()
    finally:
        conn.close()


def list_distillations(limit: int = 20) -> list[dict]:
    """列出归纳产出记录（供观察期查看）"""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM insight_distillations ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
