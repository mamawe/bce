# BCE 开发日志

## 2026-07-24 — 全量开发 + 审查 + 架构升级

### 一、初始构建（Stage 1/2/3 并行交付）

**后端（FastAPI + SQLite + httpx）**
- 完整 API：/health, /entities, /context, /documents/ingest, /documents
- LLM 抽取管线：document_parser → llm_extractor → entity_normalizer → timeline_builder → evidence_ranker
- 实体别名归一化（预置 GMV/CTR/DAU/CAC/CVR 中文别名）
- Evidence Ranking 权重：FIRST_MENTION=5.0, FINAL_RESOLUTION=5.0, FAILED_CASE=4.0, HIGH_SIMILARITY=3.0, REGULAR=2.0
- 无 LLM key 时 seed_data.py 灌入结构化演示数据

**前端（React 18 + Vite + TypeScript）**
- 文档查看器 + 实体高亮（浅黄下划线，可点击）
- Context Panel 四 Tab：历史/决策/证据/洞察
- SummaryCard 归因链摘要卡（约束路径首屏必现）
- Mock 数据降级（后端离线时 Demo Mode）

**Chrome Extension（MV3 + Shadow DOM）**
- IntersectionObserver 惰性匹配（不扫全 DOM）
- 300ms hover → 迷你卡片 → 点击 → 完整 Panel
- Shadow DOM 样式隔离，不污染宿主页面
- 4h 字典缓存 + Demo Mode 降级

### 二、信息密度调优

- Panel 结构改为"约束路径首屏 + Tab 发散探索"
- 新增 SummaryCard：最近事件 → 归因 → 决策 → 结果 → 来源，0 次点击即得
- 整体 padding 收紧（header 18→14px，body 18→14px），密度提升 ~20%
- 前端 + Extension 同步更新

### 三、代码审查与修复（重构后）

**后端修复 8 项：**
- precompute.py / timeline_builder.py N+1 查询 → 批量 get_decisions_for_events()
- evidence_ranker.py LIKE 通配符 bug（`_` 是 SQL 单字符通配）→ 转义
- entity_normalizer.py 每次调用查全量 → 模块级缓存 + invalidate_cache()
- answer_validator.py 死代码清理
- insight.py 未使用变量 + 函数内 import 修正
- llm_insight.py 未使用导入删除
- offline_import.py 确认完整可运行

**前端修复 5 项：**
- App.tsx loadContext 无 .catch() → 永久 loading 修复
- CSS 未定义变量（--bg-card 等 4 个）补入 :root
- HistoryTab 初始展开用未排序数组 → 先排序再取最新
- InsightTab mock 数据不兼容 → 加 fallback 渲染旧格式
- HistoryTab 图表化（recharts ComposedChart）

**Extension 修复 6 项：**
- panel.js renderHistory 不按时间排序 → 加 sort
- content.js 500 字符限制 → 提升到 5000
- Fallback 字典扩充（+7 实体：订单量/客单价/复购率/毛利率/净利率/品类宽度/履约成本）
- Mock evidence REGULAR 分数 3.0→2.0（对齐契约）
- background.js 死代码删除
- mock-data.js 未使用导出删除

### 四、图表改造

- HistoryTab 从垂直时间线改为 recharts 趋势图
- Y 轴：实际指标值（如 GMV 1520→1552→1575），非环比%
- 从 summary 解析 `本期值 / 上期值 / 环比`（支持 "+3.1%" 和 "下降 12%" 两种格式）
- 事件列表保留，点击展开三层：📊 数据详情 → 📝 归因 → 🎯 决策
- 环比彩色标签（↑绿 / ↓红）

### 五、证据链接可点击

- EvidenceTab 文档标题可点击 → 弹出浮窗（标题/星级/来源/操作按钮）
- "在文档查看器中打开"按钮 → 切换左侧文档面板到对应报告
- 新增 onOpenDocument 回调链：EvidenceTab → ContextPanel → App

### 六、智能问答 LLM 兜底

- ask_handler.py 新增 _handle_llm_general()
- 任何匹配不到规则策略的问题 → 全走 LLM（带实体时间线 + 预计算指标作 context）
- LLM 不可用时降级到规则引擎
- 分类默认从 "llm_analytical" 改为 "llm_general"

### 七、API 配置

- .env 写入真实智谱 API key
- 文本链：glm-4.7-flash → glm-4-flash-250414 → glm-4-flash
- 多模态链：glm-4.6v-flash → glm-4.1v-thinking-flash → glm-4v-flash
- 生图：cogview-3-flash / 视频：cogvideox-flash
- 连通性验证通过

### 八、Pipeline 重排 + 证据重排 + 跨文档关联（架构升级）

**Pipeline 编排器（app/pipeline.py 新建）：**
- 9 步管线：parse → 规则提取 → 分段 LLM → 交叉校验 → 归一化 → 时序检查 → 证据重排 → 跨实体关联 → 入库
- 结构化文档走"规则先行"路径，叙事文档走"LLM 全量"路径
- 分段抽取（按 ## 标题切段），防跨段混淆
- 交叉校验：数字冲突标记 CONFLICT 进 review_queue，不自动裁决

**证据重排（app/evidence/reconciliation.py 新建）：**
- Layer 1：置信度衰减（effective_score = base × max(0.3, 1 - 0.05 × weeks)）
- Layer 2：LLM 冲突检测（一致/补充/部分矛盾/完全推翻）
- Layer 3：共识保护（≥3 份支持 → 单份推翻不生效，标 NEEDS_REVIEW）
- DB 新字段：superseded_by, label_version, effective_score, published_at

**跨文档关联（app/normalizer/entity_relationships.py 新建）：**
- Tier 1（0.9）：显式因果句式，自动入库
- Tier 2（0.6）：LLM 推断，标 source=llm_inferred
- Tier 3（0.3）：时序共现 → 候选队列，≥2 次共现才升级
- Pruning：confidence < 0.3 且 4 周无新证据 → 自动清除
- DB 新表：entity_relationships, relationship_candidates

**限流退避（llm_client.py 改造）：**
- 请求间隔 2s（asyncio.Lock）
- 429 指数退避：5s → 10s → 20s，每模型最多 3 次重试
- 模型降级链不变

**流式 Q&A（routes.py 新增 POST /ask/stream）：**
- SSE 端点，逐 chunk 返回
- llm_client.py 新增 generate_stream() 异步生成器
- 前端 ChatPanel 流式渲染（ReadableStream 消费 SSE）

**关联 API（routes.py 新增）：**
- GET /entities/{entity_id}/relationships
- 前端 RelationshipBar 组件：水平 chips，可点击跳转关联实体

### 九、设计原则沉淀

- 不自动"定罪"：冲突只标记，人做最终裁判
- 置信度分级：0.3 / 0.6 / 0.9，前端默认展示 ≥ 0.5
- 用户可纠正：每个自动化决策有人工覆盖入口
- 衰减 + pruning：过时数据自动降权，候选关联定期清理

---

## 2026-07-24 — 数据层修复 + 权限加固 + 埋点基础设施

### 十、数据层修复（metric_value 存储）

- **为什么这样修改**：规划文档 v4 P0 要求 FACTUAL 问答返回精确数值而非 summary 片段。
- **从什么样子改成什么样子**：
  - Before：timeline_events 只有 summary 文本，"GMV：日均 GMV（万元）1,520 / 1,474 / +3.1%" 作为字符串存储。
  - After：新增 metric_value(1520.0) / metric_unit("万元") / metric_delta(46.0) / metric_delta_pct(3.1) 四个字段。
- **当初如何确定与思考的**：用户在审查规划文档时确认"数据层修复是飞书文档接入能正常工作的前提"。

### 十一、权限标记粒度修正（entity→event 级）

- **为什么这样修改**：审查规划文档时发现同一实体（GMV）的不同事件敏感度不同（总体 GMV=L1，成本结构=L4），entity 级标记无法区分。
- **从什么样子改成什么样子**：
  - Before：规划文档第 8 章设计为 entities 表加 sensitivity_level。
  - After：timeline_events 表加 sensitivity_level（每条事件独立标记），entities 表保留 default_sensitivity 作为新事件的默认值。
- **当初如何确定与思考的**：我在审查意见中指出"实体级标记太粗"，用户认可后按 event 级实施。

### 十二、文档版本策略

- **为什么这样修改**：规划文档 4.2 说"更新文档重新提取"，但未定义旧数据如何处理。与证据重排机制冲突（superseded_by 指向谁？）。
- **从什么样子改成什么样子**：
  - Before：重新 ingest 同一文档会 INSERT OR REPLACE 覆盖事件，无版本概念。
  - After：documents 表加 doc_version + superseded_by；重新 ingest 时旧事件标记 deprecated=1，新事件带新 version。
- **当初如何确定与思考的**：我提出"版本替换"方案（旧事件作废但保留，新版本入库），用户确认执行。

### 十三、推送链接 JWT 安全加固

- **为什么这样修改**：规划文档 4.3.3 的 JWT 无过期时间，且权限是发送时快照（权限收回后旧链接仍可访问）。
- **从什么样子改成什么样子**：
  - Before：规划中 JWT 只有 user_id + 权限范围，无 exp。
  - After：JWT 加 7 天过期 + 点击时实时校验 DB 中用户当前权限。
- **当初如何确定与思考的**：我在审查意见中标记为"必须改"，用户认可。

### 十四、埋点基础设施

- **为什么这样修改**：规划文档成功标准要求"推送点击率≥40%"，但无任何追踪机制。
- **从什么样子改成什么样子**：
  - Before：无 push_events 表，无法衡量推送效果。
  - After：push_events 表记录 sent/clicked/viewed 事件 + 统计 API。
- **当初如何确定与思考的**：我在审查意见中指出"成功标准缺埋点基础设施"，用户认可后加入。

---

## 2026-07-28 — 全量优化（5 批次）

### 十五、安全加固（第一批）

- **为什么这样修改**：全量代码审查发现 API key 裸露在源码树（无 .gitignore）、JWT secret 硬编码默认值可被伪造、CORS 全开 + credentials 构成 CSRF 风险、X-User-Role header 任何人可伪装 admin。
- **从什么样子改成什么样子**：
  - 无 .gitignore → 根目录 + backend/ 各一份，排除 .env / *.db / node_modules / dist
  - JWT secret 硬编码 "bce-push-link-secret..." → 读 BCE_JWT_SECRET 环境变量，未设时随机生成 + 日志警告
  - CORS `allow_origins=["*"]` → 限定 localhost:5173 / localhost:3000 / 127.0.0.1:5173
  - X-User-Role 无条件信任 → 仅 BCE_ENV=development 时生效，生产环境忽略
  - 文档 ingest 无大小限制 → 500KB 上限，超出返回 413
  - .env.example 变量名 ZHIPU_API_KEY → 修正为 LLM_API_KEY + 补全所有变量
- **当初如何确定与思考的**：全量探索审计标记为 CRITICAL（5 项），用户指示"全部优化"，按投入产出比排序第一批执行。

### 十六、SSE 流式格式对齐（第二批）

- **为什么这样修改**：后端 SSE 发送 `{"content": "x", "done": false}`，前端期望 `{"type": "chunk", "content": "x"}`，格式不匹配导致流式问答实际跑不通。
- **从什么样子改成什么样子**：
  - 后端统一为 `{"type": "chunk", "content": "..."}` + `{"type": "meta", ...}` + `data: [DONE]`
  - 前端无需改动（已按正确格式解析）
- **当初如何确定与思考的**：审计标记为 HIGH（功能性 bug），流式问答是用户可见功能，必须修。

### 十七、性能优化（第三批）

- **为什么这样修改**：/entities 端点 N+1（100 实体 = 101 次 DB 连接）；ask_handler 每次问答全量扫实体+别名；pipeline 分段 LLM 串行（10 段 × 3s = 30s）；llm_extractor 绕过共享 client 无限流保护。
- **从什么样子改成什么样子**：
  - /entities：新增 `get_all_aliases()` 单次查询，替代循环内逐实体查别名
  - ask_handler：模块级 `_get_entity_dict()` 缓存（5 分钟 TTL），替代每次请求 N+1 查询
  - pipeline：`asyncio.gather` + `Semaphore(3)` 并行分段抽取，30s → ~10s
  - llm_extractor：改用共享 `llm_client.generate_json()`，获得限流 + 退避 + 连接复用
  - llm_client：模块级 `httpx.AsyncClient` 复用（keep-alive），替代每次新建
- **当初如何确定与思考的**：审计标记 4 项 HIGH 性能问题，用户指示全部优化。

### 十八、工程质量（第四批）

- **为什么这样修改**：全后端用 print() 无法生产调试；INSERT OR REPLACE 会丢失迁移新增字段；pipeline 多处 `except: pass` 静默吞错；存在死代码。
- **从什么样子改成什么样子**：
  - print() → `logging` 模块（basicConfig + 按级别 info/warning/error）
  - INSERT OR REPLACE → `ON CONFLICT DO UPDATE`（保留迁移字段）
  - `except Exception: pass` → `except Exception as e: logger.warning(...)`
  - 删除死代码：evidence_ranker.compute_text_similarity、前端 ingestDocument 同步函数、routes.py 8 个未使用 import
  - entity_aliases 加 UNIQUE 约束防并发重复
- **当初如何确定与思考的**：审计标记 MEDIUM-HIGH，属于"不修不会崩但会越来越难维护"的债务。

### 十九、测试基建（第五批）

- **为什么这样修改**：全项目零测试覆盖，任何改动都可能静默引入回归。
- **从什么样子改成什么样子**：
  - 无测试 → pytest + pytest-asyncio，28 条测试全通过
  - 覆盖 5 条关键路径：entity_normalizer（别名匹配）、permissions（权限过滤）、jwt_links（令牌生成/过期/篡改）、database（CRUD + upsert 字段保留 + 级联删除）、ask_handler（问题分类路由）
  - conftest.py 自动为每个测试创建临时 DB，互不干扰
- **当初如何确定与思考的**：审计标记 CRITICAL（零覆盖），用户指示全部优化。优先覆盖安全相关（权限/JWT）和数据完整性（DB 操作）。

---

## 2026-07-29 — 飞书集成（v4 P0）

### 二十、飞书 lark 模块创建

- **为什么这样修改**：v4 规划 P0 要求飞书应用注册+身份授权、文档同步、IM 推送三项能力。需要独立模块封装飞书 API 调用。
- **从什么样子改成什么样子**：
  - 无飞书集成 → 新建 `app/lark/` 模块（config / auth / doc_sync / im_push / routes）
  - auth.py：tenant_access_token 自动刷新（7200s 过期，6000s 提前刷新）
  - doc_sync.py：list_wiki_spaces / list_wiki_nodes / get_document_content / sync_space
  - im_push.py：send_text_message / send_push_notification（富文本 post 格式）
  - routes.py：/api/v1/lark/spaces、/spaces/{id}/docs、/sync、/push-test、/push
- **当初如何确定与思考的**：按 v4 规划文档第 4 章技术方案实施。飞书 API 通过 tenant_access_token（应用身份）调用，无需用户 OAuth。

### 二十一、IM 推送接入 pipeline

- **为什么这样修改**：v4 要求"新文档导入后自动向相关成员推送飞书消息"。推送应在 ingest 完成后自动触发，不需要用户手动操作。
- **从什么样子改成什么样子**：
  - pipeline 无推送 → 新增 Step 9（可选）：`push_to` 参数传入 open_id 时自动发送富文本推送
  - IngestRequest 新增 `push_to` 字段，透传到 `run_ingest_pipeline`
  - 推送内容：文档标题 + 识别实体 + 事件/决策计数 + BCE 链接
  - 推送失败为 non-fatal（logger.warning），不阻塞 ingest
- **当初如何确定与思考的**：推送是"锦上添花"不应阻塞核心流程，所以用 try/except 包裹。链接格式 `http://localhost:5173/?doc={doc_id}` 后续部署时改为真实域名。

### 二十二、前端导入弹窗增加飞书知识库 Tab

- **为什么这样修改**：v4 要求"导入弹窗新增飞书知识库 Tab，显示已授权的知识库列表+文档列表"。
- **从什么样子改成什么样子**：
  - 导入弹窗只有本地文件上传 → 新增 Tab 切换（📁 本地文件 / 🔗 飞书知识库）
  - 飞书 Tab：加载知识库列表 → 选择空间 → 点击"同步"→ 调用 /api/v1/lark/sync → 显示结果
  - 新增 CSS：.import-tabs / .import-tab / .feishu-sync-panel / .feishu-space-list 等
- **当初如何确定与思考的**：Tab 切换而非独立页面，保持导入流程的统一入口。同步操作直接复用 pipeline ingest，不引入新的数据路径。

### 飞书集成验证状态

| 能力 | 状态 | 说明 |
|---|---|---|
| Bot 消息发送 | ✅ 已验证 | push-test 端点成功发送消息到辛迪 |
| tenant_access_token | ✅ 已验证 | 自动获取+缓存+刷新 |
| 知识库文档同步 | 🚫 需开权限 | 需在飞书后台开通 wiki:wiki:readonly |
| Pipeline 推送 | ✅ 代码就绪 | 等 LLM 限流恢复后端到端验证 |
| 前端飞书 Tab | ✅ build 通过 | 运行时需后端 wiki 权限才能显示空间列表 |

### 二十三、V4 数据层修复（metric_value 精确数值）

- **为什么这样修改**：v4 规划 P0 要求"FACTUAL 问'肉类毛利率多少'→ 返回精确数值"。修复前 FACTUAL 只返回 summary 文本片段，无法给出精确数字。
- **从什么样子改成什么样子**：
  - ask_handler `_handle_sql_factual`：优先读 `metric_value` + `metric_unit` + `metric_delta_pct`，格式化为"GMV 最新值：1,805.0 万元，环比上升 2.8%"；metric_value 为 NULL 时降级回 summary 文本
  - precompute `get_rolling_stats`：新增 latest_value / min_value / max_value / avg_value / trend 字段（从 metric_value 计算）
  - 存量数据回填：218/241 条事件通过 `parse_metric_values()` 补填了 metric_value
  - /context 端点已通过 timeline_builder 透传 metric 字段（无需额外改动）
- **当初如何确定与思考的**：v4 规划文档 4.4 节明确要求"FACTUAL 直接返回 metric_value + metric_unit，不再返回 summary 片段"。回填用规则引擎（parse_metric_values）而非 LLM，保证数字精确性。

**待办**：在飞书开发者后台（https://open.feishu.cn/app/cli_a94bbfef7b7c9bb7/auth）开通 `wiki:wiki:readonly` 权限后，文档同步即可跑通。

---

## 已知遗留

| 项目 | 说明 | 优先级 |
|---|---|---|
| llm_extractor 绕过 llm_client | DRY 违规，功能正常 | P2 |
| main.py 与 routes.py 管线重复 | 已部分解决（pipeline.py），旧代码待清理 | P2 |
| Bundle 562KB | recharts 占大头，可 code-split | P3 |
| 自动 ingest | 当前手动触发，P2 可加飞书 Webhook / 文件监听 | P2 |
| 权限隔离 | A 业务只看 A 数据 | P2 |
| 幻觉对抗完整方案 | answer_validator 数字校验已有，实体校验待补 | P2 |
### 二十四、metric_facts 宽表 + Ask NL→SQL 路由

- **为什么这样修改**：原 Ask 端点从 timeline_events 的 summary 文本中解析数字，链路长、易出错、无法做跨维度聚合。用户提出"宽表由数据仓库生成，作为 Ask 的查询基础设施"，BCE 只消费不生产。
- **从什么样子改成什么样子**：
  - 新建 `metric_facts` 宽表：report_date / week_label / category / merchant_type / metric_name / metric_value / metric_unit / wow_change_pct / sensitivity_level
  - 生成 10 周示例数据（W21-W30）：11 品类 × 11 指标 + 5 商户类型，共 1310 行
  - Ask 路由重构：数值型问题（FACTUAL/AGGREGATION/COMPARISON）统一路由到 `_handle_metric_sql`，由 LLM 生成 SQL 查宽表
  - 叙事型问题（ANALYTICAL："为什么/什么决策"）仍走时间线路径
  - SQL 安全防护：只允许 SELECT，禁止 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/ATTACH
  - SQL prompt 含完整表结构 + 11 条规则 + 3 个示例，确保生成质量
- **当初如何确定与思考的**：用户明确"宽表由数仓生产，BCE 消费查询"。路由策略为"SQL 优先，时间线补叙事"——数字永远走 SQL（精确快），叙事永远走时间线（有因果链），两者不竞争各管各的层。

---

## 已知遗留

| 项目 | 说明 | 优先级 |
|---|---|---|
| llm_extractor 绕过 llm_client | DRY 违规，功能正常 | P2 |
| main.py 与 routes.py 管线重复 | 已部分解决（pipeline.py），旧代码待清理 | P2 |
| Bundle 562KB | recharts 占大头，可 code-split | P3 |
| 自动 ingest | 当前手动触发，P2 可加飞书 Webhook / 文件监听 | P2 |
| 权限隔离 | A 业务只看 A 数据 | P2 |
| 幻觉对抗完整方案 | answer_validator 数字校验已有，实体校验待补 | P2 |
| 飞书 wiki 同步 | ✅ 已解决（改用 lark-cli user 身份，绕过 bot 成员限制） | done |
| 宽表接真实数仓 | 当前为示例数据，后续对接真实数仓接口写入 | P1 |
