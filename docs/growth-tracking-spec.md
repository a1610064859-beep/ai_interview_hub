# 成长追踪接口与身份规格（T7-G0）

| 项 | 值 |
| --- | --- |
| 状态 | **草案，待队长/Astra 审查批准**（本文档只含规格与审批申请，未改任何生产代码） |
| 任务 | AGENTS.md §10.2 [T7-G0]，分支 `feature/T7-growth-spec`，worktree `E:\ai_interview_hub_growth_spec` |
| 起点 | 提交 `b79b15a`（= `codex/growth-tracking-plan`，已核实两者同一提交） |
| 实现核查基线 | 提交 `d8037c2`（T7-G0 分支头，2026-09-21，含 T3-A 修复）。Gemini 正在并行修复 T3-A，若其后端契约再变，以最新验收版本为准 |
| 下游 | T7-G1（实现）、T8（企业闭环）、T9（新生端）按本契约施工 |

**标记约定**：`[已验证]`=已读当前代码确认；`[未验证]`=未核实，施工前需确认；`[待T8审批]`=留待 T8 任务票定稿；`[提案]`=本文申请的变更，批准前不存在。

**宣称纪律**：成长页所有增减描述统一为"本次比上次变化"（模型评分的观测），禁止表述为"能力提升/就业成功率提升"。测试夹具数据与真实参与者数据必须可区分。

---

## 1. 目标与非目标

### 目标
1. 同一学生、同一岗位的多次训练可查历史、看趋势、回看最近两次变化与原改进建议。
2. 最小身份方案：稳定区分至少两名学生，会话明确归属 `user_id`，不扩大为账号系统。
3. 企业端候选记录全部来自学生端真实落库报告，可追溯 `session_id`/`report_id`，同岗位每生一条、再训练原地更新。
4. 缺失维度不补零、不跨缺失点连线；不可比时返回明确原因，不生成虚假增减。
5. 成长查询零 LLM 调用、零新第三方依赖；历史亮点/顾虑/建议直接读原报告。

### 非目标（做了即事故）
- 完整账号系统（注册/登录/会话鉴权/权限模型）
- 密码登录、验证码、OAuth 等任何认证机制
- 课程平台、学习资源分发
- 任务打卡、连续训练激励、排行榜
- 自动推送（消息/邮件/站内信）
- 新增第三个岗位或岗位铺量
- 新增成长评分模型 / 对历史报告重新打分或重算
- 向量数据库、RAG、任何新基建

---

## 2. 现有数据能支持什么

逐表核查（基于 `d8037c2` 的 `server/models.py`、`server/api/sessions.py`、`server/services/scoring.py`）：

### users（支持档案选择，基本够用）
- 已有 `id, role(student/recruiter/admin), name_masked, major, grade` `[已验证]`。成长所需的学生身份、脱敏姓名、专业年级齐备。
- **缺失①**：无学生档案列表接口；前端目前无从选择。
- **缺失②（行为缺陷）**：`POST /api/sessions` 当前硬编码 `user_id=1` 并自动创建"演示学生"用户 `[已验证]`。这正是 §10.2 明令禁止的"所有学生绑一个默认用户"，必须移除，改为显式传 `user_id`（见 §4.2）。
- 学生档案的初始数据来源：现状无任何建用户入口（除上述自动建 id=1）。`[提案]` 由 `scripts/import_seeds.py` 幂等预置 ≥2 名演示学生档案（见 §12）。

### sessions（归属与过滤够用，缺输入模式）
- 已有 `id, user_id, job_id, mode, started_at, status, pending_question_json, lease_*` `[已验证]`。
- `status` 实际取值 `active / answering / completed` `[已验证]`；成长只取 `completed`。
- `mode` 现被硬编码为 `"毕业生"`，语义是**受众模式**（毕业生/新生），不是输入模式（文本/语音）`[已验证]`。**不可**把它当输入模式用于可比性判定（见 §9）。
- **缺失**：无输入模式字段（文本/语音），M1 只有文本提交端点，M2 语音落地后无法从契约层面区分两种评分口径（见 §9）。

### answers（够用）
- `duration_s, wpm, pause_cnt` 可空，文本模式落库为 NULL；`filler_cnt` 恒统计 `[已验证]`。与 §8.1"文本模式不虚构语音值"一致，成长层不需要改动此表。

### reports（历史展示够用，缺评分版本）
- 已有 `dimensions_json, highlights_json, concerns_json, improvement_json, overall` `[已验证]`。
- `dimensions_json` 固定 4 键：`professional_match / logic_structure / expression_fluency / job_competence`，每维 `{score, evidence, reason}`；文本模式 `expression_fluency.score` 恒为 null，reason="文本模式，未评估语音流畅度"；某维双评未通过校验时该维 score=null `[已验证]`。
- **有效维度集合可推导**：`dimensions_json` 中 score 非 null 的键集合。不需要新字段。
- **缺失**：无评分口径版本字段。评分提示词/算法将来变更时，存量报告无从区分，趋势会把不同口径的分数画进同一条线（见 §9）。

### [未验证] 事项
- 线上 SQLite 库的现存数据内容（是否有 id=1 以外的用户/历史会话）——本仓为演示库，施工前以实际库为准；规格不依赖库内预存数据。
- `started_at` 经 FastAPI 序列化后的精确字符串格式（存储为 naive UTC `datetime.utcnow()` `[已验证]`；本文示例按 ISO 8601 无时区后缀书写，最终以 T7-G1 实现与测试为准）。
- `server/db.py` 的 `ensure_schema_upgrades()` 目前只检查 `sessions` 表并手工 `ALTER TABLE ADD COLUMN` `[已验证]`——新增 `reports` 表列需扩展该函数，模式已有先例，但具体语句未执行过。

**结论**：不新建 growth 表、不存可由报告推导的重复分数即可支撑全部需求；需要新增的只有 2 个口径识别字段（§9）和 3 个只读接口 + 1 处创建接口契约变更（§4）。

---

## 3. 最小身份方案（学生档案选择）

### 3.1 流程
```
打开首页(web/app/page.tsx)
  → GET /api/students 拉取学生档案下拉列表（role=student）
  → 学生选择自己（演示环境每人固定选自己的档案；选择可记 localStorage 便于连续演示，可随时切换）
  → 选岗位 → POST /api/sessions {job_id, user_id}   ← user_id 为必填，来自下拉选择
  → 新生端(T9)：咨询结果页"进入岗位训练"按钮携带同一 user_id 走相同接口，sessions.mode 记 "新生"
  → 训练、报告、成长历史均按该 user_id 归档
```
- **不提供**任何建档/注册 API。档案只能由种子脚本幂等预置，杜绝客户端捏造身份。
- **不引入**登录态：`user_id` 即演示身份，仅限本机/局域网演示场景（AGENTS §2、§10.2 已批准此口径）。
- 每次创建会话服务端都重新校验 user 存在且 `role='student'`，不信任前端缓存。

### 3.2 非法 / 缺失 / 不存在 user_id 的行为
| 情形 | 行为 |
| --- | --- |
| 请求体缺 `user_id` 或类型/取值非法（非正整数） | `422`，沿用 FastAPI 校验错误格式（与 §8.1 一致） |
| `user_id` 在 users 表不存在 | `404 {"detail":{"code":"USER_NOT_FOUND","message":"学生档案不存在"}}` |
| `user_id` 存在但 `role != 'student'` | 同上 `404 USER_NOT_FOUND`（不区分暴露，防探测） |
| 岗位与学生均不存在 | 返回 `404 JOB_NOT_FOUND`（保持既有检查优先级，减少对现有测试影响） |
| 客户端提交不存在但"看起来合理"的 user_id | 一律 404，**禁止**静默自动创建用户（废除现 id=1 自动建档逻辑 `[已验证]`） |

---

## 4. 精确 API 草案

> 以下 4.1、4.3、4.4 为新增只读接口；4.2 为对已批准契约（AGENTS §8）的**破坏性变更申请**，批准前不得施工。ID 均为正整数，JSON 字段下划线命名，与 §8.1 约定一致。

### 4.1 GET /api/students —— 学生档案列表

- 方法/路径：`GET /api/students`
- 请求参数：无
- 排序：`id` 升序
- 空列表：`200 {"students": []}`，前端显示"暂无学生档案"空状态（种子脚本保证演示环境 ≥2 名学生）

**200 响应示例**：
```json
{
  "students": [
    {"id": 3, "name_masked": "王*明", "major": "车辆工程", "grade": "大三"},
    {"id": 4, "name_masked": "李*华", "major": "智能车辆工程", "grade": "大二"}
  ]
}
```
- 错误：无业务错误码（恒 200）。

### 4.2 POST /api/sessions —— 创建面试（契约变更申请）

- 方法/路径：`POST /api/sessions`（不变）
- 请求体：`{"job_id": 1, "user_id": 3}`，`user_id` **新增必填**，`extra="forbid"`（拒绝额外字段）
- 成功响应：不变（`{"sid":1,"question":{"text":"…","audio_url":null,"seq":1}}`）
- 行为变更：
  1. 删除"id=1 演示学生不存在则自动创建"的逻辑 `[已验证]`，改为按 §3.2 校验；
  2. `sessions.user_id = req.user_id`；`sessions.mode` 由调用方场景决定（毕业生入口 "毕业生"，T9 新生入口 "新生"；默认 "毕业生"）；
  3. 首次答题提交时由**服务端**按所命中端点写入 `sessions.input_mode`（`/answers/text` → `"text"`；M2 音频端点 → `"voice"`）。创建时该列为 NULL，是合法中间态——成长查询只读 `completed` 会话，其必有答案，故恒有值。
- 错误：在既有 `404 JOB_NOT_FOUND / 404 SESSION_NOT_FOUND / 409 SESSION_COMPLETED / 409 ANSWER_IN_PROGRESS / 422 / 503 SCORING_UNAVAILABLE` 基础上，新增 `404 USER_NOT_FOUND`（§3.2）。

### 4.3 GET /api/growth/{user_id}/history —— 某学生的成长历史

- 方法/路径：`GET /api/growth/{user_id}/history`
- 请求参数：`job_id`（可选 query，正整数；缺省=全部岗位）
- 数据范围：`sessions.user_id={user_id} AND sessions.status='completed' AND 存在对应 report`；**排除** active/answering 会话与无报告会话
- 排序：`started_at ASC, session.id ASC`（时间升序为正序时间线，同刻按 id 定序，与 §10.2 稳定顺序一致）
- 空列表：`200` 且 `records: []`（不是 404）
- 错误：`404 USER_NOT_FOUND`（用户不存在/非学生）；`job_id` 对应岗位不存在时 `404 JOB_NOT_FOUND`；`job_id<1` 或非整数 `422`

**200 响应示例**（学生3、岗位1，两条历史）：
```json
{
  "user_id": 3,
  "job_id": 1,
  "records": [
    {
      "session_id": 11,
      "report_id": 11,
      "job_id": 1,
      "job_title": "智驾测试工程师",
      "started_at": "2026-09-20T10:00:00",
      "mode": "毕业生",
      "input_mode": "text",
      "scoring_version": "v1",
      "overall": 70.0,
      "dimensions": {
        "professional_match": 68.0,
        "logic_structure": 72.0,
        "expression_fluency": null,
        "job_competence": 70.0
      },
      "improvement": ["回答先给结论再展开，避免铺垫过长", "补充智驾法规相关术语"]
    },
    {
      "session_id": 13,
      "report_id": 13,
      "job_id": 1,
      "job_title": "智驾测试工程师",
      "started_at": "2026-09-21T09:00:00",
      "mode": "毕业生",
      "input_mode": "text",
      "scoring_version": "v1",
      "overall": 75.0,
      "dimensions": {
        "professional_match": 73.0,
        "logic_structure": 76.0,
        "expression_fluency": null,
        "job_competence": 76.0
      },
      "improvement": ["情景题可加入更多安全兜底思考"]
    }
  ]
}
```
- `dimensions` 值域为 `分数|null` 的固定 4 键映射（null=未评估）；`overall` 为 `分数|null`（全维缺失时 null，§8.1）。evidence/reason 明细不入历史列表，点开单条走既有 `GET /api/reports/{sid}`，**不重复返回、不重新生成**。
- `input_mode`/`scoring_version` 读取语义：NULL 按 `text`/`v1` 处理（兼容依据见 §9）。

### 4.4 GET /api/growth/{user_id}/trend —— 某学生在某岗位的趋势

- 方法/路径：`GET /api/growth/{user_id}/trend`
- 请求参数：`job_id`（**必填** query，正整数；缺失/非法 → `422`）
- 数据范围与排序：同 §4.3（限定该 job_id）
- `input_mode` 字段：该岗位全部点同模式 → `"text"|"voice"`；混合 → `"mixed"`；无点 → `null`
- 错误：`404 USER_NOT_FOUND`、`404 JOB_NOT_FOUND`，同 §4.3

**200 响应通用结构**：
```json
{
  "user_id": 3,
  "job_id": 1,
  "job_title": "智驾测试工程师",
  "input_mode": "text",
  "sessions_count": 3,
  "points": [
    {
      "session_id": 11, "report_id": 11, "started_at": "2026-09-20T10:00:00",
      "overall": 70.0,
      "dimensions": {"professional_match": 68.0, "logic_structure": 72.0, "expression_fluency": null, "job_competence": 70.0}
    }
  ],
  "overall_comparison": {
    "comparable": true,
    "reasons": [],
    "message": null,
    "previous": {"session_id": 12, "overall": 72.5},
    "current":  {"session_id": 13, "overall": 75.0},
    "delta": 2.5
  },
  "dimension_changes": {
    "professional_match": {"previous": 71.0, "current": 73.0, "delta": 2.0},
    "logic_structure":    {"previous": 74.0, "current": 76.0, "delta": 2.0},
    "expression_fluency": null,
    "job_competence":     {"previous": 72.5, "current": 76.0, "delta": 3.5}
  }
}
```
- `points` 恒为全部合格点（折线数据源）；`overall_comparison` / `dimension_changes` 只看**最近两次**合格记录。
- `reasons` 为机器可读码：`NO_RECORDS` / `SINGLE_RECORD` / `OVERALL_MISSING` / `INPUT_MODE_MISMATCH` / `SCORING_VERSION_MISMATCH` / `DIMENSION_SET_MISMATCH` / `EMPTY_DIMENSION_SET`；`message` 为中文人读文案（可空）。
- `dimension_changes` 固定 4 键：仅当该维在最近两次**均非 null** 才给出 `{previous, current, delta}`，否则该键为 `null`（前端显示"未评估"，绝不画 0）。

### 4.5 可比性判定算法（growth 服务内实现，纯查询无 LLM）

```
合格记录 R = sessions(user_id, job_id, status='completed') 且存在 report，按 (started_at, id) 升序
若 |R| == 0 → reasons=[NO_RECORDS]
若 |R| == 1 → reasons=[SINGLE_RECORD]
否则取 prev=R[-2], curr=R[-1]：
  overall 可比 ⟺ 以下全部成立：
    a) curr.overall 与 prev.overall 均非 null          否则 OVERALL_MISSING
    b) im(curr) == im(prev)                            否则 INPUT_MODE_MISMATCH   # im = COALESCE(input_mode,'text')
    c) sv(curr) == sv(prev)                            否则 SCORING_VERSION_MISMATCH # sv = COALESCE(scoring_version,'v1')
    d) eff(curr) == eff(prev) 且 eff(curr) ≠ ∅         否则 DIMENSION_SET_MISMATCH / EMPTY_DIMENSION_SET
       # eff(r) = {k | r.dimensions_json[k].score is not null}
  delta = ROUND_HALF_UP(curr.overall - prev.overall, 1)
  单维 delta：仅要求该维在 prev、curr 均 非 null（不要求集合相等）
```
- reasons 可叠加（如语音/文本 + 版本同变）。`comparable=false` 时 `delta=null`，`previous/current` 仍回显（不足两条时为 null）。

---

## 5. 历史记录响应字段规格（汇总）

每条 `records[]` 必含：`session_id, report_id, job_id, job_title, started_at, mode, input_mode, scoring_version, overall, dimensions, improvement`。
- `mode`：受众模式（毕业生/新生），仅展示，不参与可比性。
- `input_mode` / `scoring_version`：口径识别（NULL→`text`/`v1`）。
- `dimensions`：4 键 `分数|null` 映射。
- `improvement`：原报告 `improvement_json` 原文数组，禁止 LLM 重写。

---

## 6. 趋势响应五个规定场景（`GET /api/growth/3/trend?job_id=1`）

### 6.1 三次同岗可比训练
```json
{
  "user_id": 3, "job_id": 1, "job_title": "智驾测试工程师",
  "input_mode": "text", "sessions_count": 3,
  "points": [
    {"session_id": 11, "report_id": 11, "started_at": "2026-09-20T10:00:00", "overall": 70.0,
     "dimensions": {"professional_match": 68.0, "logic_structure": 72.0, "expression_fluency": null, "job_competence": 70.0}},
    {"session_id": 12, "report_id": 12, "started_at": "2026-09-20T16:00:00", "overall": 72.5,
     "dimensions": {"professional_match": 71.0, "logic_structure": 74.0, "expression_fluency": null, "job_competence": 72.5}},
    {"session_id": 13, "report_id": 13, "started_at": "2026-09-21T09:00:00", "overall": 75.0,
     "dimensions": {"professional_match": 73.0, "logic_structure": 76.0, "expression_fluency": null, "job_competence": 76.0}}
  ],
  "overall_comparison": {
    "comparable": true, "reasons": [], "message": null,
    "previous": {"session_id": 12, "overall": 72.5},
    "current": {"session_id": 13, "overall": 75.0},
    "delta": 2.5
  },
  "dimension_changes": {
    "professional_match": {"previous": 71.0, "current": 73.0, "delta": 2.0},
    "logic_structure": {"previous": 74.0, "current": 76.0, "delta": 2.0},
    "expression_fluency": null,
    "job_competence": {"previous": 72.5, "current": 76.0, "delta": 3.5}
  }
}
```
前端文案："本次比上次 +2.5（模型评分观测，不代表真实能力变化）"；`expression_fluency` 显示"未评估（文本模式）"。

### 6.2 某维缺失 → 折线断点
第 2 次（session 12）`logic_structure` 双评未过校验落 null：
```json
{
  "sessions_count": 3,
  "input_mode": "text",
  "points": [
    {"session_id": 11, "overall": 70.0, "dimensions": {"professional_match": 68.0, "logic_structure": 72.0, "expression_fluency": null, "job_competence": 70.0}},
    {"session_id": 12, "overall": 68.0, "dimensions": {"professional_match": 66.0, "logic_structure": null,    "expression_fluency": null, "job_competence": 70.0}},
    {"session_id": 13, "overall": 75.0, "dimensions": {"professional_match": 73.0, "logic_structure": 76.0, "expression_fluency": null, "job_competence": 76.0}}
  ],
  "overall_comparison": {
    "comparable": false,
    "reasons": ["DIMENSION_SET_MISMATCH"],
    "message": "两次训练的有效评分维度集合不同（第2次逻辑结构未评估），overall 不直接比较",
    "previous": {"session_id": 12, "overall": 68.0},
    "current": {"session_id": 13, "overall": 75.0},
    "delta": null
  },
  "dimension_changes": {
    "professional_match": {"previous": 66.0, "current": 73.0, "delta": 7.0},
    "logic_structure": null,
    "expression_fluency": null,
    "job_competence": {"previous": 70.0, "current": 76.0, "delta": 6.0}
  }
}
```
折线规则：`logic_structure` 序列为 `[72.0, null, 76.0]`，echarts `connectNulls: false`，第 2 点断开，不补零、不跨点连线。

### 6.3 overall 不可比（输入模式不同，M2 之后）
```json
{
  "input_mode": "mixed",
  "sessions_count": 2,
  "points": [
    {"session_id": 13, "started_at": "2026-09-21T09:00:00", "overall": 75.0, "dimensions": {"professional_match": 73.0, "logic_structure": 76.0, "expression_fluency": null, "job_competence": 76.0}},
    {"session_id": 20, "started_at": "2026-09-22T15:00:00", "overall": 78.0, "dimensions": {"professional_match": 75.0, "logic_structure": 78.0, "expression_fluency": 82.0, "job_competence": 77.0}}
  ],
  "overall_comparison": {
    "comparable": false,
    "reasons": ["INPUT_MODE_MISMATCH", "DIMENSION_SET_MISMATCH"],
    "message": "文本与语音训练评分口径不同，overall 不可直接比较",
    "previous": {"session_id": 13, "overall": 75.0},
    "current": {"session_id": 20, "overall": 78.0},
    "delta": null
  },
  "dimension_changes": {
    "professional_match": {"previous": 73.0, "current": 75.0, "delta": 2.0},
    "logic_structure": {"previous": 76.0, "current": 78.0, "delta": 2.0},
    "expression_fluency": null,
    "job_competence": {"previous": 76.0, "current": 77.0, "delta": 1.0}
  }
}
```
注：`expression_fluency` 因第 1 次（文本）为 null 不可算单维变化；单维变化不要求输入模式相同，只要求该维两次均有效。`[已验证：M2 落地前不存在 voice 会话，此场景为 M2 后契约]`

### 6.4 仅一次训练
```json
{
  "input_mode": "text",
  "sessions_count": 1,
  "points": [
    {"session_id": 11, "report_id": 11, "started_at": "2026-09-20T10:00:00", "overall": 70.0,
     "dimensions": {"professional_match": 68.0, "logic_structure": 72.0, "expression_fluency": null, "job_competence": 70.0}}
  ],
  "overall_comparison": {
    "comparable": false,
    "reasons": ["SINGLE_RECORD"],
    "message": "仅一次训练，暂无可比较的两次记录",
    "previous": null, "current": null, "delta": null
  },
  "dimension_changes": {
    "professional_match": null, "logic_structure": null,
    "expression_fluency": null, "job_competence": null
  }
}
```

### 6.5 零次训练
```json
{
  "input_mode": null,
  "sessions_count": 0,
  "points": [],
  "overall_comparison": {
    "comparable": false,
    "reasons": ["NO_RECORDS"],
    "message": "该岗位暂无已完成的训练记录",
    "previous": null, "current": null, "delta": null
  },
  "dimension_changes": {
    "professional_match": null, "logic_structure": null,
    "expression_fluency": null, "job_competence": null
  }
}
```
前端显示空状态与"去训练"入口，不画空图、不虚构趋势。

---

## 7. 两名学生隔离示例

种子档案：学生A=`id 3 王*明`，学生B=`id 4 李*华`，两人都在岗位1训练。

**学生A查询自己的历史** `GET /api/growth/3/history`（节选）：
```json
{
  "user_id": 3,
  "records": [
    {"session_id": 11, "report_id": 11, "job_id": 1, "overall": 70.0, "started_at": "2026-09-20T10:00:00"},
    {"session_id": 13, "report_id": 13, "job_id": 1, "overall": 75.0, "started_at": "2026-09-21T09:00:00"}
  ]
}
```

**学生B查询自己的历史** `GET /api/growth/4/history`：
```json
{
  "user_id": 4,
  "records": [
    {"session_id": 12, "report_id": 12, "job_id": 1, "overall": 72.5, "started_at": "2026-09-20T16:00:00"}
  ]
}
```

隔离断言（进自动化验收矩阵 A1）：
1. A 的 `records` 中不出现 `session_id=12`，B 的不出现 11/13 —— 尽管三人同岗位、时间交错；
2. `GET /api/growth/3/trend?job_id=1` 的 `points` 只含 11、13；B 的 72.5 分不出现在 A 的任何点、均值、delta 中；
3. `GET /api/growth/3/history` 与 `GET /api/growth/4/history` 返回的 `user_id` 与路径一致（服务端以路径为准，不接受 query 传身份）；
4. `GET /api/growth/999/history` → `404 USER_NOT_FOUND`。

---

## 8. 企业闭环规则（T8 按此实施）

```
学生训练(POST /api/sessions, user_id 绑定)
  → 6题+追问 → status='completed' + report 落库（唯一事实来源）
  → 企业查询 GET /api/recruiter/candidates?job_id（T8 实现，本规格不改其契约）
      候选记录 = 对每个 (job_id, user_id) 现场计算"最新合格报告"：
        合格 ⟺ session.status='completed' 且 report 存在
             且 COALESCE(scoring_version,'v1') ∈ T8 认定的可用口径集合
             且满足 T8 定稿的完整性要求 [待T8审批]
        取 (started_at, session.id) 最大的一条
  → 展示雷达图 + 加权排序
```

- **同源保证**：候选数据在查询时由 sessions+reports 联表计算，**不建候选表、不建静态排行榜**；学生再训练生成新报告后，下次查询自动命中其最新合格报告 → 天然"原地更新、不产生重复候选人"（同岗位每 `user_id` 恰一条）。
- **可追溯**：每条候选记录必须携带 `session_id`、`report_id`、`trained_at`（= session.started_at），点击可回看原报告页。
- **缺维不罚零**：某维 null 时不按 0 分计入加权；该候选是"降权/标记不完整/正常参与"由 T8 定稿 `[待T8审批]`。
- **权重**：维度权重与排序公式 `[待T8审批]`，本规格不定值。
- **口径隔离**：文本/语音报告不混排（候选记录携带 `input_mode`，是否分列展示由 T8 定稿 `[待T8审批]`）。

**候选条目示例**（形状参考，最终以 T8 任务票为准）：
```json
{
  "job_id": 1,
  "candidates": [
    {
      "user_id": 3, "name_masked": "王*明",
      "session_id": 13, "report_id": 13, "trained_at": "2026-09-21T09:00:00",
      "input_mode": "text", "scoring_version": "v1", "overall": 75.0,
      "dimensions": {"professional_match": 73.0, "logic_structure": 76.0, "expression_fluency": null, "job_competence": 76.0}
    },
    {
      "user_id": 4, "name_masked": "李*华",
      "session_id": 12, "report_id": 12, "trained_at": "2026-09-20T16:00:00",
      "input_mode": "text", "scoring_version": "v1", "overall": 72.5,
      "dimensions": {"professional_match": 71.0, "logic_structure": 74.0, "expression_fluency": null, "job_competence": 72.5}
    }
  ]
}
```
学生3 再训练生成 session 21/report 21（同岗位）后，同查询仍返回 2 条候选，学生3 条目变为 `session_id=21, report_id=21` —— 验收矩阵 A11。

---

## 9. 评分口径识别与最小变更申请

### 9.1 现状结论
| 项 | 现状 | 结论 |
| --- | --- | --- |
| 输入模式（文本/语音）字段 | **无**。`sessions.mode` 是受众模式（毕业生/新生），当前硬编码 `"毕业生"` `[已验证]`，与文本/语音无关 | 缺失 |
| 评分版本字段 | **无**。`reports` 仅存评分结果 JSON `[已验证]` | 缺失 |
| 有效维度集合 | 可由 `dimensions_json` 中 score 非 null 的键推导 `[已验证]` | **不需要新字段** |

### 9.2 为什么不能靠现有字段可靠推断
- **输入模式**：唯一"指纹"是文本模式把 `answers.duration_s/wpm/pause_cnt` 落 NULL。但 `duration_s`/`pause_cnt` 是客户端随音频提交的（AGENTS §8 音频契约），客户端漏报、M2 端点行为调整、或未来混合端点都会使该指纹失效；且 §8.1 已禁止用打字耗时等替代语音时长——用可空客户端字段反推口径属于脆弱隐式契约，评分口径比较必须建立在服务端写入的显式事实上。
- **评分版本**：提示词、双评均值、证据校验规则的变化在存储的 `dimensions_json` 中**不留任何痕迹**，原理上不可推断。一旦 T3 后算法再修订（Gemini 正在并行修改评分），新旧报告将被画进同一条趋势线，产生跨口径的虚假增减——正是 §10.2 禁止的场景。

### 9.3 最小变更申请（只申请，不实施）
| # | 变更 | 内容 |
| --- | --- | --- |
| 1 | `sessions` 加列 `input_mode VARCHAR(16) NULL` | 取值 `text/voice`，由服务端在首次答题时按所命中端点写入（text 端点→text，M2 音频端点→voice）；仅服务端可写 |
| 2 | `reports` 加列 `scoring_version VARCHAR(16) NULL` | `server/services/scoring.py` 增常量 `SCORING_VERSION="v1"`，生成报告时写入；后续算法修订必须递增 |
| 3 | 迁移方式 | 扩展 `server/db.py::ensure_schema_upgrades()` 现有 `PRAGMA table_info + ALTER TABLE ADD COLUMN` 机制 `[已验证模式存在]`，覆盖 sessions 与 reports 两表；不引入 Alembic |
| 4 | 存量兼容 | 查询时 `COALESCE(input_mode,'text')`、`COALESCE(scoring_version,'v1')`。依据：截至本规格日仓库只存在文本提交端点 `[已验证]`，且评分算法自 T3-A（d8037c2）后未再变更 `[以 Gemini 并行修复合入结果为准，合入若有评分行为变更需重估]`；T7-G1 合入后所有新行显式赋值，NULL 语义仅覆盖存量 |

涉及文件（= §12 批准项 4/5）：`server/models.py`、`server/db.py`、`server/services/scoring.py`、`server/api/sessions.py`。

---

## 10. T7-G1 实施边界建议（不默认扩界，逐项待批）

| 文件 | 动作 | 内容 |
| --- | --- | --- |
| `server/services/growth.py` | 新增 | §4.5 合格记录查询 + 可比性判定 + trend/history 组装；纯 DB 查询，零 LLM |
| `server/api/growth.py` | 新增 | `GET /api/students`、`GET /api/growth/{user_id}/history`、`GET /api/growth/{user_id}/trend` 三路由 |
| `server/schemas.py` | 修改 | +`StudentItem/StudentListResponse/GrowthHistoryResponse/GrowthTrendResponse` 等；`SessionCreateRequest` 增 `user_id: int = Field(..., ge=1)` |
| `server/main.py` | 修改 | 挂载 growth router |
| `server/api/sessions.py` | 修改 `[扩界申请]` | 身份绑定（§4.2）、删除自动建 id=1 用户、首次答题写 `input_mode` |
| `server/models.py` | 修改 `[扩界申请]` | +`Session.input_mode`、`+Report.scoring_version` |
| `server/db.py` | 修改 `[扩界申请]` | `ensure_schema_upgrades()` 扩展两列迁移 |
| `server/services/scoring.py` | 修改 `[扩界申请]` | +`SCORING_VERSION="v1"` 常量并在结果 dict 返回 |
| `scripts/import_seeds.py` | 修改 `[扩界申请]` | 幂等 upsert ≥2 名演示学生档案（id 固定，重跑不重建） |
| `tests/test_growth.py` | 新增 | §11 验收矩阵全部用例；先写 happy-path 再实现 |
| `web/app/page.tsx` | 修改 | 学生档案选择器（§3.1），创建会话携带 `user_id` |
| `web/app/growth/page.tsx` | 新增 | 岗位筛选、历史列表、echarts 折线（`connectNulls:false`）、"本次比上次"卡片、空状态、原报告/再次训练入口 |
| `web/app/reports/[sid]/page.tsx` | 修改 | 增"查看成长记录"入口（§9 前端要求） |

- 依赖：T3-B 验收通过（报告页与首页存在）；不新增任何第三方依赖，图表复用 echarts。
- 说明：当前 T7-G0 起点分支尚无 `web/` 目录（T3-B 在 `feature/T3-ui-bootstrap` worktree 并行开发 `[已验证]`），上表前端条目是对 T3-B 产物的增量要求，T7-G1 须基于 T3-B 合入后的代码施工。
- 编码注意：`webm/opus` 与语音相关逻辑一律不碰；不做泛化重构（AGENTS §11.3）。

---

## 11. 自动化验收矩阵（T7-G1 的 tests/test_growth.py 最小集合）

| # | 用例 | 构造 | 断言 |
| --- | --- | --- | --- |
| A1 | 两学生隔离 | 学生3、4 各在岗位1完成 ≥1 次真实流程 | `GET /growth/3/history` 无学生4的 session；trend points 互不混入（§7 四条断言） |
| A2 | 两岗位隔离 | 学生3 在岗位1、2 各一次 | `trend?job_id=1` 的 `sessions_count=1`，不含岗位2分数；`history` 不带 job_id 时两条都在 |
| A3 | 同人同岗三次 | 学生3 岗位1 连续 3 次真实流程 | history 3 条按 `(started_at,id)` 升序；trend 3 点；`overall_comparison.delta` = 第3次−第2次（1位小数） |
| A4 | 零次记录 | 全新学生档案 | trend `200`、`points=[]`、`reasons=["NO_RECORDS"]`；history `records=[]` |
| A5 | 仅一次记录 | 学生3 岗位2 仅 1 次 | `reasons=["SINGLE_RECORD"]`、`delta=null`、`dimension_changes` 全 null |
| A6 | 缺失维度 | 中间报告某维 score=null（夹具直写 reports） | 该维序列含 null 且接口原样返回 null；`dimension_changes[dim]=null`；无补零字段 |
| A7 | 文本/语音不可比 | 两报告 input_mode 分别 text/voice（M2 前用夹具直写 `sessions.input_mode`；夹具与实测数据可区分） | `reasons` 含 `INPUT_MODE_MISMATCH`、`delta=null`；`input_mode="mixed"` |
| A8 | 评分版本不可比 | 两报告 scoring_version v1/v2（夹具） | `reasons` 含 `SCORING_VERSION_MISMATCH`、`delta=null` |
| A9 | 有效维度集不同 | 前后两次报告非 null 维度集合不同（夹具） | `reasons` 含 `DIMENSION_SET_MISMATCH`、`delta=null` |
| A10 | 企业同源 | 两学生同岗训练后查 `GET /api/recruiter/candidates?job_id=1`（T8 实现后） | 每生一条；`session_id/report_id/overall` 与库内报告一致 |
| A11 | 再训练不重复候选人 | A10 后学生3 再完成一次 | 候选仍 2 条；学生3 条目指向最新合格 `session_id/report_id` |
| A12 | 缺维不零分处罚 | 候选报告某维 null | 加权计算不含该维 0 分（具体公式随 T8 定稿 `[待T8审批]`） |
| A13 | 非法身份 | `user_id=999` / recruiter 用户 | 404 `USER_NOT_FOUND` |
| A14 | 缺失 user_id 建会话 | POST /api/sessions 缺 user_id | 422（FastAPI 格式）；不再自动创建 id=1 用户（断言 users 表无新增） |
| A15 | 只统计完成会话 | 存在 active/answering 会话与无报告 completed 会话 | 均不出现在 history/trend |
| A16 | 零 LLM 调用 | 调用三接口前后对比 usage 日志计数 | 计数不变（成长查询不新增任何模型调用） |

> A7/A8/A9 在 M2 前只能以测试夹具直写字段构造，夹具数据严禁进入演示库或 M4 实测导出（AGENTS §10.2"测试夹具与真实参与者实测数据明确区分"）。

---

## 12. 需要队长批准的变更清单

| # | 变更 | 类型 | 建议 | 理由 |
| --- | --- | --- | --- | --- |
| 1 | `POST /api/sessions` 请求体增必填 `user_id`，并删除 id=1 自动建档逻辑 | API 破坏性变更 | **建议批准** | §10.2 明令禁止全员绑默认用户；这是身份归属的唯一入口。前端 T3-B 页面需同步传参 |
| 2 | 新增 `GET /api/students` | 新 API | **建议批准** | 档案选择的数据源；只读、无鉴权面扩大 |
| 3 | 新增 `GET /api/growth/{user_id}/history`、`GET /api/growth/{user_id}/trend` | 新 API | **建议批准** | §10.2 T7-G1 验收的直接依赖；只读纯查询 |
| 4 | `sessions.input_mode`、`reports.scoring_version` 两列（可空 VARCHAR） | 数据模型加列 | **建议批准** | 符合 §7"字段可增不可减"；不建新表；是可比性判定的契约基础。不可比风险若不解决，成长趋势会跨口径造假 |
| 5 | T7-G1 文件边界扩展：`server/api/sessions.py`、`server/models.py`、`server/db.py`、`server/services/scoring.py`、`scripts/import_seeds.py` | 文件扩界 | **建议批准** | 均为最小 diff（见 §10）；models/db/scoring 是字段落地的必经文件；演示学生档案需幂等预置，否则无合法身份可用 |
| 6 | 成长专用汇总表 / 候选人表 | 数据模型新表 | **不建议批准** | 一切可由 sessions+reports 推导；建表即制造双份事实，违背"默认不新建 growth 表" |
| 7 | 成长页调用 LLM 生成总结/解读 | 功能 | **不建议批准** | §10.2 明确禁止新增 LLM 调用；历史建议直接读原报告 |
| 8 | 注册/登录/密码等认证机制 | 功能 | **不建议批准** | 局域网演示场景已批准用档案选择；认证是超范围扩张 |
| 9 | 新第三方依赖（图表库以外的） | 依赖 | **不建议批准** | echarts 已覆盖折线/雷达；AGENTS §11.3 禁令 |

---

## 附：本文未解决事项
1. §9.3 兼容性依据依赖"评分算法自 d8037c2 后未变"——Gemini 并行修复 T3-A 若触及评分输出结构，`SCORING_VERSION="v1"` 的基线需按其合入结果重估。
2. `[待T8审批]`：企业端维度权重、缺维候选资格、文本/语音是否分列展示。
3. `[未验证]`：线上库存量数据内容、`started_at` 最终序列化格式、`ensure_schema_upgrades()` 扩展后的实际执行（T7-G1 测试覆盖）。
