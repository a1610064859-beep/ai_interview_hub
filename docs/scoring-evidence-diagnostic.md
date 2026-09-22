# T3-DIAG：sid=5 内容三维评分全空根因诊断

> 分支：`feature/T3-scoring-diagnostic`
> Worktree：`E:\ai_interview_hub_scoring_diag`
> 基线：`main` @ `5c5c3ca`
> 范围：只读诊断 + 本文档；**未改生产代码 / 测试 / 数据库 / 配置**。
> 禁止项遵守：未读 `*.log`、`.workbuddy/`、`.godot/`、usage 日志。

---

## 1. 结论摘要（先看）

| 维度 | 落库结果 | 已观测到的终点表现 |
| --- | --- | --- |
| `professional_match` | `score/evidence=null`，reason=`未获得通过校验的双次评分` | 双评均值要求两侧该维均非 `None`；当前落库为双侧缺失后的统一文案 |
| `logic_structure` | 同上 | 同上 |
| `job_competence` | 同上 | 同上 |
| `expression_fluency` | `91.3`（正常） | **不经 LLM evidence**；`compute_acoustic_fluency` 确定性路径 |

**与 ASR 字间空格的关系（审查口径）：**

- **已验证数据缺陷：** FunASR 落库的 12 条 `answer_text` **全部**呈汉字间空格（例：`超 声 波 雷 达…`）。
- **已验证规则冲突面：** `validate_evidence` 要求 evidence 为某一单条回答的**字面子串**（`evidence in ans`），**不**做空白归一化。将原文去汉字间空格后取连续 8 字片段，对 **原始** answers 做等价校验：**53/53 全部失败**；对去空格后的 answers：**全部通过**。保留字间空格的字面片段（如 `超 声 波 雷 达`）对原始 answers **可通过**。
- **高概率主因（非逐次钉死）：** ASR 字间空格是三维全空的高概率主因——常见无空格中文 evidence 与现有数据形态存在系统性冲突，足以在「单次评分校验 / 修正重试后置 None / 双评均值」链路中导致三维为空。
- **仍未验证：** 每次 LLM 调用的具体失效点（缺维 / evidence 为空 / 超长 / 首尾空格 / 字间空格不匹配 / 单侧异常等）。原始 LLM JSON **未持久化**，不得写成「三维已确认在 `validate_evidence` 处失效」。

**排除项（已验证）：** 模型不可用（HTTP 200、报告已生成、流畅度正常）；答案为空或过短。

---

## 2. 代码路径梳理（失效漏斗）

### 2.1 数据进入评分

语音收尾（`server/api/sessions.py`）：

1. FunASR `transcribe_wav` 原样返回 `text`（`server/services/asr.py`：**无**去字间空格）。
2. `all_answers = [a.answer_text …]` 直接交给 `score_interview(..., mode="voice", acoustic_samples=…)`。
3. 声学流畅度走 `compute_acoustic_fluency`（与 evidence 无关）→ sid=5 得 `91.3`。
4. 内容三维走两次并行 `call_scoring_llm` → `calculate_dimension_average`。

对比：`_compute_wpm` 已用 `"".join(answer_text.split())` 去空白计字，说明**工程上已知 ASR 带空白**，但评分 evidence 链路未对齐。

### 2.2 单次评分可能失效路径（`call_scoring_llm`）

下列路径均可导致某维最终为 `None`；**sid=5 每次调用走了哪一条仍 [未验证]**：

| 步骤 | 条件 | 结果 |
| --- | --- | --- |
| LLM 缺维 | 字段为 `null`/缺省 → `Optional` 为 `None` | **不进** `invalid_dims`；**不触发**修正重试；维保持 `None` |
| evidence 空 / 非 str / strip 后空 | `validate_evidence` False | 进修正；重试后仍失败 → 置 `None` |
| evidence 长度 ∉ [1,25] | False（注：>25 更可能在 pydantic `max_length=25` 整包校验失败） | 见下 |
| evidence 首尾空格导致非子串 | False（单测 `test_evidence_validation_exact_string_spaces`） | 修正后仍失败 → `None` |
| ASR 字间空格：无空格中文 ≠ 有空格原文 | False（§3.2 用 sid=5 复现冲突面） | 修正后仍失败 → `None` |
| 第一次无效 → 追加修正 user 消息再调一次 | 仍无效 | 该维置 `None`，保留其他已合规维 |
| pydantic 整包失败 | `chat_json` 同模型再试 1 次 / 换链 | 两侧皆抛 → 503；sid=5 **已出报告** → 至少一侧未整包失败 |

### 2.3 双评均值（三维共同终点表现）

`calculate_dimension_average(d1, d2)`：

- 任一侧该维为 `None` → `(None, None, "未获得通过校验的双次评分")`。
- **禁止**用单侧有效分冒充双评（与任务约束一致；当前实现亦如此）。

因此 UI 上三维 reason 文案相同，**不能**从文案区分「双侧 evidence 失败」与「一侧调用异常 / 缺维」——需原始响应才能区分，[未验证]。

### 2.4 Schema 约束（`SingleDimensionScore`）

- `evidence: str`，`min_length=1`，`max_length=25`。
- 超长 evidence 在进入 `validate_evidence` 前即可导致 `ValidationError`（usage/原始 body 未读，[未验证] sid=5 是否触发过）。

---

## 3. sid=5 数据审计摘要（只读 SQLite：`data/interview.db`）

| 项 | 值 |
| --- | --- |
| session | id=5，user_id=1，job_id=1，status=`completed`，mode=毕业生 |
| answers | **12** 条（主问 6 + 追问 6），id=15..26 |
| report | id=2，`overall=91.3`（仅流畅度计入等权均值） |
| 空回答 | **0** |
| `len(strip)<8` | **0** |
| 含「汉字 汉字」字间空格 | **12/12** |
| 内容三维 | 全部 `score=null`，reason=`未获得通过校验的双次评分` |
| 流畅度 | `91.3`，reason 含「共12条有效语音回答」 |
| 列表字段 | `highlights/concerns/improvement` 非空（例：highlights 提及 CANoe 等） |

**样本保全：** sid=5 **保留为真实缺陷样本**；不重跑评分、不改写 answers/reports。修复后用**新会话**验证；是否回刷历史数据另议，且不得以篡改已验收报告为前提。

### 3.1 回答形态样例（原文）

| id | seq | followup | spaces | 原文开头 |
| --- | --- | --- | --- | --- |
| 15 | 1 | N | 23 | `超 声 波 雷 达 档 位 车 速 …` |
| 16 | 1 | Y | 79 | `先 要 明 确 制 驾 系 统 的 通 信 拓 扑 …` |
| 18 | 2 | Y | 108 | `对 channel 总 线 进 行 通 信 和 测 试 …场 景 回 放…` |
| 26 | 6 | Y | 15 | 含 `method request response event` 等拉丁片段 |

### 3.2 子串规则可复现实验（内联等价于 `validate_evidence`，未改库）

探针（对 12 条原始 answers）：

| evidence | vs 原始 | vs 去汉字间空格后 answers |
| --- | --- | --- |
| `场景回放` | **False** | **True** |
| `超声波雷达档位车`（去空格片段） | **False** | **True** |
| `超 声 波 雷 达`（保留空格字面） | **True** | — |
| `ECU` / `channel` / `method request` | **True**（原文含拉丁词） | True |
| `CANoe` | False | False（**原文未出现** CANoe） |

补充：**highlights 中的「CANoe」并非 answer 子串** → 模型在非 evidence 字段可按 JD/术语表组织语言；evidence 则必须字面命中。这与「评分 HTTP 200 但仍三维空」兼容。

去空格中文 8 字窗口 vs 原始 answers：**失败率 53/53**。

本实验证明的是**数据形态与字面规则的系统性冲突面**，不是对 sid=5 各次 LLM 原始 evidence 的还原。

---

## 4. 三维与失效步骤的表述边界

三者共用同一套 LLM 内容维 + 同一套 `validate_evidence` + 同一套双评均值，**没有维间特殊分支**。

| 维度 | 可陈述内容 | 不可陈述内容 |
| --- | --- | --- |
| `professional_match` | 落库为双评失败文案；ASR 字间空格是高概率主因之一 | 「已确认在 `validate_evidence` 失败」 |
| `logic_structure` | 同上 | 同上 |
| `job_competence` | 同上 | 同上 |

次级可能（概率较低，[未验证]）：某次整侧异常使 `res1`/`res2` 为 `None`，则三维在均值步骤一并清空——但仍与「至少一侧产出 highlights」相容。

**不是：** 答案为空/过短；流畅度链路故障；「模型完全不可用」(503)。

---

## 5. 根因按概率排序

### P1 — 已验证数据缺陷 + 已验证冲突面（最高）

**FunASR 汉字间空格落库 ∩ 严格字面子串 evidence 校验 → 无空格中文 evidence 系统性无法命中原文。**

- 证据：§3 审计 + §3.2 纯函数复现；`asr.py` 无归一化；`validate_evidence` 字面 `in`。
- 定位：这是**已验证的数据缺陷与规则冲突面**，也是三维全空的**高概率主因**。
- 边界：不能据此断言 sid=5 每一次调用都死在 `validate_evidence`；缺维、整侧异常等路径仍 [未验证]。

### P2 — 高概率推断（依赖未持久化的原始 JSON）

两侧独立 `call_scoring_llm`（各最多 1 次修正）对三维均未能留下合规 `SingleDimensionScore`，故均值全空。

- 不能排除「一侧异常 + 另一侧 evidence 全灭」的组合，[未验证]。

### P3 — 可能但证据较弱

- LLM 直接缺维（`null`）：不触发修正；若双侧皆缺维，现象相同。[未验证]
- evidence 超 25 字导致 pydantic 失败后整次重试/换模：若最终仍返回带 highlights 的对象，则最终成功包内维仍可能缺/无效。[未验证]
- 首尾空格 evidence：单测覆盖该规则；sid=5 无原始 evidence，[未验证]

### 已排除（已验证否定）

- 12 条回答为空或过短。
- 「仅因 Next ECONNRESET」：报告与流畅度已落库。
- 「放宽校验才能解释」：无需放宽即可用现有规则解释失败面；失败是规则按设计工作的结果。

---

## 6. 最小修复候选（仅建议，本任务不实施）

约束回顾：**禁止**放宽 evidence 语义（改成模糊匹配/去空格比对冒充字面）、**禁止**补零、**禁止**单评冒充双评。

### 候选 A（推荐）：ASR 落库前仅折叠 CJK 间空白

- **做法：** 在 `transcribe_wav` 返回后或 sessions 写入前，**仅折叠 CJK 字符之间的空白**；**保留**英文词、数字、英文术语之间的空格（例：`使 用 CANoe 进 行 总 线 测 试` → `使用 CANoe 进行总线测试`）。`validate_evidence` 与双评规则**保持不变**。
- **理由：** 与 `_compute_wpm` / 填充词正则对「无空格中文」的隐含假设对齐；不改变双评与 evidence 严格性。
- **测试要求：** 必须补充混合文本用例，至少覆盖 `使 用 CANoe 进 行 总 线 测 试`；并先用**新会话**验证内容三维恢复，再决定是否处理历史数据。
- **文件边界（待任务票批准）：**
  - `server/services/asr.py`（归一化纯函数 + `transcribe_wav` 出口）
  - `tests/test_asr.py` 或新建定向单测（CJK 间空格折叠；英文/数字空格保留；混合文本）
  - 可选：`server/api/sessions.py` 仅当归一化放在 API 层时
  - **不改** `validate_evidence` 成功判据；**不改** `calculate_dimension_average` 双评要求
- **历史数据：** **不改写 sid=5**；其作为真实缺陷样本保留。历史回刷另票评估，且不得破坏已验收报告证据链。

### 候选 B：评分输入侧使用「展示用原文」的归一化副本

- 落库保留 raw ASR；`score_interview` 入参 answers 使用归一化副本；evidence 必须命中**归一化副本**（报告展示亦用副本）。
- 仍保持字面匹配，不放宽校验。
- **文件边界：** `server/api/sessions.py`、`server/services/scoring.py`（仅入参预处理）、测试；需产品确认「报告 evidence 对应哪一版正文」。

### 候选 C（不推荐作主修复）：强化 prompt 要求复制带空格片段

- 脆弱；与人类可读报告冲突（evidence 变成 `场 景 回 放`）。
- 不解决拉丁/中文混排与模型稳定性。

### 明确排除的「假修复」

- 放宽 `validate_evidence`（去空格后再 `in`）——任务禁止。
- 单侧有效即出分——单评冒充双评，禁止。
- 缺维补 0——禁止。

---

## 7. 验证方法说明（可复现、临时文件不入库）

1. 只读查询 `answers`/`reports` where `session_id=5`。
2. 内联复制 `validate_evidence` 逻辑（避免本机缺 pydantic 时 import 失败），对 sid=5 原文做探针与窗口统计。
3. 临时产物：`_tmp_sid5_audit.json`（worktree 本地，**不提交**）。
4. **未**读取 usage / `*.log`；原始 LLM 评分 JSON：**现有系统未持久化，[未验证]**。

---

## 8. 分类清单（交付要求）

### 已验证

- sid=5 内容三维 reason 为双评失败文案；流畅度 91.3。
- 12/12 回答含汉字间空格；无空/过短。
- 无空格中文片段相对原始 ASR 文本，在现行字面规则下系统性无法命中（53/53）；保留空格字面可通过。
- ASR 出口不归一化；WPM 已去空白。
- 至少一次评分结构化成功（非空 highlights 等）→ 非模型不可用。

### 高概率推断

- ASR 字间空格是三维全空的高概率主因（常见无空格中文 evidence 与数据形态冲突 → 维无法形成双评有效对）。

### 未验证项

- 各次 LLM 原始评分 JSON 与具体 evidence 字符串。
- 每次调用的具体失效点（`validate_evidence` / 缺维 / 异常 / pydantic 等）。
- 双侧是否均完成、是否有一侧异常。
- 缺维 vs evidence 失败的精确比例。
- pydantic `max_length` 是否在 sid=5 触发过。

---

## 9. 下一步建议（非本票施工）

1. 单独申请 ASR 输出规范化施工票（候选 A）：仅折叠 CJK 间空白；保留英文/数字空格；补充混合文本测试；**新会话**验收内容三维。
2. 可选：评分阶段落库「脱敏后的 evidence 校验结果摘要」（非 raw log），便于下次免读 usage 定位。
3. sid=5 继续作为缺陷样本保留；历史数据是否回刷在新会话验收通过后再议。
