# AGENTS.md —— 「智驾未来·AI面试仓」开发契约（v1.0）

> 本文件是全项目唯一事实来源（Single Source of Truth）。任何任务开始前先通读本文；
> 本文与你的直觉冲突时，以本文为准；本文有遗漏时，先提问再动手，禁止自行扩大范围。

## 1. 项目背景（为什么做）
- 中国·上海第九届青少年AI创新大赛"AI+匠心智造"职教赛道·企业命题05「智能面试仓的开发与应用」。
- 交付物（全部材料的 deadline）：项目报告书PDF（10章）、核心代码PDF、演示视频MP4≤500M、PPT PDF、项目概况表PDF。
- 作品提交截止 **2026-10-15**；**功能冻结日 2026-10-05**，此后只修 bug。
- 评审五维度：技术可行性 / 功能完整性 / 创新亮点 / 落地价值 / 展示效果。所有取舍以此为准绳。

## 2. 产品定义（做什么）
面向智能汽车产业的**岗位定向型 AI 面试平台**，三端闭环：
- **学生端（P0）**：选岗位 → 语音模拟面试（TTS提问+ASR转写）→ 多维可解释评分报告。
- **新生端（P1）**：输入专业/年级/兴趣 → 输出智能汽车产业链岗位地图、能力差距、分年级学习路径。
- **企业端（P1）**：粘贴JD → 自动生成评估维度+题库 → 候选人雷达图与加权排序初筛。
- 差异化护城河（报告书创新点，代码必须真实支撑）：①车企垂直题库（智驾测试/三电两个种子岗位）②表达层声学特征量化（语速/停顿/填充词进入评分）③评分带 evidence 原文引用的可解释性。

## 3. 范围控制（不做什么——违反即事故）
数字人形象、视觉/表情分析、模型微调、向量数据库、移动端、公网部署、真实企业对接、多岗位铺量（只做2个种子岗位做深）。ER 图里的每张表都要有对应功能，禁止"以后可能用到"的字段。

## 4. 技术栈（锁定，换型需人工确认）
- 前端：Next.js + TypeScript + Tailwind；图表 echarts（雷达图/折线图）。
- 后端：Python FastAPI + SQLAlchemy + SQLite（ORM 写法须兼容未来换 Postgres）。
- LLM：OpenAI 兼容客户端，全部经 `server/services/llm.py` 单点封装，模型名/KEY/BASE_URL 全部走 `.env`。
- ASR：FunASR(Paraformer) 本地批处理为主，讯飞WS为备；TTS：edge-tts。
- 音频转换：ffmpeg（webm/opus → 16k mono wav），Dockerfile 必须安装。
- 部署形态：本机/局域网运行即可，不要求上云。

## 5. 模型策略（延迟与质量分工）
```
编排/追问/新生模式：本地 Qwen3-30B-A3B(Ollama, OpenAI兼容端点) 为主，
                    超时或不可用 → 云端 flash 档(DashScope qwen-flash)兜底
评分/JD解析：       云端旗舰档为主 → 本地MoE兜底（质量优先，允许慢）
```
- `llm.chat_json()` 必须实现：timeout（编排类6s）、fallback 模型链、pydantic 校验失败自动重试1次、每次调用记录 {stage, model, ttft_ms, total_tokens} 到 usage 日志。
- **所有降级必须静默可用**：追问判定失败=直接下一题；评分本地兜底成功=正常出报告。任何 LLM 故障都不允许 500 给前端。

## 6. 核心实现规约（照做，不要发挥）
1. **会话状态机** `server/services/orchestrator.py`：服务端驱动，状态落库可断点续跑；题目结构=固定2+专业3+情景1；追问每题最多1次（查 answers 表计数），追问判定提示词必须包含否定约束（禁止评价回答好坏/重复原问题/超过一句话）。
2. **TTS预取**：`start()` 时 asyncio.gather 并行合成全部固定题音频，面试中播放零等待；预取失败不阻塞 start。预生成3-5条通用过渡语（"嗯，我了解了"等），学生提交回答后立即播放，用于掩盖3-5s处理延迟。
3. **语音链路**：前端 MediaRecorder(webm) + AnalyserNode 统计 duration_s/pause_cnt（<-45dB 持续>1.5s计1次）；后端 ffmpeg 转码 → ASR；填充词（嗯|那个|就是|然后|这个）由后端正则计数；语速=字数/时长。禁止依赖ASR词级时间戳。
4. **评分引擎** `server/services/scoring.py`：四维=专业匹配度/逻辑结构/表达流畅度/岗位素养，每维 {score, evidence(引用原话≤25字), reason}；表达流畅度必须消费声学特征量化值（语速基准220-280字/分）；两次独立调用取均值；缺失维度置 null 禁止虚构；输出经 pydantic 校验。
5. **知识注入**：单岗位术语表+JD要点全文进 prompt（当前规模不用检索）；新生端岗位地图可静态数据+LLM组织，不做RAG基建。
6. **LLM调用记账**：所有调用必须过 usage 日志，报表页不需要展示，但日志要能算出"单场面试平均token与成本"。

## 7. 数据模型（建表以此为准，字段可增不可减）
users(id, role[student/recruiter/admin], name_masked, major, grade)
jobs(id, family, title, jd_digest, terms_json, dims_json)
questions(id, job_id, type[通用/专业/情景], text, followup_hint)
sessions(id, user_id, job_id, mode[毕业生/新生], started_at, status)
answers(id, session_id, q_seq, question_text, answer_text, is_followup, is_retry, duration_s, wpm, pause_cnt, filler_cnt)
reports(id, session_id, dimensions_json, highlights_json, concerns_json, improvement_json, overall)

## 8. API 契约（前后端按此并行，改动需人工批准）
POST /api/sessions                {job_id}                        → {sid, question:{text,audio_url,seq}}
POST /api/sessions/{sid}/answers  (audio, duration_s, pause_cnt)  → {type: followup|next|done, question?|report_id?}
GET  /api/reports/{sid}                                           → 评分报告JSON
POST /api/jobs/parse              {jd_text}                       → {dims[≤5], questions[8-11], terms}
GET  /api/recruiter/candidates?job_id                             → 加权排序+雷达图数据
POST /api/counsel                 {major,grade,interests}         → 岗位地图/差距/路径JSON

### 8.1 M1 补充契约 v0.1（队长于 2026-09-21 批准）

本节为已批准的契约补充，优先用于 M1 文本模式。原音频提交接口保留。
统一约定：ID 为正整数；JSON 使用下划线字段名；主问题 seq 为 1–6，追问沿用原题 seq。

| 接口 | 请求 | 成功响应 |
| --- | --- | --- |
| GET /api/jobs | 无参数 | 200，{"jobs":[{"id":1,"family":"智驾","title":"智驾测试","jd_digest":"…"}]} |
| GET /api/jobs/{job_id}/questions | 岗位 ID | 200，{"job_id":1,"questions":[{"id":1,"type":"通用","text":"…"}]} |
| POST /api/sessions/{sid}/answers/text | application/json，{"answer_text":"回答正文"} | 200，见下述联合类型 |

- 岗位、题目列表按 id 升序；列表为空返回 200；岗位不存在返回 404。
- 题目查询用于 T2 验收；面试下一题由服务端决定。
- answer_text 去除首尾空白后长度为 1–5000 字符；拒绝额外字段。
- 客户端不提交题目、题号、追问标记或声学值；服务端绑定当前待答题。
- 文本提交成功响应严格为以下三种之一：
  - {"type":"followup","question":{"text":"…","audio_url":null,"seq":1}}
  - {"type":"next","question":{"text":"…","audio_url":null,"seq":2}}
  - {"type":"done","report_id":1}
- question.audio_url 类型为 string | null，创建会话响应同样适用；M1 mock 返回 null，前端跳过播放。
- 报告仍通过 GET /api/reports/{sid} 获取，sid 与 report_id 不得混用。

文本数据与评分：
- 保存规范化 answer_text；duration_s、wpm、pause_cnt 为 null，不得用打字耗时替代语音时长。
- filler_cnt 按既定正则统计，但不得据此虚构语音流畅度。
- 文本模式的表达流畅度为 null；其余维度继续执行两次独立评分及原文证据校验。
- overall 为有效维度等权均值，保留一位小数；全部缺失则为 null。
- 页面标注“文本模式，未评估语音流畅度”；缺失维度显示“未评估”，不能画成零分。
- 实施前核对 T1 模型空值兼容性；若不兼容，报告差异，禁止自行修改数据模型。

错误与重试：
- 404：JOB_NOT_FOUND、SESSION_NOT_FOUND。
- 409：SESSION_COMPLETED、ANSWER_IN_PROGRESS；不得重复推进。
- 422：字段或长度非法，沿用 FastAPI 校验错误格式。
- 503：SCORING_UNAVAILABLE，评分主备链均失败；本次最终回答与状态推进一并回滚，页面保留文本供重试。
- 业务错误结构为 {"detail":{"code":"SESSION_COMPLETED","message":"面试已结束"}}，其他业务码替换 code 与对应说明。
- 追问失败直接下一题；usage 记录不随业务回滚丢失。
- 前端提交期间禁用按钮；网络结果不明时不自动重发。

## 9. 前端要求（展示效果是独立评分项，认真做）
- **虚拟面试舱 HMI 风格**：全屏深色座舱风（参考智能汽车HMI），系统蓝+橙强调色，卡片圆角发光描边。
- 面试进行页：中央=面试官波形动画+当前问题字幕逐字亮起；左侧=题目进度轨道（追问项橙色标记）；底部=ASR转写滚动条+麦克风电平环；右上=计时。
- 报告页：overall 大数字+环形进度、四维雷达图、evidence 高亮卡片、improvement 清单。此页是演示视频主画面，视觉优先级最高。
- 流程页：岗位选择 → 设备自检（录3s回放）→ 面试舱 → 报告页。进入面试舱加1.5s过场动画。
- 企业端：候选人列表+雷达图+排序；新生端：单页表单+结构化结果展示。

## 10. 里程碑（agent 按此交付，验收不过不算完成）
M1(9/23) 文本闭环：打字问答6题+追问1层+评分落库，报告页可看（ASR/TTS用mock接口隔离）。
M2(9/28) 语音闭环：真音频→转写→评分全链路；声学统计数值正确。
M3(10/5) 三端冻结：企业端+新生端+面试舱UI完成，**此后禁止新功能**。
M4(10/9) 实测数据导出脚本：能批量生成会话并导出时延/评分统计（供报告书）。

### 10.1 M1 页面前置与执行门禁（2026-09-21 批准）

- T3 内前置 M1 必需页面；T6/T7 的完整语音与视觉验收保留，里程碑日期不变。
- /：岗位选择 → 创建会话 → 当前题目及进度 → 文本提交 → 完成后跳转报告。
- /reports/[sid]：总体分、有效维度雷达图、证据与原因、改进清单，按 §8.1 处理缺失值。
- 验收：先写 happy-path 测试；自动化完成六题、一次追问、报告落库，并验证故障降级及空值语义；构建通过，浏览器可打开同场真实报告。
- 代码由 Codex/Sol 执行，指挥官负责文档与审查；先完成 T1，再 T2、T3-A、T3-B。人工题库准备可并行。
- 所有生产代码合入须有测试证据及明确通过的审查；禁止直接提交 main。

已批准的直接依赖清单：
- 后端新增：uvicorn（运行服务）、httpx（API 测试）；现有 requirements.txt 六项依赖范围保持。
- 前端运行：next、react、react-dom、echarts。
- 前端开发：typescript、@types/node、@types/react、@types/react-dom、tailwindcss、@tailwindcss/postcss、postcss。
- 使用原生 fetch；python-multipart 留到音频任务单单列。
- 精确版本兼容性尚未验证；安装前提交 Node/Python 版本、精确包版本及兼容性结果，前端生成锁文件。此次批准不代表版本验证已通过。
- 后端地址通过 .env 配置，附 .env.example，不在代码中硬编码。

执行任务票（预估为规划值，文件边界不得自行扩展）：

**[T2] 人工题库导入与查询**
- 指派：人工供题 + Codex/Sol；分支 feature/T2-seeds；依赖 T1 验收通过。
- 边界：data/jobs_seed.json、scripts/import_seeds.py、server/main.py、server/api/__init__.py、server/api/jobs.py、tests/test_seeds.py。
- 验收：两个岗位由人工供题；重复导入不重复建题；§8.1 两个查询接口通过自动化测试。
- 预估：2万–4万 token，执行 2–3 小时，人工题库 3–5 小时。

**[T3-A] 文本编排与评分落库**
- 指派：Codex/Sol；分支 feature/T3-text-loop；依赖 T2 验收通过。
- 边界：server/services/orchestrator.py、server/services/scoring.py、server/services/asr.py、server/services/tts.py、server/schemas.py、server/api/sessions.py、server/api/reports.py、server/main.py、tests/test_text_flow.py、tests/test_scoring.py、requirements.txt。
- 验收：§6 的题目结构、追问限制、状态恢复、评分与证据要求及 §8.1 错误/空值规则通过测试；ASR/TTS 仅 mock。
- 预估：8万–15万 token，执行 6–10 小时，人工验收 1 小时。

**[T3-B] M1 最小页面与验收证据**
- 指派：Codex/Sol；分支 feature/T3-m1-ui；依赖 T3-A 验收通过。
- 边界：web/package.json、web/package-lock.json、web/tsconfig.json、web/next-env.d.ts、web/postcss.config.mjs、web/next.config.ts、web/app/layout.tsx、web/app/globals.css、web/app/page.tsx、web/app/reports/[sid]/page.tsx、.env.example、memory/TESTING.md。
- 验收：本节页面要求与构建通过，30秒可核对报告维度、引用和改进项，完整流程另留测试记录。
- 预估：4万–8万 token，执行 4–6 小时，人工验收 0.5 小时；9/23 前验收，9/24 仅修复。

## 11. 工作纪律（对 agent 的硬性要求）
1. 每个任务只触碰任务单点名的文件；需要跨界改动先停下来说明理由等确认。
2. 先写 happy-path 测试再实现；每个任务完成必须 `git commit`（信息格式：`T{n}: 摘要`）。
3. 禁止引入新第三方依赖，除非任务单明确列出；禁止大爆炸式重构；改坏了用 git 回滚，不要"改回来"。
4. 所有配置进 `.env`（附 `.env.example`），代码里禁止硬编码 KEY/URL/模型名。
5. 每次回复末尾附：本次改动文件清单 + 未解决事项 + 下一步建议，不超过10行。

## 12. 任务单（按序执行）
T1 骨架：目录结构+config+db models+llm.py(含usage日志与fallback链) | 验收：pytest 一条真实chat_json通过
T2 jobs/questions 表+种子数据脚本（题库JSON由人工提供，agent只做导入）| 验收：API列出岗位题目
T3 orchestrator+scoring（ASR/TTS mock）| 验收：文本走完6题+追问+报告落库 = M1
T4 tts.py+预取+过渡语料播放 | 验收：start()返回时mp3齐全
T5 asr.py+ffmpeg转换链 | 验收：真实webm→文本 = M2
T6 前端面试播放器（录音/电平环/静音统计/字幕动画）| 验收：全语音流程可跑
T7 报告页（雷达图+evidence卡片）| 验收：视觉人工验收
T8 企业端（JD解析+看板）| 验收：JD→题库→排序闭环
T9 新生端 | 验收：输入背景出路径报告
T10 HMI美化pass+演示种子数据清洗 | 验收：全屏运行无debug痕迹
