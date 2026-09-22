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
10. 409 `ANSWER_IN_PROGRESS`：保留原文，不自动重发
11. 网络结果不明：保留原文，锁住本次页面，提示刷新确认，绝不自动重发
12. `audio_url=null` 不渲染播放器；`transition_audio_url` 可忽略播放，不误判响应非法
13. 桌面 1080p 与窄屏 360px 无横向溢出

### 执行结果

| 项 | 状态 | 说明 |
| --- | --- | --- |
| mock 6 题 + 1 次追问 | [未验证] | 未做浏览器点击；逻辑：第2题固定一次追问后继续主问题，第6题后进演示完成态 |
| real 创建会话 | [未验证] | 本轮未启动后端 |
| followup / next / done 三态 | [未验证] | 解析与 mock 推进已实现；未浏览器走完 |
| report_id 与 sid 不混用 | [未验证] | 代码：`router.push(\`/reports/${view.sid}\`)`，`report_id` 仅校验 |
| 双击只发一次 | [未验证] | `submitLock` / `createLock` 同步 ref 已实现 |
| 503 保留输入可人工重试 | [未验证] | 明确 HTTP 错误解除锁并保留 textarea |
| 网络未知不重发 | [未验证] | `hold=true`，保留原文，无自动重发 |
| audio_url=null 无播放器 | [未验证] | 仅 `audioUrl !== null` 时渲染 `<audio>` |
| 业务错误码可见 | [未验证] | 复用 `detail.code/message` 格式化 |
| 360px / 1080p 无横向溢出 | [未验证] | 沿用 `max-w-full` / `overflow-x-hidden`，未目视 |
| mock 首页 SSR | 部分 | `next start -p 34722`：HTTP 200，含演示岗位卡与“非正式”；文本框在交互后才出现 |
| `npm run typecheck` | 通过 | 退出码 0 |
| `npm run build` | 通过 | 退出码 0；构建后仅边界内文件变更，无 `next-env.d.ts` 脏改 |

### 临时服务清理

- 启动：`npx next start -p 34722`（外壳 PID 42664，监听 PID 11840）
- 清理：`taskkill /PID 11840 /T /F` 成功；复查 `34722` 无 LISTENING
- 未保留其他 Next/dev/stub 进程
