# 改进计划：M2 关闭 → 质量加固 → T8/T9 合入 → M3 冻结 → M4 实测

> 状态：草案 v1（2026-09-23 起草，基于 main @ 4cb6da5，待队长批准）
> 前提声明：**批准本计划即视为：① 队长批准 T8/T9 两份规格及实现合入 main；② 批准下述小范围代码修复。**
> 执行纪律：每项按任务逐次提交（`T{n}: 摘要`）、带测试证据、不扩文件边界、不新增第三方依赖。

## 一、问题分析（按严重度）

### P0 —— 里程碑风险

1. **M2 未关闭**（截止 9/28，剩 5 天）：真人语音终验最后一步前端 HTTP 500（Next 反代 ECONNRESET）未自动跳转报告页；终验证据 82 行只存在于未合并分支 `feature/M2-final-acceptance`，main 的 `memory/TESTING.md` 完全没有记录。
2. **跑 pytest 会清空真实演示库**：`tests/test_text_flow.py:26-33`、`tests/test_audio_flow.py:32`、`tests/test_growth.py:77-82` 直接连 `data/interview.db` 清空全部表（仅 `test_seeds.py` 正确使用内存库）。M4 实测数据一旦落库，任何一次跑测试即被抹掉。
3. **演示库与种子严重不符**：`data/interview.db` 仅 1 岗位 6 题、种子学生 id=3/4 缺失、遗留 legacy user id=1 的 active 会话——演示与成长页会出现空态/不可比数据。

### P1 —— M3 冻结（10/5）缺口

4. T8（企业端，+1892 行含 730 行测试）、T9（新生端，+664 行含 301 行测试）已在分支 `feature/T8-recruiter` / `feature/T9-freshman` 写完，但规格仍标"待队长批准/复审"，代码未审查、未合入。三端闭环是演示视频主线。
5. T8 将 `dims_json` 从中文标签列表改为 `{labels, weights}` 形状；已确认 `scripts/import_seeds.py:105-109` 重跑会更新已有岗位，无需独立迁移脚本，但合入后必须重跑种子导入。

### P2 —— 质量缺陷（小改动）

6. SQLite 无 WAL/timeout 配置 → 并发 "database is locked" 抛 500；心跳续租 `except: pass` 静默（`server/api/sessions.py:255、633`）。
7. `server/services/llm.py` 的 `ttft_ms` 恒 null（契约 §6.6 要求记录 {stage, model, ttft_ms, total_tokens}），影响报告书"单场平均时延"统计。
8. `server/api/reports.py:23` `.first()` 同会话多报告取数不确定。
9. 前端 `web/app/page.tsx:13-14` 死导入（`pickTransitionAudioUrl`、`ActionLock`）；`page.tsx:1015` `finishRecording` 无 try/catch，失败成 unhandled rejection。
10. 三份规格文档（growth-tracking-spec / asr-implementation-spec / report-page-spec）状态头仍标"待批准"但实现已合入 main；根目录遗留 0 字节 `test_edge.mp3`。

### P3 —— 后置

11. M4 实测导出脚本零启动（截止 10/9）：`scripts/` 仅 `import_seeds.py`。
12. T10（HMI 美化 pass + 演示种子数据清洗）未开始。

## 二、执行排期（6 阶段）

### 阶段 1（9/23–9/25）：M2 关闭 + 数据安全

- **T-M2a**：定位最终提交 ECONNRESET 根因（重点排查 Next rewrites 代理对音频上传大体的超时/连接重置，对比前端直连后端 vs 代理路径），最小修复；复验断连恢复路径（T6-FIX 已合入，可能已缓解，须实测确认）。
- **T-M2b**：重跑 M2 终验（H 断网 HTTP 端到端 + 真人麦克风整场 + 完成后自动跳转报告页 + 内容维度至少 1 项过双评），合并 `feature/M2-final-acceptance`（82 行 TESTING.md 证据）后追加复验记录，正式关闭 M2。
- **T-ISO**：新增 `tests/conftest.py`，统一注入独立临时 SQLite（`DATABASE_URL` → pytest tmp_path），移除三个测试文件内的清表夹具；验收：pytest 全绿且 `data/interview.db` 字节级不变。
- **T-SEED**：备份后重建演示库 → `scripts/import_seeds.py` → 核验 2 岗位 12 题 + 学生 id=3/4 → 流程写入 `memory/TESTING.md`。

### 阶段 2（9/25–9/26）：稳健性小修

- `server/db.py`：SQLite `connect_args={"timeout": ...}` + WAL。
- `server/api/sessions.py`：续租失败记日志，不再静默。
- `server/api/reports.py`：按 id 降序取最新报告，消除取数不确定性。
- `server/services/llm.py`：stream 首块计时实现 `ttft_ms`（保持 fallback 链/重试/usage 记录语义不变），usage 日志补齐契约字段。
- `web/app/page.tsx`：清理死导入、`finishRecording` 补 try/catch。
- 文档：三份规格状态头回写"已批准并实施"；删除 `test_edge.mp3`。

### 阶段 3（9/26–9/30）：T8 企业端合入

- 按任务票边界逐文件审查 `feature/T8-recruiter`（重点：加权排序 Decimal、缺维资格 min 3 有效维、权重和=1 校验 503、dims_json 英文键形状、种子文件变更）→ 合入 main → 重跑 `import_seeds.py` 完成 dims_json 形状迁移 → 全量 pytest（89 + T8 用例）绿。
- T8 验收走查：两学生同岗位训练后出现在企业列表、候选数据可追溯原会话/报告、再训练更新不新增重复候选人、跨岗位记录不混入 → 证据入 `memory/TESTING.md`。

### 阶段 4（9/30–10/3）：T9 新生端合入

- 同流程审查合入 `feature/T9-freshman`（静默降级 degraded 标志、train_hint 进种子岗位、`data/freshman_static.json`）。
- T9 验收：新生路径 30 秒进入岗位训练入口 → 训练完成在成长页可见（统一学生身份、不产生虚构咨询分数）→ 全量测试绿。

### 阶段 5（10/3–10/5）：M3 冻结验收 + T10

- 三端贯通演练 = 演示视频脚本路径：新生了解岗位 → 学生训练 → 报告建议 → 再次训练与成长记录 → 企业查看同源候选报告。
- T10：全屏走查无 debug 痕迹、HMI 美化 pass、演示种子数据清洗。
- M3 冻结记录入 `memory/TESTING.md`。

### 阶段 6（10/6–10/9）：M4 实测导出

- 新增 `scripts/export_stats.py`：批量生成会话、导出时延/评分统计、匿名参与者同岗位多次训练的原始记录与有效维度变化（任务票另定文件边界后施工）。

## 三、边界与不做的事

- 不新增第三方依赖；不改数据模型字段。
- **不补 FK/索引**（登记为已知限制：SQLite 演示规模无实际风险，动表有迁移风险，违背"禁止大爆炸重构"）。
- 无鉴权为既有设计（局域网演示形态，§3 范围外），不改动。
- 每阶段产出：git 提交 + `memory/TESTING.md` 证据 + 构建通过；阶段 3/4 若审查发现规格与实现偏差，停下汇报待确认，不自行扩界。

## 四、预计改动文件清单

| 阶段 | 文件 |
| --- | --- |
| 测试隔离 | 新增 `tests/conftest.py`；改 `tests/test_text_flow.py`、`tests/test_audio_flow.py`、`tests/test_growth.py` |
| 稳健性 | `server/db.py`、`server/api/sessions.py`、`server/api/reports.py`、`server/services/llm.py` |
| 前端 | `web/app/page.tsx` |
| 文档/数据 | `memory/TESTING.md`、3 份 docs 规格状态头、演示库重建（数据操作）、删除 `test_edge.mp3` |
| M2/T8/T9 | 合并既有分支 + 按审查结论的必要修复 |
| M4 | 新增 `scripts/export_stats.py`（待任务票定稿） |

## 五、未解决事项与下一步建议

1. ECONNRESET 根因待实测定位（阶段 1 首项）。
2. T7-G1 "真实浏览器双学生成长页走查" 补一次人工验收（随阶段 3 联调一并做）。
3. 请队长确认：批准本计划 = 批准 T8/T9 规格合入；若只想先做 M2，请退回说明。
