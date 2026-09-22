# T7-G1 成长追踪施工前契约差异审计（T7-G1-P0）

| 项 | 值 |
| --- | --- |
| 状态 | **审计修订完成（有条件通过后修订）；不改生产代码；不自行批准契约** |
| 任务 | `[T7-G1-P0]` 施工前契约与当前代码差异审计 |
| 基线 | `main` @ `5c5c3ca`（`T4: 补TTS关闭时不复用残留MP3定向测试`） |
| 分支 | `feature/T7-growth-preflight` |
| 工作树 | `E:\ai_interview_hub_growth_preflight` |
| 规格依据 | 已合入 `docs/growth-tracking-spec.md`（`c5fdc42` / merge `4169c18`，草案 v2，**状态仍为待队长批准**） |
| 产出 | 仅本文件；未改 `growth-tracking-spec.md`、`AGENTS.md`、任何生产代码 |
| 修订记录 | 按审查「有条件通过」：清行尾空格；P8 改为 ASR 空格规范化验收后定义 `v1`；合入策略改为集成分支一次性进 main；P14 建议批准新增 `growth-data.ts` |

**宣称纪律**：本文只做差距与派工清单；§6 审批包须队长明示批准后，T7-G1 方可改契约/模型/破坏性请求体。

---

## 0. 一句话结论

相对规格：关系模型与报告页入口骨架已在；**身份绑定、口径字段、成长 API、成长页、双学生种子均未落地**；`POST /api/sessions` 仍硬编码 `user_id=1`；规格中“尚无 web/、尚无 voice 会话”等假设已过期。T7-G1 **不得开工实现契约变更**，须先过下方审批清单；且 **`SCORING_VERSION=v1` 不得以当前 `5c5c3ca` 冻结**，须先完成并验收 ASR 汉字间空格规范化后再定义。

---

## 1. 模型与迁移核对（users / sessions / reports）

### 1.1 当前 `server/models.py`（`5c5c3ca`）

| 表 | 已有字段 | 相对规格 |
| --- | --- | --- |
| `users` | `id, role, name_masked, major, grade` | **已满足**档案所需列；无学生列表 API、无种子学生 |
| `sessions` | `id, user_id, job_id, mode, started_at, status, pending_question_json, lease_token, lease_expires_at` | **缺** `input_mode`；`mode` 仍是受众模式字段本身可用，但创建时被硬编码 |
| `answers` | 声学可空字段齐全 | **已满足**；成长层不必改表 |
| `reports` | `id, session_id, dimensions_json, highlights_json, concerns_json, improvement_json, overall` | **缺** `scoring_version` |

### 1.2 当前 `server/db.py::ensure_schema_upgrades()`

- 仅对 `sessions` 做 `PRAGMA table_info` + 条件 `ALTER TABLE ADD COLUMN`（`pending_question_json` / `lease_token` / `lease_expires_at`）。
- **不**检查 `reports` 表；**不**存在 `input_mode` / `scoring_version` 迁移。
- 模式先例存在，规格 §9.3 扩展两列的路径仍然成立，但**尚未执行过**。

### 1.3 报告落库现状

文本端点与语音端点在 `done` 时均 `Report(...)` 写入五元组结果字段，**无** `scoring_version`。
`scoring.score_interview(..., mode="text"|"voice")` 仅影响 `expression_fluency` 计算，**不**把 `mode` 持久化到 session/report。

---

## 2. `POST /api/sessions` 与相关真实状态

### 2.1 请求体（契约 vs 实现）

| 项 | 规格草案 §4.2 | 当前 main |
| --- | --- | --- |
| 请求 schema | `{job_id, user_id, mode}` 三者必填，`extra=forbid` | `SessionCreateRequest` **仅** `job_id: int ≥1`，`extra=forbid` |
| `user_id` | 客户端必填；校验 role=student | **忽略请求**；恒 `user_id=1` |
| 默认用户 | **禁止**自动建档 | 若不存在则创建 `id=1, name_masked="演示学生", major="车辆工程", grade="大三"` |
| `mode` | 必填枚举 `毕业生\|新生`，无默认 | 硬编码 `"毕业生"` |
| `input_mode` | 创建时 NULL；首答按端点写入 | **无列、无写入、无 409 混用校验** |
| 成功响应 | `{sid, question}` | 另含 T4 字段 `transition_audio_urls: list[str]`（成长规格示例未列，**兼容可加字段，非冲突**） |

### 2.2 答题端点与评分口径（当前已进 M2 能力）

| 端点 | 评分调用 | 会话级口径持久化 |
| --- | --- | --- |
| `POST .../answers/text` | `score_interview(..., mode="text")` | 无 |
| `POST .../answers`（音频） | `score_interview(..., mode="voice", acoustic_samples=...)` | 无 |

**冲突风险**：同一 `sid` 理论上可交替打文本/语音端点；服务端无 `INPUT_MODE_MISMATCH`。成长规格要求首答锁定 `input_mode`，此缺口在 **voice 已合入的 main** 上比 G0 起草时更紧迫。

**施工约束（审查确认）**：`input_mode` 须在**首次答题的租约事务内原子写入**；后续提交若端点模式与已存值不一致 → `409 INPUT_MODE_MISMATCH`（不覆盖、不形成混合会话）。

### 2.3 既有测试对创建契约的依赖

以下测试一律 `POST /api/sessions` + `{"job_id": 1}`（破坏性变更后必改，且越出 AGENTS 预定 T7-G1 文件边界）：

- `tests/test_text_flow.py`
- `tests/test_audio_flow.py`
- `tests/test_tts.py`

---

## 3. 报告页成长入口与前端身份

### 3.1 报告页（`web/app/reports/[sid]/page.tsx`）

- **已有**「查看成长记录」→ `href="/growth"`。
- **缺失**：`web/app/growth/` **不存在** → 链接为死链（Next 404）。
- 文本/语音展示靠 `isTextModeReport()`：`expression_fluency.score===null` 且 `reason==="文本模式，未评估语音流畅度"`（`web/lib/report-data.ts`）。这是**隐式推断**，与规格要求的显式 `input_mode` **不一致**（报告页短期可保留文案启发式；成长 API 不得用此启发式替代字段）。

### 3.2 首页（`web/app/page.tsx`）

- `requestRealSession(jobId)` body = `JSON.stringify({ job_id: jobId })`。
- **无**学生选择器；**无** `localStorage` / `sessionStorage` 身份；**无** `user_id` / 受众 `mode` 传递。
- `ApiMode` 的 `mock|real` 是前端演示开关，**不是**规格中的 `毕业生|新生`，也不是 `text|voice`。

### 3.3 种子脚本（`scripts/import_seeds.py`）

- 只导入 `Job` / `Question`；**零** `User` 写入。
- 与规格 §12「幂等预置 id=3、4；冲突即失败」**完全缺失**。

### 3.4 路由挂载（`server/main.py`）

- 仅 `jobs` / `sessions` / `reports`；**无** `growth` / `students` router。
- `tests/test_growth.py` **不存在**。

---

## 4. 对照 `growth-tracking-spec.md` 逐项清单

### 4.1 已满足（可复用，无需为成长再建）

| # | 项 | 证据 |
| --- | --- | --- |
| S1 | users/sessions/reports/answers 核心关系可用 | `server/models.py` |
| S2 | 完成态 + 报告落库可支撑历史事实源 | sessions `completed` + Report 写入 |
| S3 | 四维 JSON + 文本流畅度 null 语义 | scoring + §8.1 已落地 |
| S4 | 有效维度可由 score≠null 推导 | 无需新字段 |
| S5 | `ensure_schema_upgrades` ALTER 先例 | `server/db.py` |
| S6 | 报告页雷达/证据/改进/再次训练 | `web/app/reports/[sid]/page.tsx` |
| S7 | 报告页已留成长入口文案与链接 | 同上（页未建） |
| S8 | 前端已有 echarts，无新依赖需求 | `web/package.json` echarts@5.6.0 |
| S9 | 不存在 growth 表 / 成长 LLM（符合非目标） | 全仓无 growth 实现 |

### 4.2 缺失（相对规格草案）

| # | 项 |
| --- | --- |
| M1 | `GET /api/students` |
| M2 | `GET /api/growth/{user_id}/history` |
| M3 | `GET /api/growth/{user_id}/trend` + §4.5 可比性算法 |
| M4 | `sessions.input_mode` 列 + 首答（租约事务内）原子写入 + 后续一致性校验 |
| M5 | `reports.scoring_version` 列 + `SCORING_VERSION` 常量写入 |
| M6 | `POST /api/sessions` 必填 `user_id`+`mode`；删除 id=1 自动建档 |
| M7 | 错误码 `USER_NOT_FOUND` / `INPUT_MODE_MISMATCH` |
| M8 | `scripts/import_seeds.py` ≥2 演示学生（建议 id=3、4，冲突即失败） |
| M9 | `server/services/growth.py`、`server/api/growth.py`、`tests/test_growth.py` |
| M10 | `web/app/growth/page.tsx`（历史/趋势/空状态/折线 connectNulls:false） |
| M11 | 首页学生档案选择 + 创建会话带 `user_id`/`mode` +（可选）localStorage |
| M12 | `web/lib/growth-data.ts`（响应校验与趋势转换；审查建议批准新增） |
| M13 | 成长页查询零 LLM（实现时 monkeypatch 验收 A16） |

### 4.3 当前实现与规格冲突

| # | 冲突 | 当前行为 | 规格要求 |
| --- | --- | --- | --- |
| C1 | 全员默认用户 | 恒 `user_id=1` + 自动建「演示学生」 | 显式 `user_id`；禁止自动建档；§10.2 明令禁止 |
| C2 | 创建请求体 | 仅 `job_id`；多传字段 422 | 必填 `user_id`+`mode` |
| C3 | 受众 mode | 服务端写死「毕业生」 | 请求体必填，无默认 |
| C4 | 输入模式 | 无字段；双端点可混用 | 首答锁定；混用 409 |
| C5 | 评分版本 | 无字段 | 报告写入版本；NULL=legacy 不可比 |
| C6 | 前端身份 | 无选择、无持久化 | GET students + 选择后再创建会话 |
| C7 | 成长入口 | `/growth` 死链 | 可打开成长页并带身份上下文 |
| C8 | AGENTS 预定边界 vs 规格扩界 | T7-G1 预定文件不含 sessions/models/db/scoring/import_seeds | 规格 §10/§12 申请扩界——**未批准不得改** |

### 4.4 规格中已过期的假设（相对 `5c5c3ca`）

| # | 规格表述 | 现状 |
| --- | --- | --- |
| E1 | 「T7-G0 起点尚无 `web/`」 | main 已有完整 `web/`（T3-B + T6 等） |
| E2 | 「M2 落地前不存在 voice 会话」/ 场景 6.3 标为 M2 后 | **语音答题端点与 voice 评分已在 main**；夹具不再是唯一构造手段，混用风险已是现网行为 |
| E3 | 实现核查基线 `d8037c2`；「Gemini 并行修 T3-A」 | T3-A 已合入；其后 T4/T5/T6 等已进 main；scoring 有声学流畅度变更（如 `fd6b81a`） |
| E4 | 创建响应示例仅 `{sid, question}` | 实际另有 `transition_audio_urls`（T4）；成长契约无需回退该字段 |
| E5 | 文档头「草案 v2，待队长批准」 | 规格文件已合入 main，但 **AGENTS §10.2 仍要求「队长批准契约变更后交施工」**；合入 ≠ 批准 API/模型变更 |
| E6 | 附「评分算法自 d8037c2 后未变」作为 v1 依据 | **已变**（语音流畅度路径）；且 **ASR 汉字间空格修复即将改变 evidence 有效率与内容评分**。**禁止**把 `5c5c3ca` 直接冻结为 `v1`；须先完成并验收 ASR 输出规范化，再以修复后的评分链定义为 `v1`（见 P8） |

---

## 5. T7-G1 所需实施地图（批准后施工；本文不批准）

### 5.1 API 变更（均待批）

| 变更 | 类型 |
| --- | --- |
| `POST /api/sessions` 请求体增必填 `user_id`、`mode`；删 id=1 自动建档 | **破坏性** |
| `404 USER_NOT_FOUND`、`409 INPUT_MODE_MISMATCH` | 错误语义新增 |
| `GET /api/students` | 新增只读 |
| `GET /api/growth/{user_id}/history` | 新增只读 |
| `GET /api/growth/{user_id}/trend` | 新增只读 |

成功响应形状、报告 GET、答题端点路径建议保持；`transition_audio_urls` 保留。

### 5.2 数据字段（均待批；不新建表）

| 列 | 表 | 空值语义 |
| --- | --- | --- |
| `input_mode VARCHAR(16) NULL` | `sessions` | NULL=创建中/legacy；完成会话应由答题路径写入 `text`/`voice` |
| `scoring_version VARCHAR(16) NULL` | `reports` | NULL=legacy 不可比；新报告写 `"v1"`（**仅当 P8 定义的 ASR 规范化后评分链已验收**） |

迁移：扩展 `ensure_schema_upgrades()`；不引入 Alembic；**禁止**自动 COALESCE 回填（规格 §9.3 / §12#10）。

### 5.3 精确文件清单（建议拆票后的全集）

**后端（建议票 BE）**

| 文件 | 动作 |
| --- | --- |
| `server/services/growth.py` | 新增 |
| `server/api/growth.py` | 新增（含 students + growth 两路由，或 students 同文件分路由） |
| `server/schemas.py` | 修改 |
| `server/main.py` | 修改（挂载 router） |
| `server/api/sessions.py` | 修改（身份/mode/input_mode 租约内原子写）**[扩界]** |
| `server/models.py` | 修改（两列）**[扩界]** |
| `server/db.py` | 修改（迁移）**[扩界]** |
| `server/services/scoring.py` | 修改（`SCORING_VERSION`，依赖 P8）**[扩界]** |
| `scripts/import_seeds.py` | 修改（双学生种子）**[扩界]** |
| `tests/test_growth.py` | 新增（先写 happy-path） |
| `tests/test_text_flow.py` | 修改（创建 body）**[扩界·兼容]** |
| `tests/test_audio_flow.py` | 修改（创建 body）**[扩界·兼容]** |
| `tests/test_tts.py` | 修改（创建 body）**[扩界·兼容]** |

**前端（建议票 FE）**

| 文件 | 动作 |
| --- | --- |
| `web/app/growth/page.tsx` | 新增 |
| `web/app/page.tsx` | 修改（档案选择 + 创建传参） |
| `web/app/reports/[sid]/page.tsx` | 修改（成长链接带 `user_id`/`job_id` 查询；死链变活） |
| `web/lib/growth-data.ts` | **新增（审查建议批准）**：响应校验、趋势/历史转换、空状态与 reasons 映射；避免逻辑全堆进 page |

**明确不在本审计批准范围内、且规格也不要求 T7-G1 改的**：`AGENTS.md` 正文契约表（待队长批后再改）、企业端 `recruiter`（A10–A12 属 T8）、新生端（T9）。

### 5.4 迁移兼容策略（建议写入批准说明）

1. `create_all` + `ensure_schema_upgrades` 为存量 SQLite 加可空列。
2. 存量行保持 NULL；growth 比较对 NULL 返回 `*_UNKNOWN`，不参与 overall 比较。
3. 不设自动回填工具；演示库若需人工 UPDATE，**单独审批**。
4. 合入后所有新完成会话：首答在租约事务内写 `input_mode`；新报告写 `scoring_version="v1"`（仅当 P8 已满足）。
5. 破坏性请求体：旧客户端只发 `job_id` → 422。**不得**让仅合入 BE 的 main 对外演示；须经集成分支前后端齐备后一次性进 main（见 §7.3）。

### 5.5 两名学生种子方案（规格 §7 / §12#6；待批）

| id | name_masked | major | grade | role |
| --- | --- | --- | --- | --- |
| 3 | 王*明 | 车辆工程 | 大三 | student |
| 4 | 李*华 | 智能车辆工程 | 大二 | student |

规则：

- 写入走 `import_seeds.py` 幂等；**不提供**建档 API。
- 目标 id 已存在且四元组不完全一致 → **非零退出**，禁止覆盖。
- **避开 id=1**：现存自动建档与大量测试可能已占用 1；种子用 3/4。
- 施工后应删除「创建会话时自动插入 id=1」逻辑；既有库中 id=1 行可残留但不再作为默认绑定。

### 5.6 后端测试矩阵（`tests/test_growth.py`；对齐规格 §11）

| # | 归属 T7-G1？ | 说明 |
| --- | --- | --- |
| A1–A9, A13–A17 | **是** | 隔离、趋势、空/单次、缺维、text/voice、版本、维度集、非法身份、缺 user_id、仅 completed、零 LLM、种子冲突 |
| A10–A12 | **否（T8）** | recruiter 候选；本票只预留夹具注释，不实现企业 API |
| A7 | M2 已具备 | 仍可用夹具直写；亦可用真 voice/text 双会话构造（夹具不得进演示库） |

**回归**：现有 text/audio/tts 创建会话用例改为带 `user_id`+`mode`（种子用户或测试夹具用户）。

### 5.7 前端页面与 30 秒人工路径

```
打开 / → 选择学生档案（≥2）→ 选岗位 →（real）设备自检 → 面试完成
→ /reports/{sid} → 点「查看成长记录」
→ /growth?user_id=…&job_id=… → 见历史与趋势（或空状态）
→ 点某条打开原报告；点「再次训练」回 /
```

验收文案约束：「本次比上次变化」；缺维显示「未评估」；折线 `connectNulls: false`；0/1 次明确空状态。

---

## 6. 需要队长批准的事项（集中清单）

> 审计**不**替队长勾选。下列为规格 §12 + 本审计相对 main 的增补；§6.2 为审查建议的审批包，供队长一次性批准。

### 6.1 二选一 / 明确批准项

| ID | 事项 | 选项 |
| --- | --- | --- |
| P1 | `POST /api/sessions` 破坏性请求体（必填 `user_id`+`mode`，删 id=1 自动建档） | **批准破坏性变更** / **驳回并要求兼容层（如可选 user_id 默认？——与 §10.2 冲突，不推荐）** |
| P2 | 新增错误码 `USER_NOT_FOUND`、`INPUT_MODE_MISMATCH` | **批准** / **驳回** |
| P3 | 新增 `GET /api/students` | **批准** / **驳回** |
| P4 | 新增 `GET /api/growth/.../history` 与 `.../trend`（含 §4.5 算法与 reasons 码表） | **批准** / **驳回** |
| P5 | 加列 `sessions.input_mode`、`reports.scoring_version`（NULL=legacy，不兜底）；`input_mode` 在首次答题租约事务内原子写入 | **批准** / **驳回** |
| P6 | T7-G1 文件扩界：`sessions.py`、`models.py`、`db.py`、`scoring.py`、`import_seeds.py` + 三个既有测试文件 | **批准扩界** / **驳回（则无法落地身份与口径）** |
| P7 | 种子学生固定 id=3、4 + 冲突即失败 | **批准** / **改用其他固定 id（请明示）** |
| P8 | `SCORING_VERSION="v1"` 基线定义 | **批准：ASR 汉字间空格规范化修复并验收之后的评分行为定义为 `v1`** / **驳回（须另定基线）**。**禁止**把当前 `main @ 5c5c3ca` 直接冻结为 `v1` |
| P9 | 存量 NULL 回填 | **不批准自动回填（规格默认）** / **批准人工回填批次（另开任务）** |
| P10 | 新建 growth/候选表 | **不批准（规格默认）** / **批准新建（与 §10.2 冲突）** |
| P11 | 成长页新增 LLM 总结 | **不批准（规格默认）** / **批准（与 §10.2 冲突）** |
| P12 | 注册登录认证 | **不批准（规格默认）** / **批准（超范围）** |
| P13 | 新第三方依赖 | **不批准（用 echarts）** / **批准某库（点名）** |
| P14 | 前端新增 `web/lib/growth-data.ts`（响应校验与趋势转换） | **批准新增** / **禁止，逻辑仅写在 page.tsx** |
| P15 | T7-G1 开工闸门 | **完成本审计修订且队长批准 §6.2 审批包后开工** / **仍仅作草案，暂缓 G1** |
| P16 | A10–A12 | **确认留 T8** / **要求 G1 一并做（需企业 API 边界）** |
| P17 | 合入策略（审查新增） | **批准：BE/FE 可并行开发，均先汇入 `feature/T7-growth-integration`，全链路测试通过后一次性合入 main；禁止 BE 或 FE 单独先合 main** / **驳回（须另定策略）** |

### 6.2 建议审批包（审查调整后；供队长一次性批准）

| 项 | 建议 |
| --- | --- |
| 批准 | **P1–P7、P14、P17** |
| P8 | 改为「**ASR 空格规范化修复验收后的评分行为定义为 `v1`**」（非 `5c5c3ca`） |
| 不批准 | **P9–P13** |
| P15 | 完成上述修订后 **批准 T7-G1 开工**（仍须队长明示） |
| P16 | A10–A12 **留在 T8** |
| 合入 | BE、FE **不得**直接先合入 main；统一进入 `feature/T7-growth-integration` 验证后合入 |

**开工前置（审查阻断项）**：先处理并验收 **ASR 汉字间空格缺陷** → 再冻结 `v1` → 再在 T7-G1 写入 `SCORING_VERSION`。

---

## 7. 可并行拆分（文件不交叉）

### 7.1 建议任务票 BE：`[T7-G1-BE]` 分支 `feature/T7-growth-be`

**前置**：队长批准 §6.2 审批包；P8 依赖的 ASR 规范化已验收（或 BE 中 `SCORING_VERSION` 写入与 ASR 票串行，不得抢先标 `v1`）。
**文件**：§5.3 后端表全部；**不得**改 `web/**`。
**顺序**：先写 `tests/test_growth.py` happy-path（A3）→ models/db → sessions/scoring/seeds → growth API → 修回归测试。
**验收**：A1–A9、A13–A17 自动化绿；现有 text/audio/tts 回归绿。
**合入**：只合入 `feature/T7-growth-integration`，**禁止**直接合 main。

### 7.2 建议任务票 FE：`[T7-G1-FE]` 分支 `feature/T7-growth-fe`

**前置**：契约批准；可与 BE 并行（按冻结契约/fixture 开发）；`web/lib/growth-data.ts` 在 P14 批准下新增。
**文件**：§5.3 前端表；**不得**改 `server/**`、`scripts/**`、`tests/test_*.py`。
**顺序**：`growth-data.ts` → 首页档案选择 → 创建 body → `growth/page.tsx` → 报告页链接 query。
**验收**：构建通过；30 秒人工路径；空/单次/缺维 UI；文案合规。
**合入**：只合入 `feature/T7-growth-integration`，**禁止**直接合 main。

### 7.3 合流顺序（保证 main 永远可演示）

1. 自 main 拉出 `feature/T7-growth-integration`。
2. BE 与 FE **并行开发**，分别合入 integration（文件不交叉）。
3. 在 integration 上完成全链路测试（两学生 × 两岗位 × 同岗三次 + 创建破坏性契约联调）。
4. **一次性**将 integration 合入 main（前后端同发版，避免中间态旧前端对 BE 全 422）。
5. **禁止**「BE 先合 main → FE 再合 main」；**禁止**在未批扩界文件上「顺手重构」。

---

## 8. 风险与依赖

| 风险 | 等级 | 说明 |
| --- | --- | --- |
| 契约未批即施工 | 高 | AGENTS：批准后方可交施工；规格头仍写待批 |
| BE 单独进 main | 高 | 旧前端创建请求全 422，破坏「main 永远可演示」；用 integration 闸门化解 |
| 过早冻结 `v1` | 高 | ASR 空格修复将改 evidence/评分；P8 须等 ASR 验收 |
| 演示库全是 user_id=1 | 中 | 成长隔离演示失败；需种子 3/4 + 新会话 |
| voice/text 混用存量会话 | 中 | 无 input_mode；历史不可比属预期，但演示前应清库或隔离 |
| 报告页死链 | 低 | FE 进 integration 前演示勿点「成长」 |
| T8 候选规则未定 | 低 | 不阻塞 G1，但阻塞企业闭环叙事 |
| 扩界测试文件漏改 | 高 | 漏改则 CI 红 |

**依赖**：T3-B 报告页（已满足）；T7-G0 规格（已合入文档）；**ASR 空格规范化验收（P8 前置，未满足）**；**队长契约批准（未满足）**；echarts（已有）；不新增依赖、不新建 growth 表、不新增 LLM。

---

## 9. 与「不新增」纪律的符合性检查

| 约束 | 审计结论 |
| --- | --- |
| 不新建 growth 表 | 规格明确不建议；现码也无；**保持** |
| 不新增第三方依赖 | 前端已有 echarts；后端无新包需求；**保持** |
| 不新增 LLM 调用 | 成长查询纯 DB；A16 验收；**保持** |
| 若发现规格要求冲突 | **未发现**规格要求新建表/新依赖/新 LLM；冲突仅在于规格草案与**当前生产行为**（默认用户等） |

---

## 10. 当前差距摘要（派工用）

```
[身份]     全员 → user_id=1          规格 → 显式多学生
[口径]     无 input_mode/version     规格 → 两列 + 比较算法
[API]      无 students/growth        规格 → 3 只读 + 破坏性 create
[前端]     无选择器；/growth 404     规格 → 选择 + 成长页 + growth-data.ts
[种子]     仅岗位题库                规格 → ≥2 学生冲突即失败
[v1 基线]  禁止冻 5c5c3ca            须 ASR 空格规范化验收后定义
[合入]     禁 BE/FE 各自先合 main    → feature/T7-growth-integration 一次合入
[治理]     规格已合入但仍待队长批契约 → 阻塞 T7-G1 生产改动
```

---

## 附：本审计未改动清单

- 未修改任何生产代码
- 未修改 `docs/growth-tracking-spec.md`
- 未修改 `AGENTS.md`
- 未读取 `*.log` / `.workbuddy/` / `.godot/`
- 唯一文档产出：`docs/growth-implementation-audit.md`
