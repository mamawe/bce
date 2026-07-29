# BCE API Contract v1

## Base URL
`http://localhost:8000/api/v1`

## Core Endpoints

### GET /context?entity_id={id}
Returns full context for an entity (used by Context Panel).

Response:
```json
{
  "entity_id": "METRIC_GMV",
  "entity_name": "GMV",
  "category": "METRIC",
  "description": "成交总额",
  "timeline": [
    {
      "event_id": "evt_001",
      "occurred_at": "2026-03-22",
      "time_granularity": "WEEK",
      "summary": "GMV 环比下降 12%",
      "event_type": "FLUCTUATION",
      "attribution": "广告渠道B预算骤减40%导致新客获取不足",
      "decision": {
        "action": "临时调配渠道A预算补齐，恢复渠道B投放",
        "owner": "增长运营组",
        "outcome": "SUCCESS",
        "outcome_detail": "W13 GMV 恢复至正常水平"
      }
    }
  ],
  "evidence": [
    {
      "doc_title": "2026年第12周增长团队复盘周报",
      "doc_url": "/samples/week12.md",
      "importance_score": 5.0,
      "reason_code": "FINAL_RESOLUTION"
    }
  ],
  "insight": {
    "pattern": "GMV 在近6个月内出现3次类似下降，均与渠道预算调整相关",
    "risk": "渠道B预算审批流程变更可能导致Q3再次出现类似波动",
    "suggestion": "关注渠道B预算审批节点，提前2周预警"
  }
}
```

### GET /entities
List all known entities.

Response:
```json
{
  "entities": [
    { "entity_id": "METRIC_GMV", "entity_name": "GMV", "category": "METRIC", "aliases": ["成交总额", "流水"] },
    { "entity_id": "METRIC_CTR", "entity_name": "CTR", "category": "METRIC", "aliases": ["点击率"] }
  ]
}
```

### POST /documents/ingest
Ingest a document for extraction.

Request:
```json
{
  "title": "2026年第12周增长团队复盘周报",
  "content": "...(markdown text)...",
  "source_url": "optional"
}
```

Response:
```json
{
  "doc_id": "doc_2026_w12",
  "entities_found": 5,
  "events_extracted": 3,
  "decisions_extracted": 2
}
```

### GET /documents
List ingested documents.

### GET /health
Health check.

## Data Models (SQLite for MVP)

### entities
- entity_id TEXT PK
- entity_name TEXT
- category TEXT (METRIC|OBJECT|EVENT|DECISION|EXPERIMENT|OWNER)
- description TEXT

### entity_aliases
- alias_id INTEGER PK
- entity_id TEXT FK
- alias_name TEXT

### timeline_events
- event_id TEXT PK
- entity_id TEXT FK
- occurred_at TEXT
- time_granularity TEXT (DAY|WEEK|MONTH|QUARTER)
- summary TEXT
- event_type TEXT (FLUCTUATION|DECISION|EXPERIMENT|LAUNCH)
- attribution TEXT
- document_id TEXT

### decisions
- decision_id TEXT PK
- event_id TEXT FK
- action_taken TEXT
- owner TEXT
- outcome TEXT (SUCCESS|FAILED|INCONCLUSIVE|PENDING)
- outcome_detail TEXT

### evidence_links
- evidence_id INTEGER PK
- entity_id TEXT FK
- document_id TEXT
- doc_title TEXT
- doc_url TEXT
- importance_score REAL (0-5)
- reason_code TEXT (FIRST_MENTION|FINAL_RESOLUTION|FAILED_CASE|HIGH_SIMILARITY|REGULAR)

### documents
- doc_id TEXT PK
- title TEXT
- content TEXT
- source_url TEXT
- ingested_at TEXT

## LLM Extraction Schema (sent to GLM)

System prompt instructs LLM to return:
```json
{
  "document_metadata": { "doc_id": "", "title": "", "date": "" },
  "entities_mentioned": [
    { "raw_text": "", "normalized_candidate": "", "category": "" }
  ],
  "timeline_extraction": [
    {
      "time_anchor": "",
      "primary_entity": "",
      "event_summary": "",
      "event_type": "",
      "attribution": "",
      "decision": { "action": "", "owner": "", "status": "", "result_description": "" },
      "importance_flag": ""
    }
  ]
}
```

## Evidence Ranking Weights
- FIRST_MENTION: 5.0
- FINAL_RESOLUTION: 5.0
- FAILED_CASE: 4.0
- HIGH_SIMILARITY: 3.0
- REGULAR: 2.0
