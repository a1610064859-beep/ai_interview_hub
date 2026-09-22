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
