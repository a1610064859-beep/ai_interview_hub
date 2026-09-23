# 测试记录

记录真实验证方式、结果和未验证项。

## T3-B2 文本问答推进与报告跳转

范围：岗位选择 → 创建会话 → 文本回答推进（含最多 1 层追问）→ `done` 跳转 `/reports/{sid}`（mock 进入演示完成态）。报告页本身不在本任务验收。

### Happy-path

1. mock 完整 6 题 + 固定 1 次追问 → 演示完成态，全程显示“演示模式·非正式数据”
2. real 模式可创建会话并展示首题
3. 文本提交响应三态：`followup` / `next` / `done`
4. `done` 跳转使用会话 `sid`，不得把 `report_id` 当作路由参数
5. 双击/连点提交只发出一次 POST
6. 成功进入下一题后清空上一题文本

### 异常与边界

7. 空回答、超长（去空白后 >5000）前端拦截并提示，不发请求
8. HTTP 404/409/422/503 展示 `detail.code/message`（业务错误码可见）
9. 503 `SCORING_UNAVAILABLE`：保留 textarea 原文，解除提交锁，允许人工重试；不自动重发
10. 409 `ANSWER_IN_PROGRESS`：保留原文，`hold=true` 锁页，提示刷新确认，不释放 `submitLock`，不自动重发
11. 网络结果不明 / HTTP 200 但响应非法：保留原文，锁页，提示刷新确认，绝不自动重发
12. `audio_url=null` 不渲染播放器；`transition_audio_url` 可忽略播放，不误判响应非法
13. 桌面 1080p 与窄屏 360px 无横向溢出

### 执行结果

| 项 | 状态 | 说明 |
| --- | --- | --- |
| mock 6 题 + 1 次追问 | 通过 | Edge headless CDP：选岗 → 答完第2题出现追问 → 追问后第3题 → 至第6题 →「演示完成」且仍显示演示模式 |
| real 创建会话 | [未验证] | 本轮未启动后端 |
| followup / next / done 三态 | 部分 | mock 验证 followup/next/演示完成态；real `done`→`/reports/{sid}` 未浏览器验证 |
| report_id 与 sid 不混用 | 部分 | 代码：`router.push(\`/reports/${view.sid}\`)`；mock 完成态不伪造 report 路由 |
| 双击只发一次 | 通过 | 第1题连点两次提交后仅到「第2题 / 共6题」，未跳到第3题 |
| 503 保留输入可人工重试 | [未验证] | 逻辑保留；本轮未注入 503 |
| 409 ANSWER_IN_PROGRESS 锁页 | 代码修复 | 与网络未知相同：`hold=true`，不释放 `submitLock`；未联调注入 |
| 非法 200 锁页 | 代码修复 | `invalid` 分支 `hold=true` 并提示刷新；未联调注入 |
| 网络未知不重发 | [未验证] | `hold=true` 逻辑保留 |
| audio_url=null 无播放器 | [未验证] | mock 题 `audioUrl=null`，CDP 流程未见播放器控件需求 |
| 业务错误码可见 | [未验证] | 复用 `detail.code/message` |
| 360px / 1080p 无横向溢出 | [未验证] | 未改视口目视 |
| `npm run typecheck` | 通过 | 退出码 0（修复后） |
| `npm run build` | 通过 | 退出码 0（修复后） |

### 临时服务清理（复审轮）

- Next：`npx next start -p 34722`，监听 PID `47740`；已 `taskkill /T /F`，复查无 LISTENING
- Edge CDP：远程调试口 `9230`，监听 PID `46604`；已结束进程树，复查无 LISTENING
- 未保留其他 Next/dev/stub 进程

## M1 真实浏览器闭环验收

范围：Next `NEXT_PUBLIC_API_MODE=real` + FastAPI 真后端；Edge headless CDP 驱动：选岗 → 文本 6 题 → 至少 1 次追问 → `done` 跳转 `/reports/{sid}` → 核验报告页。评分走真实 LLM 双评；会话创建时关闭 TTS 预取以降低等待，不影响文本编排与评分。

### 执行结果

| 项 | 状态 | 说明 |
| --- | --- | --- |
| real 创建会话 | 通过 | 岗位「三电系统测试」；页面显示「后端联调」「会话 2」 |
| 6 题 + 至少一次追问 | 通过 | 第1题短答触发追问；后续主问题亦有追问（每题最多1层，符合编排）；共 12 次提交后完成 |
| `done` → `/reports/{sid}` | 通过 | 浏览器导航至 `http://127.0.0.1:34723/reports/2`（路径参数为 sid，非 report_id） |
| 真实 sid | **2** | API `GET /api/reports/2` 同步 200；报告编号 #1 |
| 总体分 | 通过 | overall=**67.5**（及格） |
| 三项有效维度 | 通过 | 专业匹配度 65.0 / 逻辑结构 72.5 / 岗位素养 65.0 |
| 流畅度未评估 | 通过 | score=null，reason=「文本模式，未评估语音流畅度」；页面「未评估」+ 文本模式徽标「文本模式仅绘制 3 项有效维度」 |
| evidence | 通过 | 如「使用CANoe分析报文」「我会说明测试输入、观察点」「坚持功能安全底线」 |
| 改进建议 | 通过 | 4 条 improvement 均展示于「针对性能力提升路线」 |
| `npm run build`（real） | 通过 | `BUILD_EXIT=0` |
| 端口清理 | 通过 | 验收后结束 uvicorn `:18080`、Next `:34723`、CDP `:9233`；复查无 LISTENING |

### 备注

- 本轮为关闭 M1 人工门禁的真实流程证据。

## T6 真实浏览器语音闭环验收（第二轮）

范围：real 模式（Next :34724 → FastAPI :18080）+ Edge headless 153 CDP（:9223）。麦克风捕获设备注入真实中文语音文件（SAPI 合成 wav，`--use-file-for-fake-audio-capture`），`--use-fake-ui-for-media-stream` 自动授权，`--autoplay-policy=no-user-gesture-required` 允许自检回放与过渡语自动播放。注入说明：语音内容为真实中文语音（非纯音/静音仿真），但 looping 注入导致 ASR 文本含无意义音节，内容分不代表真实面试水平——本验证目标是链路与声学评分，不以内容分为准。

### 执行结果

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 设备自检（录 3s → 回放 → 确认） | 通过 | 自检录音 3s → 自动回放 →「能清楚听到自己的声音吗」→ 点击「自检通过，进入面试舱」 |
| 拒绝权限/回放失败路径 | 代码就绪 | NotAllowed/NotFound 文案与回放失败重试已实现；本轮未注入权限拒绝（自动化浏览器自动授权），留人工抽验 |
| 1.5s 座舱过场 | 通过 | 自检通过后进入「正在进入面试舱…」过场页，随后渲染面试舱 |
| 面试舱核心展示 | 通过 | 左侧题目进度轨道（1–6 节点、当前橙色、追问中 pulse）、字幕逐字亮起（40ms/字）、右上 ⏱ 计时、电平环随注入语音起伏 |
| 真实 MediaRecorder→WebM→multipart 上传 | 通过 | 12 次语音提交全部 200（6 题 + 每题追问，共 12 次，符合每题最多 1 层追问） |
| 真实 ASR 转写 | 通过 | 服务端 FunASR 对注入语音返回真实转写（含无意义音节，见注入说明） |
| 声学评分非 null | **通过** | 报告 session 1：`expression_fluency.score=82.7`，reason=「语速168字/分（扣10.5）、停顿6.8次/分（扣1.5）、填充词6.8个/分（扣5.3），共12条有效语音回答」——浏览器声学值真实进入评分 |
| done → 跳转报告页 | 通过 | 浏览器位于 `/reports/1`（sid 路径，非 report_id） |
| 过渡语播放 | 降级验证 | edge-tts 403（R1黄）导致 `transition_audio_url=null`，前端静默跳过播放、不阻断推进——失败不阻断路径已实测 |
| 语音提交同步 ref 锁 | 代码就绪 | `voiceSubmitLockRef` 同步拦截双击；自动化未注入双击竞态，留人工抽验 |
| 单测 / typecheck / build | 通过 | 19 tests 全过；`tsc --noEmit` 0；`next build` 0 |
| 端口清理 | 通过 | `taskkill` 结束 :9223/:34724/:18080，复查无 LISTENING |

### 已知边界

- 注入语音 looping 使转写文本失真（"hello 啦 啦 ty 啥"类音节），内容维度分（2.5/5.0/4.0）不具参考性；声学维度与链路行为是本轮验收对象。
- 真人完整 6 题语音流程（含自然语音内容分）仍属 M2 终验项（J 人工 curl 已关闭；H 严格断网已通过，见下节）。

### J 人工 curl 证据（2026-09-22，补录）

说明：本段为并行验收线产出的 **人工 curl J 证据**，仅补录至本文件；**不覆盖**上文「T6 真实浏览器语音闭环验收（第二轮）」记录。样本为真实中文 WebM（SAPI 中文合成 wav → ffmpeg opus），未将音频/json 合入本分支。

前置：`TTS_ENABLED=false`，`ASR_ENABLED=true`，uvicorn `127.0.0.1:18080`；样本约 59632 bytes / 10.3s。

1. 创建会话
   - `POST /api/sessions` body `{"job_id":1}` → **HTTP 200**，**sid=1**，`question.seq=1`，`audio_url=null`

2. 主答（真实中文 WebM）
   - `POST /api/sessions/1/answers` multipart：`audio`=中文 webm，`duration_s=10.3`，`pause_cnt=1`
   - **HTTP 200**（约 26.3s，含首次 FunASR 加载）
   - 响应：`type=followup`，`question.seq=1`，`transition_audio_url=null`

3. 追问（同样本）
   - 同上，`pause_cnt=0` → **HTTP 200**（约 0.63s）
   - 响应：`type=next`，`question.seq=2`，`transition_audio_url=null`
   - 推进：**followup → next**

4. DB `answers` 声学落库

| id | q_seq | is_followup | duration_s | wpm | pause_cnt | filler_cnt |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1 | 0 | 10.3 | 209.7 | 1 | 0 |
| 2 | 1 | 1 | 10.3 | 209.7 | 0 | 0 |

5. 本轮 J 未跑至 `done`，无流畅度终评；全场报告仍以上文浏览器第二轮为准。
6. FastAPI 端口清理：验收后 `taskkill` 结束 uvicorn；复查 `18080/34723/34722/9231` 均为 **NO_LISTENER**。

### 五项竞态冒烟（2026-09-22，合入前）

范围：`feature/T6-voice-player` @ `62af8dc`；real 模式 Next `:34724` + FastAPI `:18080`；Edge headless CDP；双击竞态；计量以 **DB 行数 / MediaRecorder 构造次数 / Audio 构造与元素 play 次数** 为准。

| # | 项 | 结果 | 证据 |
| --- | --- | --- | --- |
| 1 | 双击岗位选择，仅创建一个会话 | 通过 | 选岗后 sessions=0；自检通过后 sessions=1 |
| 2 | 双击自检开始，仅创建一个媒体流 | 通过 | MediaRecorder 构造=1，getUserMedia=1 |
| 3 | 双击自检通过，仅发一个创建会话请求 | 通过 | DB 仅 sid=1（与 #1 同证） |
| 4 | 双击停止并发送，仅发一个音频请求 | 通过 | answers 仅 1 行（session_id=1, q_seq=1） |
| 5 | 过渡语 pending≤1；新题音频每题自动尝试≤1 | 通过 | pending 期 `Audio('/audio/smoke-t0.mp3')` ctor=1；首题 el.play(q)=1；答后增量 q≤1 |

冒烟脚本退出：`SMOKE_OK` / `SMOKE_EXIT=0`。验收后清理 `:18080` / `:34724` / `:9223` → **NO_LISTENER**。

### H 严格断网与本地缓存转写验收证据（2026-09-22）

说明：依据 `docs/asr-implementation-spec.md` §7-H，实施严格断网隔离（拦截所有非 loopback socket 连接，抛出 `OSError(10051, Network is unreachable)`），并设置 `MODELSCOPE_OFFLINE=1`、`HF_HUB_OFFLINE=1`，验证冷启动加载本地缓存模型并完成真实中文 WebM 转写。

1. **环境与隔离手段**：
   - 环境变量：`MODELSCOPE_OFFLINE=1`，`HF_HUB_OFFLINE=1`，`ASR_MODEL_CACHE_DIR=E:\ai_models\funasr`
   - Socket 拦截：对 `8.8.8.8:53` 外呼连接主动抛出 `[Errno 10051] [H断网拦截] 网络不可达`
2. **输入样本**：
   - 真实中文语音（Windows SAPI Huihui，16kHz mono），内容：“我们使用CANoe进行智能汽车总线通信测试和故障注入”
   - ffmpeg 转码为真实 WebM/Opus 容器样本（23833 字节）
3. **执行链路与判定**：
   - **ffprobe** 真实容器探测：通过（Opus, 1 channel, 16000 Hz）
   - **ffmpeg** 转码为 16k mono wav：通过（195598 字节）
   - **FunASR AutoModel** 冷加载：完全读取本地缓存 `E:\ai_models\funasr\models\iic--speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch\snapshots\master\model.pt`（status: `<All keys matched successfully>`）
   - **转写结果**：`'我 们 使 用 canoe 进 行 智 能 汽 车 总 线 通 信 测 试 和 故 障 注 入'`
   - **首加载+转写耗时**：24.37 秒，RTF=0.242
   - **结论**：**H 严格断网验收通过**，无任何外网依赖，模型完全依赖本地缓存离线运行。

## [T4-FIX] edge-tts 7.2.8 升级与真实合成验证

说明：依据 [T4-FIX] 任务单，在分支 `feature/T4-edge-tts-7` 验证 `edge-tts==7.2.8` 升级后的兼容性与真实合成。

### 1. 环境与依赖锁定
- Python 版本：3.11.9
- 依赖变更：`requirements.txt` 精确锁定 `edge-tts==7.2.8`
- pip 解析结果：卸载 `edge-tts-6.1.19`，安装 `edge-tts-7.2.8` 及唯一新增子依赖 `tabulate-0.10.0`，无其他冲突

### 2. 真实执行与 ffprobe 校验
- 执行调用：`Communicate("你好", voice="zh-CN-XiaoxiaoNeural").save(...)`（pytest `test_edge_tts_v7_real_synthesis_and_ffprobe`）
- **复测（2026-09-22 18:07，worktree `E:\ai_interview_hub_t4` @ `fd9ca53`）**：
  - `edge_tts.__version__ == 7.2.8`；voice=`zh-CN-XiaoxiaoNeural`
  - 短句「你好」pytest：**PASSED**（`REAL_TTS_EXIT=0`，约 3.9s）
  - 复述句「你好，智驾测试过渡语验证。」：`mp3_bytes=19152`；ffprobe `format_name=mp3`，`codec_name=mp3`，`sample_rate=24000`，`channels=1`，`duration=3.192000`
- 首轮记录：短句「你好」约 7200 字节，`duration=1.200000`（与句长一致，链路可用）

### 3. 会话预取与静态服务验证
- 服务端创建会话：`POST /api/sessions`（job_id=1）返回 HTTP 200，sid=1
- 预取返回值：
  - `question.audio_url`: `/audio/session_1_q1.mp3`
  - `transition_audio_urls`: 3 条过渡音频 URL
- 静态路由验证：
  - `GET /audio/session_1_q1.mp3` → HTTP 200，`content-type: audio/mpeg`，大小 24048 字节
  - 3 条过渡语经 `/audio/...` 访问均返回 HTTP 200
- 降级验证：模拟网络异常时，会话创建不阻塞，`audio_url` 平稳降级为 `None`

### 4. 自动化测试回归
- 真实验收门控：`test_edge_tts_v7_real_synthesis_and_ffprobe` 仅当 `TTS_ACCEPTANCE_REAL=1` 执行；未设置时 `pytest.skip`（理由：需真实 edge-tts 网络验收）
- **普通门禁**（`TTS_ACCEPTANCE_REAL` 未设置，worktree `E:\ai_interview_hub_t4` 合入 main `73d363f` 后）：全量 pytest **68 passed, 2 skipped**（含真实 TTS 与 ASR 真实验收各 1 条），退出码 0
- **真实 TTS 门禁**（`TTS_ACCEPTANCE_REAL=1`，仅跑 `test_edge_tts_v7_real_synthesis_and_ffprobe`）：**1 passed**，退出码 0；短句「你好」`mp3_bytes=7200`；ffprobe `format_name=mp3`，`codec_name=mp3`，`sample_rate=24000`，`channels=1`，`duration=1.200000`；跑完清除环境变量
- 附带修复（既有提交）：`TTS_ENABLED=false` 时预取/URL 复用一律返回 `None`，避免磁盘残留 MP3 污染文本编排断言；`test_text_flow` autouse 关闭 TTS
- 临时验证产物未入库；本定点修复仅改 `tests/test_tts.py` 与本文件

## [T6-FIX] 最终评分断连后的报告只读恢复

范围：仅前端结果确认。网络异常或反代式 HTTP 500（无已知业务 `detail.code`）后，**不重发 POST**，只读轮询 `GET /api/reports/{sid}`；503 / 409 `ANSWER_IN_PROGRESS` 等保持原语义。

分支 / worktree：`feature/T6-final-result-recovery` @ `E:\ai_interview_hub_t6_recovery`，基线 `main`=`5c5c3ca`。

### 行为要点

1. POST 严格只发一次（既有同步锁）。
2. 结果不明 → 保持提交锁 + 文案「正在确认评分结果，请勿重复提交」→ 首次立即查报告，之后每 2s，最长 120s。
3. 报告 200 合法 → `router.push(/reports/{sid})`；`REPORT_NOT_FOUND` 继续等；`SESSION_NOT_FOUND` 停；超时保留锁并给出报告页链接。
4. 组件卸载 AbortSignal 取消轮询。
5. **未改** `server/**`、评分规则、LLM/ASR/TTS、API 契约、`package.json` / `next.config.ts`。

### 自动化（A–I）

| 项 | 结果 |
| --- | --- |
| A 网络异常后 404→404→200，POST=1 | 通过 |
| B HTTP 500 未知 → 报告立即 200 | 通过 |
| C 503 SCORING_UNAVAILABLE 不轮询 | 通过 |
| D 409 ANSWER_IN_PROGRESS 不重发、不轮询 | 通过 |
| E SESSION_NOT_FOUND 立即停 | 通过 |
| F 非法报告结构 → still_unknown | 通过 |
| G 超最大轮询停，POST 仍=1 | 通过 |
| H AbortSignal 取消 | 通过 |
| I 409 SESSION_COMPLETED 只读确认报告 | 通过 |
| J 未知 404（无 code / 非 REPORT_NOT_FOUND）立即停，GET=1 | 通过 |
| K 仅 REPORT_NOT_FOUND 才继续轮询 | 通过 |

### 复审定点（Astra）

- 404 仅 `REPORT_NOT_FOUND` 继续；其余 404 → `unexpected_http`。
- `page.tsx` sleep 在定时器结束与 abort 时均 `removeEventListener`。
- amend 入本分支 HEAD；文件边界仍为批准的 4 个文件。

### 门禁与浏览器 stub

| 检查 | 退出码 |
| --- | --- |
| `npm test`（含 A–I） | 0（43 pass） |
| `npm run typecheck` | 0 |
| `npm run build`（含 real 验收构建） | 0 |
| 全量 pytest（项目 .venv） | 0（69 passed, 2 skipped） |

浏览器 stub（Edge headless CDP + 临时 stub `:18091`，Next `:34730`）：
- 答案 POST **1** 次（代理式 HTTP 500，无业务 code）
- 恢复轮询报告：`404 REPORT_NOT_FOUND` → `404` → `200`；随后报告页自身再 GET 1 次（预期）
- 最终 URL：`http://127.0.0.1:34730/reports/5`
- 全程无第二次 POST；验收后 `:18091` / `:34730` / `:9235` 均清理为无监听

### 合入 main 与合入后抽验（2026-09-22）

- 合入前确认 `main`=`5c5c3ca`（未前进）。
- `--no-ff` 合入：`9945a8c` Merge branch `feature/T6-final-result-recovery`（功能提交 `253c829`）。
- 合入后于 `E:\ai_interview_hub`（main）复跑 stub 最终题抽验：
  - POST×1（代理式 500）→ 报告 `404→404→200` → 自动进入 `http://127.0.0.1:34730/reports/5`
  - `ACCEPT_EXIT=0`；端口 `:18091` / `:34730` / `:9235` → CLEAN
- 长评分断连恢复机制在合入后的 main 上已再验证；真人最终题全链路可作为 M2 关闭后的联调抽检项保留。

## T7-G1-BE 成长追踪后端

范围：学生身份归属、input_mode/scoring_version 列、成长只读 API、种子学生 3/4；不写 v1（待 ASR 规范化验收）。

### 自动化

| 项 | 状态 |
| --- | --- |
| tests/test_growth.py | 见本票门禁 |
| 创建会话必填 user_id+mode | 旧请求体 422 |
| 首答原子写 input_mode；混用 409 | text->voice 与 voice->text 双向 |
| 同步 main 6f2facb（ASR CJK） | merge-base=6f2facb；保留双方 audio 测试 |
| scoring_version 新报告保持 NULL | P8；测试用 fixture |
| sid=5 | 不改写 |

## [T5-FIX] FunASR 中文字间空格规范化与评分证据恢复

范围：仅 `server/services/asr.py` 增加 `normalize_asr_text`，在 `transcribe_wav` 返回前折叠 CJK–CJK 空白；不改 `validate_evidence`、不放宽 25 字、不动 sid=5、不写 `SCORING_VERSION`。文本答题不经过本函数。

分支 / worktree：`feature/T5-asr-cjk-normalize` @ `E:\ai_interview_hub_asr_normalize`，基线 `main`=`2c9cc24`。

### 归一化规则

- 仅当空白两端均为 CJK 统一汉字（`\\u4e00-\\u9fff`）时删除该空白（含空格/制表/换行/全角空格）。
- 保留：英文词间、数字间、英文与英文、以及非 CJK–CJK 两端的空格（如 `使用 CANoe`、`ISO 26262 功能安全`）。

### 证据匹配（夹具，不改 sid=5）

| 场景 | 结果 |
| --- | --- |
| 规范化前：`超声波雷达` ∈ 带汉字间空格原文 | **失败**（复现冲突面） |
| 规范化后：同 evidence + 严格 `validate_evidence` | **通过** |
| 超长 / 虚构 / 首尾空格 | 仍失败（规则未放宽） |

### 自动化

| 项 | 结果 |
| --- | --- |
| `normalize_asr_text` 用例（CJK / CANoe / ISO / 换行 / 空串） | 通过 |
| 语音落库为规范化文本 + wpm/filler 同源 | 通过 |
| `tests/test_scoring.py` evidence 严格性回归 | 通过 |
| 定向 `test_audio_flow` + `test_scoring` | 33 passed, 1 skipped |
| 全量 pytest | 72 passed, 2 skipped |
| `ASR_ACCEPTANCE_REAL=1` 真实 FunASR | 通过：落库文本无 CJK–CJK 间空格 |
| sid=5 | **未改写、未重跑**（保留缺陷样本） |

## T7-G1-FE 学生档案选择与成长追踪前端

范围：`web/lib/growth-data.ts` 校验与折线转换；首页 real 模式学生/mode 选择与创建会话三字段；`/growth` 历史与趋势；报告页成长入口携带 `user_id`/`job_id`。不改 server、不改依赖。

### 自动化

| 项 | 状态 |
| --- | --- |
| growth-data 纯函数（请求体三项、双学生隔离、0/1/3 历史、null 不补零、connectNulls=false、不可比 reasons、报告链接、非法抛错） | 见 `npm test` |
| `npm test` | 通过，退出码 0（52 pass） |
| `npm run typecheck` | 通过，退出码 0 |
| `npm run build` | 通过，退出码 0 |
| `git diff --check` | 通过 |

### 浏览器验收（mock/stub）

- stub `:18092` + Next `:34731`（real rewrite）。
- 首页/成长页 HTTP 200；`POST /api/sessions` 三字段 body → 200；仅 `job_id` → 422。
- 学生4历史 `records:[]`（0 条空态数据源）。
- 报告页成长链接为 CSR（加载报告后渲染）；`buildGrowthHref`/`buildReportHref` 由单元测试覆盖。
- 验收后 `:18092` / `:34731` 已清理无监听。

### 合入约束

- 禁止直接合 main；经 Astra 审查后进入 `feature/T7-growth-integration`。

## T7-G1-FE 定点修复（Astra 驳回 bc138de）

范围：修复 `page.tsx` 无身份 `reportHrefFor` 自递归；趋势按 `(input_mode, scoring_version)` cohort 拆系列；同步 `main 6f2facb`。不改 T6 断连恢复、不改依赖/后端。

### 修复点

1. `resolveReportHref`：无身份 → `reportPathForSid`（`/reports/{sid}`）；有身份 → `?user_id=&job_id=`；本地函数改名 `buildInterviewReportHref`，禁止遮蔽。
2. `transformTrendToLineOptions`：多 cohort 时 overall+四维全部拆系列，非本 cohort 填 null，`connectNulls=false`；text/voice、v1/v2、legacy 互不连线；单 cohort 保持综合分+四维。

### 门禁

| 检查 | 退出码 |
| --- | --- |
| `npm test` | 0（59 pass） |
| `npm run typecheck` | 0 |
| `npm run build` | 0 |
| 全量 pytest | 0（72 passed, 2 skipped） |
| `git diff --check` | 见提交前 |

不合入 main / integration；交 Astra 复审。

## T7-G1-INTEGRATION 成长追踪集成分支联调

范围：自 `main@6f2facb`（含 ASR CJK `ca9a75e`/`6f2facb`）建 `feature/T7-growth-integration`；`--no-ff` 先后合入 BE `f185b97`、FE `5fac0f6`；只解冲突、不重构；P8 保持 `SCORING_VERSION=None`；禁止合入 main。

### 合并

| 步骤 | 提交 |
| --- | --- |
| merge BE | `5a24ccc`（`6f2facb` + `f185b97`） |
| merge FE | `c1b395d`（`5a24ccc` + `5fac0f6`） |
| 冲突 | 仅 `memory/TESTING.md`（双方均改）；保留 BE 节 + FE 节，无生产代码冲突 |

### 联调 stub

- `tests/test_growth.py::test_integration_stub_matrix_and_p8_closed`
- 覆盖：两学生两岗位、0/1/3 次、跨学生/跨岗位隔离、text/voice/legacy 不可比、创建三字段、P8 仍关闭

### 门禁（integration worktree）

| 检查 | 退出码 |
| --- | --- |
| 全量 pytest | 0（85 passed, 2 skipped） |
| `web/npm test` | 0（59 pass） |
| `npm run typecheck` | 0 |
| `npm run build` | 0 |
| `git diff --check` / `main...HEAD` | 0 |

不合入 main；交 Astra / 队长审查后另票合 main。

## T7-G1-P8 评分版本闸门验收

范围：在 `feature/T7-growth-integration`（起点 `1c0d706`，验收提交 `288e488`）上，用 ASR CJK 规范化后的语音链路新建完整语音会话；**不改 sid=5**（本 worktree 演示库无 sid=5；验收库 `data/p8_gate.db` 独立，已清理）。音频为 **受控真实中文 WebM**（Windows SAPI → ffmpeg opus），**标注：受控音频验收，非真人麦克风验收**。

### 语音闸门结果

| 项 | 值 |
| --- | --- |
| 新 sid / report_id | **1 / 1**（库 `data/p8_gate.db`，已清理） |
| 学生 / 岗位 | user_id=**3**（王*明）/ job_id=**1**（智驾测试） |
| input_mode | `voice` |
| 主问题 / 追问 / 总回答 | **6 / 2 / 8**（全部 `POST .../answers` multipart） |
| professional_match | score=**80.0**，evidence=`超声波雷达与毫米波雷达的台价标定`（len=16），字面子串命中 answer_id=**1** q_seq=**1** |
| logic_structure | score=**87.5**，evidence=`先复现缺陷用系统日志和传感器回放数据`（len=18），字面子串命中 answer_id=**2** q_seq=**2** |
| job_competence | score=**89.0**，evidence=`坚持功能安全底线组织跨部门风险评审`（len=18），字面子串命中 answer_id=**6** q_seq=**5**（追问） |
| expression_fluency | score=**97.0**（确定性声学；evidence=null）；语速205字/分、停顿1.1次/分、填充词0.0个/分；样本含真实 duration_s/wpm/pause_cnt/filler_cnt（8 条） |
| overall | **88.4** |
| 落库答案 CJK–CJK 间空格 | **无**（8/8） |
| P8 | **【通过】** |
| SCORING_VERSION | 验收后启用 **`"v1"`**（闸门会话报告当时仍为 NULL，属闸门前样本，**不回填**） |

### 代码与测试

- `server/services/scoring.py`：`SCORING_VERSION="v1"`（仅改常量；未改算法/prompt/evidence/双评）
- 自动化：新报告 v1、legacy NULL 不回填、history 原样、trend overall 对 legacy/v1 不可比、前端 cohort 拆线、evidence 字面规则、input_mode 隔离不回归
- 受控音频 / 临时 DB / 结果 JSON：**不入库**；验收后清理，不以 `.gitignore` 掩盖未跟踪目录

### 门禁（P8 收尾重跑）

| 检查 | 退出码 |
| --- | --- |
| 全量 pytest | 0（86 passed, 2 skipped） |
| `web/npm test` | 0（59 pass） |
| `npm run typecheck` | 0 |
| `npm run build` | 0 |
| `git diff --check` | 0 |

### 宣称纪律

本轮为受控合成中文 WebM 技术闸门，**不得宣称真人语音验收**。**未合入 main**。
