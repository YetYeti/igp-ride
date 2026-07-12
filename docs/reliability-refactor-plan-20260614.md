# igp-ride 可靠性重构计划

日期：2026-06-14

输入：`docs/refactor-plan-20260614.md`

范围：认证状态、长期无人值守同步、失败恢复、日志追踪、数据库状态、CLI 体验、测试保障。

## 一、项目现状总结

`igp-ride` 当前已经是一个可用的本地同步 CLI。它能登录 IGPSPORT，保存本地凭据和 session，拉取活动列表，下载 FIT 文件，解析 FIT 指标并 upsert 到 SQLite。它还能把本地 FIT 文件上传到 Intervals.icu，并通过 `external_id=igp-{ride_id}` 检查远端是否已存在，避免常规重复上传。CLI 已有 `login`、`logout`、`status`、`reset`、`update`、`list`、`show`、`note`、`icu login/status/logout/sync`，并支持 `--format json` 和 `--no-input`。

可靠性方面已经实现的能力：

- IGPSPORT session 保存 `Authorization`、`access_token`、`refresh_token`、`expires_at` 和 cookies，文件权限设为 `0600`。见 `src/igp_ride/client.py:260`。
- token 过期前会主动重新登录；401/403 和 `AuthenticationError` 会触发有限重登重试。见 `src/igp_ride/client.py:42`、`src/igp_ride/client.py:206`、`src/igp_ride/client.py:288`。
- IGPSPORT 和 Intervals.icu HTTP client 都配置了 429/5xx 的 requests retry。见 `src/igp_ride/client.py:193`、`src/igp_ride/icu_client.py:139`。
- Intervals.icu 同步已有本地状态字段：`icu_activity_id`、`icu_external_id`、`icu_synced_at`、`icu_sync_status`、`icu_sync_error`。见 `src/igp_ride/database.py:501`。
- 本地日志已有文件输出和轮转，console 只输出 warning 及以上。见 `src/igp_ride/utils.py:45`。
- 测试覆盖了 CLI 输出、配置、DB upsert、增量同步、认证 client、ICU client、ICU sync 和 note sync。

主要短板不在“能不能跑”，而在“失败后能否解释、恢复并证明状态正确”。当前同步流程没有显式 sync run 记录，没有统一错误分类，没有每个 activity 的尝试次数和最后一次阶段记录；FIT 下载和 DB 写入之间缺少可追踪的事务边界；ICU 上传成功但本地 `mark_icu_synced` 失败时，只能靠下次 `external_id` 远端查询修复，缺少 run-level 审计；下载并发复用同一个 `requests.Session`，长期运行时存在隐性线程安全风险。

## 二、风险清单

### P0：可能导致重复上传、漏同步或无法继续同步

1. ICU 上传成功后本地状态更新失败，缺少可审计恢复记录

- 风险描述：`sync_icu()` 调用 `upload_activity_file()` 成功后才调用 `mark_icu_synced()`。如果进程在两者之间崩溃或 SQLite commit 失败，本地仍可能保持 `pending/failed`。
- 触发场景：上传已成功，磁盘满、数据库锁、进程被 kill，或 DB 写入异常。
- 当前依据：上传在 `src/igp_ride/service.py:590`，本地标记在 `src/igp_ride/service.py:614`；`mark_icu_synced()` 单独 commit，见 `src/igp_ride/database.py:135`。
- 建议方向：增加 `sync_runs` 和 `activity_sync_attempts` 表，上传前写入 `uploading` attempt，上传后先保存远端返回，再标记 activity。下次运行先用 `external_id` reconcile，再决定是否上传。

2. FIT 下载状态缺少 checksum/file_size，无法区分“文件存在但内容变了”

- 风险描述：`sync()` 只检查 FIT path 是否存在；已存在则跳过下载和 upsert。虽然 `repair()` 会检查 FIT header，但没有 checksum、size、downloaded_at 或 source revision。
- 触发场景：FIT 文件被截断但 header 还像 FIT；用户手动替换文件；IGPSPORT 后续修正活动数据。
- 当前依据：下载队列只看 `not fit_path.exists()`，见 `src/igp_ride/service.py:257`；skip 分支见 `src/igp_ride/service.py:299`；header 校验见 `src/igp_ride/service.py:800`。
- 建议方向：增加 `fit_file_size`、`fit_sha256`、`fit_downloaded_at`、`fit_verified_at`、`fit_error`。`update` 对 downloaded 记录至少做轻量校验，`repair` 负责重下和重算 checksum。

3. 并发 FIT 下载复用同一个 session

- 风险描述：`ThreadPoolExecutor` 的 worker 共享 `client_copy = self.client`，即共享一个 `requests.Session`。requests Session 通常不保证线程安全。
- 触发场景：多 FIT 同时下载时，cookies/header/connection pool 状态竞争，导致偶发失败或认证状态错乱。
- 当前依据：`client_copy = self.client` 和 executor submit 见 `src/igp_ride/service.py:272`。
- 建议方向：短期把 FIT 下载改回顺序或给每个 worker 创建独立 client/session；中期抽象 `FitDownloader`，限制并发并记录每条失败原因。

### P1：影响长期稳定运行

1. 没有 sync run 级别审计

- 风险描述：日志有文本，但数据库无法回答“某次同步从哪里开始、处理了哪些 activity、为什么失败、失败是否已恢复”。
- 触发场景：cron 长期运行、用户几天后发现某条活动没上传、需要定位失败窗口。
- 当前依据：只有 `sync_meta.last_sync_time`，见 `src/igp_ride/database.py:520`；`SyncSummary` 只有聚合计数，见 `src/igp_ride/models.py:31`。
- 建议方向：新增 `sync_runs`，记录 run id、kind、started_at、finished_at、status、summary_json、error_class、error_message、app_version。

2. 错误类型还太粗

- 风险描述：目前核心异常是 `AuthenticationError`、`DataSyncError`、`ICUClientError`、`DatabaseError`、`ConfigurationError`。它们不足以表达 retryable、permanent、rate_limited、bad_payload、file_corrupt、remote_conflict。
- 触发场景：自动化想知道该重试、告警还是要求用户重新登录。
- 当前依据：CLI 主要按异常类型映射 exit code，见 `src/igp_ride/cli.py:186`；IGPSPORT business error 默认多归到认证或数据同步，见 `src/igp_ride/client.py:323`。
- 建议方向：引入 `errors.py`，定义 `SyncError` 基类和 `category/retryable/status_code/ride_id` 属性，CLI 和 DB attempt 记录都用统一分类。

3. `last_sync_time` 是运行结束时间，不是远端游标

- 风险描述：增量同步用“是否遇到本地已有 activity”作为边界，`last_sync_time` 只决定 page size，并不直接参与远端查询。这个设计可用，但 `last_sync_time` 命名容易误导，也不能解释最后处理到哪条远端 activity。
- 触发场景：大量历史活动导入、远端排序变化、IGPSPORT 重新发布旧活动。
- 当前依据：`last_sync_time` 只用于 `_calculate_fetch_limits()`，见 `src/igp_ride/service.py:201`；增量停止条件是 page ids 全部在本地，见 `src/igp_ride/service.py:445`。
- 建议方向：把 meta 改为 `last_successful_run_at`，另加 `last_seen_start_time`、`last_seen_ride_id` 作为诊断字段；不要用时间过滤远端，除非 API 明确支持。

4. FIT 下载失败只保存 `missing/invalid`，不保存失败原因和次数

- 风险描述：用户只能看到数量，无法知道某个 ride 为什么失败、失败多久、是否一直重试同一种错误。
- 触发场景：IGPSPORT 返回下载 URL 缺失、签名 URL 过期、网络异常、文件非 FIT。
- 当前依据：失败时只 `summary.fit_files_failed += 1` 并设置 `fit_status="missing"`，见 `src/igp_ride/service.py:305`。
- 建议方向：增加 `fit_download_status` 细分、`fit_retry_count`、`fit_last_error`、`fit_last_attempt_at`。

### P2：影响体验、可维护性或排查效率

1. CLI 缺少本地同步健康视图

- 风险描述：`status` 主要检查认证，`list/show` 查看活动，但没有“一页看清 pending/failed/missing/invalid/last run/log path”。
- 当前依据：`cmd_status()` 只检查 credentials/session/authenticated，见 `src/igp_ride/cli.py:436`；`icu status` 只检查 API key 和 athlete，见 `src/igp_ride/cli.py:535`。
- 建议方向：新增 `doctor` 或增强 `status --verbose`，输出 DB path、FIT dir、log path、activities count、missing FIT、ICU failed、last run。

2. 数据库迁移机制是隐式 `ALTER TABLE`

- 风险描述：`_ensure_activity_columns()` 能补字段，但没有 schema version、迁移历史、回滚策略和检查约束。
- 当前依据：`CREATE TABLE IF NOT EXISTS` 后手写补列，见 `src/igp_ride/database.py:468`、`src/igp_ride/database.py:511`。
- 建议方向：增加 `schema_migrations` 或 `PRAGMA user_version`，每个版本一个幂等迁移函数；状态字段加 CHECK 约束时需采用 SQLite rebuild table 迁移。

3. `RideSyncService` 同时承担 orchestration、auth、download、ICU note reconciliation

- 风险描述：后续加入 run 记录、错误分类、retry policy 后，`service.py` 会继续膨胀。
- 当前依据：`RideSyncService` 已包含 login/logout/reset/update/repair/icu/note/build activity 等职责，见 `src/igp_ride/service.py:89`。
- 建议方向：按阶段提取 `SyncOrchestrator`、`IcuSyncService`、`FitService`、`ActivityRepository`，不要一次性大重写。

## 三、推荐目标架构

### 认证管理

保留现有 `IGPSportClient` 自动登录策略：本地保存 token/session，过期前刷新式重登，401/403 后重登重试。短期不必真正实现 refresh token，除非确认 IGPSPORT refresh endpoint 稳定；当前凭据可用于重新 login，已经能满足无人值守。

改进点：

- 将认证状态检查结果结构化为 `AuthStatus(provider, configured, session_present, authenticated, expires_at, error_category)`。
- IGPSPORT business code 要映射为认证失效、限流、服务端错误、数据错误，而不是默认全部归认证。
- `login` 切换账号保持现有“新账号成功后才覆盖旧状态”的策略。
- 文档明确：多设备登录导致 session 被挤掉时，401/403 或业务未登录 code 应归类为 `auth_expired`，自动重登后继续；如果密码也失效，则返回 exit code 3 并建议 `igp-ride login`。

### 本地数据库状态机

活动主状态不要合成一个大字段，保留按阶段字段更适合这个项目：

- `fit_download_status`: `missing | downloading | downloaded | invalid | failed`
- `icu_sync_status`: `pending | uploading | synced | failed | skipped`
- `icu_note_sync_status`: `pending | synced | failed | conflict`

每个阶段都保存：

- `*_attempt_count`
- `*_last_attempt_at`
- `*_last_error`
- `*_last_error_category`

新增 run/attempt 表后，activities 表只保留最新快照；详细历史放 attempt 表。

### 同步任务流程

目标流程是“先记录 intent，再做外部副作用，再 reconcile，再更新状态”：

1. 创建 `sync_runs` 记录，状态 `running`。
2. 检查配置和认证，记录 auth status。
3. 拉取 IGPSPORT 活动列表，逐页记录 fetch 摘要。
4. upsert activities，但不覆盖已成功的 ICU 状态。
5. 为缺失/invalid/failed FIT 建立 download attempt。
6. 下载 FIT 到临时文件，校验 header、size、sha256 后原子 rename。
7. 对 downloaded 且未 synced 的活动查询 ICU remote external ids。
8. 如果远端已存在，mark synced。
9. 如果远端不存在，写 attempt `uploading`，上传，保存远端 id，mark synced。
10. 同步或 reconcile note。
11. 完成 `sync_runs`，保存 summary。

### 错误分类

建议统一分类：

- `config`: 缺少账号、API key、路径不可写。
- `auth`: 401/403、业务未登录、密码错误、API key 失效。
- `network`: timeout、DNS、connection reset。
- `rate_limited`: HTTP 429。
- `remote_5xx`: 500/502/503/504。
- `remote_payload`: JSON 格式变化、缺少字段、下载 URL 异常。
- `file_invalid`: 非 FIT、FIT parse 失败、checksum 不符。
- `db`: SQLite locked、commit 失败、schema 不兼容。
- `conflict`: ICU note 远端已有不同内容。

每个错误标注 `retryable`。默认 `network/rate_limited/remote_5xx/db locked` 可重试，`config/auth/file_invalid/conflict` 不自动无限重试。

### 重试机制

保留 requests adapter 的短重试，用于单个 HTTP 请求内的瞬时错误。服务层再增加 per-activity retry policy：

- FIT 下载：最多 3 次，指数退避，记录每次 attempt。
- ICU 上传：最多 2 次；上传超时后必须先按 `external_id` 查远端再决定是否重试。
- note sync：最多 2 次；conflict 不重试。

### 日志与 sync run

日志继续保留到文件，但补充：

- 每次 run 生成 `run_id`，日志里所有关键行带 `run_id`。
- CLI 结束输出 log path 和 run id。
- `sync_runs.summary_json` 保存和 CLI JSON 一致的聚合摘要。
- `activity_sync_attempts` 保存每个 activity 每次阶段结果。

### CLI 命令设计

保留现有命令，优先增强而不是改名：

- `igp-ride status --verbose`: 显示认证、本地 DB、FIT、ICU 状态和最近 run。
- `igp-ride update --retry-failed`: 明确重试 failed/missing/invalid FIT。
- `igp-ride update --since YYYY-MM-DD`: 只处理本地 start_time 之后的候选，主要用于 repair/reconcile，不依赖远端时间过滤。
- `igp-ride icu sync --retry-failed`: 显式包含 failed；当前默认 include_failed=True，CLI 层可把语义说清楚。
- `igp-ride doctor`: 检查配置路径、权限、DB schema、log path、认证、最近失败。
- `igp-ride logs --tail 100`: 打印最近日志，便于 agent/cron 排查。

## 四、数据库改进建议

### activities 新增字段

```sql
ALTER TABLE activities ADD COLUMN fit_file_size INTEGER NOT NULL DEFAULT 0;
ALTER TABLE activities ADD COLUMN fit_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE activities ADD COLUMN fit_downloaded_at TEXT;
ALTER TABLE activities ADD COLUMN fit_verified_at TEXT;
ALTER TABLE activities ADD COLUMN fit_last_attempt_at TEXT;
ALTER TABLE activities ADD COLUMN fit_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE activities ADD COLUMN fit_last_error TEXT NOT NULL DEFAULT '';
ALTER TABLE activities ADD COLUMN fit_last_error_category TEXT NOT NULL DEFAULT '';
ALTER TABLE activities ADD COLUMN icu_last_attempt_at TEXT;
ALTER TABLE activities ADD COLUMN icu_attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE activities ADD COLUMN icu_last_error_category TEXT NOT NULL DEFAULT '';
```

后续 rebuild table 时加约束：

```sql
CHECK (fit_file_status IN ('missing', 'downloading', 'downloaded', 'invalid', 'failed'))
CHECK (icu_sync_status IN ('pending', 'uploading', 'synced', 'failed', 'skipped'))
```

### sync_runs

```sql
CREATE TABLE sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    app_version TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL DEFAULT '',
    summary_json TEXT NOT NULL DEFAULT '{}',
    error_category TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sync_runs_started_at ON sync_runs(started_at);
CREATE INDEX idx_sync_runs_kind_status ON sync_runs(kind, status);
```

`kind`: `update | repair | icu_sync | doctor`

`status`: `running | succeeded | failed | cancelled`

### activity_sync_attempts

```sql
CREATE TABLE activity_sync_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    ride_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    attempt_no INTEGER NOT NULL DEFAULT 1,
    retryable INTEGER NOT NULL DEFAULT 0,
    error_category TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    remote_activity_id TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    bytes_written INTEGER NOT NULL DEFAULT 0,
    checksum TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES sync_runs(id)
);

CREATE INDEX idx_attempts_ride_stage ON activity_sync_attempts(ride_id, stage);
CREATE INDEX idx_attempts_run_status ON activity_sync_attempts(run_id, status);
```

`stage`: `fetch | upsert | download_fit | verify_fit | icu_lookup | icu_upload | note_sync`

### 迁移策略

短期采用 `PRAGMA user_version`：

- v1：当前 schema。
- v2：新增 FIT/ICU attempt snapshot 字段。
- v3：新增 `sync_runs` 和 `activity_sync_attempts`。
- v4：如果需要 CHECK 约束，再 rebuild table。

迁移函数必须幂等，并在 `tests/test_database.py` 增加从旧 schema 文件或手工旧表迁移的测试。

## 五、同步流程改进建议

更鲁棒的 `update`：

1. `AppConfig.load(require_credentials=True)`，检查 DB/FIT/log 目录可写。
2. 创建 `sync_runs(kind='update')`。
3. 调用 `client.get_activity_page(page=1, page_size=1)` 验证认证；认证失败直接标记 run failed。
4. 根据是否 `--all` 选择全量或增量拉取；增量继续使用“遇到本地已知 activity 边界”策略。
5. 对每条远端 activity 执行 upsert。upsert 只更新活动元数据和 FIT 快照，不清空 ICU synced 状态。
6. 对 `fit_file_status in ('missing', 'invalid', 'failed')` 或本地文件不存在的记录建立下载队列。
7. 下载到 `{ride_id}.fit.tmp`，检查 `_looks_like_fit_file()`，计算 size/sha256，成功后原子 rename 到 `{ride_id}.fit`。
8. 解析 FIT；解析失败标记 `invalid`，但保留文件和错误原因。
9. 每个 activity 更新 attempt 和 snapshot 字段。
10. 完成 run，输出 summary、run id、log path。

更鲁棒的 `icu sync`：

1. 检查 API key，创建 `sync_runs(kind='icu_sync')`。
2. 查询 pending/failed downloaded FIT 活动。
3. 按 pending 最早日期调用 `list_activities(oldest=...)`，构建 `external_id -> remote`。
4. 每个 candidate 先 reconcile：远端已有则 mark synced，不上传。
5. 远端没有且本地文件存在，写 attempt `icu_upload/running`。
6. 上传超时或网络失败后，不立即盲目重试；先重新查 `external_id`。
7. 上传成功后写入 `icu_activity_id`、`icu_external_id`、`icu_synced_at`。
8. 同步 note；远端已有不同 note 时标记 conflict，不覆盖。
9. 完成 run，输出 uploaded/already_remote/failed/notes_conflicted。

## 六、CLI 改进建议

保持极简命令集：

- `igp-ride status`: 当前保持默认简洁输出，适合人工快速看认证。
- `igp-ride status --verbose`: 增加 DB path、FIT dir、log file、activity counts、missing/invalid FIT、ICU pending/failed、last successful run。
- `igp-ride doctor`: 运行只读诊断。检查配置文件权限、DB schema version、FIT 目录可写性、日志目录、IGPSPORT auth、ICU auth、最近失败。JSON 模式下输出结构化 diagnostics。
- `igp-ride update --retry-failed`: 明确重试 failed/missing/invalid FIT。当前 `update` 后会调用 `repair()`，但 CLI 语义不够显性。
- `igp-ride icu sync --dry-run`: 保持现状，继续保证不改变本地状态。
- `igp-ride icu sync --retry-failed`: 显式重试 failed upload。当前 service 默认 include_failed=True，建议 CLI 帮用户看见这个行为。
- `igp-ride logs --tail N`: 输出 log 文件最后 N 行；`--json` 时返回 path 和 lines。

不建议短期增加太多别名。`sync` 可以未来作为 `update && icu sync` 的高级命令，但当前更重要的是把两个阶段状态做可靠。

## 七、测试计划

P0 测试：

1. ICU 上传成功但 `mark_icu_synced()` 抛异常：下一次运行应通过 `external_id` 标记 already_remote，不重复上传。
2. ICU 上传 timeout 后远端实际存在：下一次运行先 lookup，再 mark synced。
3. FIT 下载写入 tmp 成功但 rename 前失败：不应留下 downloaded 状态。
4. FIT 文件存在但 checksum/size 不匹配：`repair` 应重下或标记 invalid。
5. 并发下载改造后，多个 FIT 下载不会共享同一个 session。

P1 测试：

1. `sync_runs` 成功、失败、空结果三种状态。
2. 每个 activity attempt 记录 stage、status、error_category。
3. IGPSPORT 401/403、业务未登录 code、密码错误分别映射到 auth 分类。
4. HTTP 429/5xx 映射为 retryable；配置缺失和 note conflict 不重试。
5. schema v1 到 v2/v3 迁移保留已有 activities、notes、icu 状态。

P2 测试：

1. `status --verbose` text/json 输出稳定。
2. `doctor` 在无凭据、无 ICU key、DB 不存在、FIT dir 不可写时给出明确诊断。
3. `logs --tail` 不泄露密码、API key、Authorization。
4. CLI JSON 模式 stdout 仍只输出 JSON，progress/logs 不污染 stdout。

现有测试位置：

- CLI：`tests/test_cli.py`
- DB：`tests/test_database.py`
- IGPSPORT client：`tests/test_client.py`
- ICU client：`tests/test_icu_client.py`
- service orchestration：`tests/test_service.py`

## 八、分阶段实施路线图

### 阶段 1：状态可观测性和错误分类

目标：先让失败可解释，不改大流程。

任务：

- 新增 `src/igp_ride/errors.py`，定义 `SyncError`、`ErrorCategory`、`classify_exception()`。
- `client.py`、`icu_client.py` 保持原异常对外兼容，但 service 记录时使用分类。
- `database.py` 增加 `sync_runs` 表和最小 repository 方法：`start_run()`、`finish_run()`。
- `cmd_update()`、`cmd_icu_sync()` 输出 run id 和 log path。

涉及文件：

- `src/igp_ride/errors.py`
- `src/igp_ride/database.py`
- `src/igp_ride/service.py`
- `src/igp_ride/cli.py`
- `tests/test_database.py`
- `tests/test_service.py`
- `tests/test_cli.py`

验收标准：

- 每次 `update` 和 `icu sync` 都产生一条 `sync_runs`。
- 成功和失败 run 都有明确 status。
- 现有测试全部通过，新增 run 测试覆盖异常路径。

### 阶段 2：FIT 下载状态机

目标：让本地 FIT 文件可靠、可校验、可恢复。

任务：

- activities 增加 FIT size/hash/attempt/error 字段。
- 下载改为 tmp 文件 + 校验 + 原子 rename。
- `_download_fit_safe()` 返回结构化结果，不再只返回 bool。
- 取消共享 session 并发，先改为顺序下载；如确实需要并发，再用 worker-local client。
- `repair()` 使用同一套 download/verify 逻辑。

涉及文件：

- `src/igp_ride/database.py`
- `src/igp_ride/service.py`
- `src/igp_ride/models.py`
- `tests/test_service.py`
- `tests/test_database.py`

验收标准：

- FIT 下载失败能在 DB 查到 ride_id、错误分类、错误消息、attempt_count。
- 非 FIT、短文件、parse 失败都被标记为 invalid/failed。
- tmp 文件不会被误认为 downloaded。

### 阶段 3：ICU 上传恢复和 attempt 记录

目标：消除上传成功但本地状态丢失时的重复风险。

任务：

- 新增 `activity_sync_attempts` 表。
- ICU 上传前后写 attempt。
- 上传异常后先按 `external_id` reconcile，再决定 retry/fail。
- `icu_sync_status='uploading'` 的旧记录在下次运行先 reconcile。
- note conflict 改为明确 `conflict` 状态。

涉及文件：

- `src/igp_ride/database.py`
- `src/igp_ride/service.py`
- `src/igp_ride/icu_client.py`
- `tests/test_service.py`
- `tests/test_database.py`

验收标准：

- 模拟上传成功后 DB 写失败，下次运行不重复上传。
- missing FIT、ICU 401、429、500、note conflict 均有正确状态。
- `icu sync --dry-run` 仍不改变 DB。

### 阶段 4：诊断 CLI 和迁移机制

目标：让长期无人值守运行容易排查。

任务：

- 引入 `PRAGMA user_version` 迁移。
- 新增 `status --verbose`。
- 新增 `doctor`。
- 新增 `logs --tail`。
- README 更新长期运行和 cron 示例。

涉及文件：

- `src/igp_ride/database.py`
- `src/igp_ride/cli.py`
- `src/igp_ride/utils.py`
- `README.md`
- `tests/test_cli.py`
- `tests/test_database.py`

验收标准：

- `igp-ride --format json doctor` 输出稳定 JSON。
- `doctor` 不做破坏性操作。
- 迁移测试能从旧 schema 保留数据升级。

### 阶段 5：模块边界整理

目标：降低 `service.py` 复杂度，为后续维护留空间。

任务：

- 提取 `FitService`：下载、校验、checksum、repair。
- 提取 `IcuSyncService`：remote lookup、upload、note sync。
- 提取 `RunRecorder` 或 repository 方法，封装 run/attempt 写入。
- 保持 CLI 行为不变，只移动代码和补测试。

涉及文件：

- `src/igp_ride/service.py`
- `src/igp_ride/fit_service.py`
- `src/igp_ride/icu_sync_service.py`
- `src/igp_ride/database.py`
- `tests/test_service.py`

验收标准：

- `RideSyncService` 只负责 high-level orchestration。
- 原 CLI 输出和 JSON contract 不回归。
- ruff、basedpyright、pytest 全部通过。

## 九、最终建议：优先做的 5 件事

1. 先加 `sync_runs`

原因：这是最小但收益最高的可观测性基础。没有 run id，后续所有失败恢复都难以证明。

2. 把 FIT 下载改为 tmp + 校验 + 原子 rename，并记录 size/hash/error

原因：本地 FIT 是上传 ICU 的源数据。先保证源文件状态可信，后续 ICU 同步才可靠。

3. 修复并发下载共享 session

原因：这是当前同步流程中最明显的隐性稳定性风险。短期顺序下载比不确定的并发更适合无人值守。

4. 为 ICU 上传增加 attempt 和 reconcile-first 恢复

原因：这是避免重复上传的关键。`external_id` 已经有了，缺的是把“上传前/上传后/本地写失败”的状态持久化。

5. 增加 `doctor` 或 `status --verbose`

原因：长期运行需要快速判断“认证、DB、FIT、ICU、日志、最近失败”在哪个环节出问题，尤其适合 cron 和 agent 调用。

## 不建议现在做的事

- 不建议直接大规模重写为多层架构。当前代码测试覆盖较好，应该用小阶段把状态和错误模型先补起来。
- 不建议马上依赖 IGPSPORT refresh token endpoint，除非先写探测和测试；现有用户名密码重登已经满足基本无人值守。
- 不建议把 `update` 和 `icu sync` 立即合并成一个默认命令。两个阶段的状态先做好，再考虑一键同步。
