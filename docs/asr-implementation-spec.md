# T5-P1：ASR 依赖、模型存储与接口实施规格

| 项 | 值 |
| --- | --- |
| 任务 | T5-P1「ASR依赖、模型存储与接口实施规格」（规格与审批申请，未改任何生产代码/依赖/配置） |
| 分支 / worktree | `feature/T5-asr-spec` / `E:\ai_interview_hub_t5_spec` |
| 基线 | main `fdd74a1`（= T5-P0 `1788674` 合入后的 main；main 同期已通过验收合入 T4 TTS 预取 `757a62f`） |
| 前置输入 | `docs/asr-preflight.md`（T5-P0 实测：ffmpeg 8.1 就绪；系统 Python 3.11.9 可用；funasr/torch 全缺；RTX 3070 Ti 8GB；C 盘余 14G） |
| 状态 | **待队长审批**。§5 API 细则、§1 依赖、§4 配置键、§6 文件边界均"批准后才可施工" |
| 修订记录 | v1=`d677712` 初稿；v2=按 Astra 审查修订：①输入内容损坏（含截断/内部损坏）统一 422 AUDIO_INVALID，503 仅限环境缺失败；②删除 ASR_DISABLED，关闭 ASR 统一 503 ASR_UNAVAILABLE；③ASR_MODEL_NAME/ASR_MODEL_CACHE_DIR 改必填无默认；④ASR_PROVIDER 锁定 funasr，讯飞登记为后续缺口；⑤Dockerfile 改列待批扩界；⑥删除 prepare_asr_model.py 申请；⑦CUDA 失败自动回退 CPU 定稿；⑧验收 F 更名"并发重复请求不重复推进"；v3=错误分类弃用 stderr 文案匹配，改阶段判定（魔数初筛→ffprobe 解析→ffmpeg 转码→可执行性），stderr 仅作日志诊断，验收 D 增至三类损坏样本 |

**标记约定**：`[已验证]`=官方包元数据/官方索引/本机实测取证；`[未验证]`=未实测、禁止据此宣称；`[待批]`=本规格申请、队长批准前不得实施。

---

## 1. 依赖清单

### 1.1 直接依赖（写入 requirements.txt 的全部内容，[待批]）

```text
# ---- T5 ASR（方案A GPU；批准后追加）----
--extra-index-url https://download.pytorch.org/whl/cu121
funasr==1.4.16
torch==2.5.1+cu121; platform_system=="Windows"
torchaudio==2.5.1+cu121; platform_system=="Windows"
numpy==1.26.4
soundfile==0.14.0
python-multipart==0.0.32
```

方案B（CPU 降级）仅改两行：删除 `--extra-index-url` 行，`torch==2.5.1`、`torchaudio==2.5.1`（Windows 上 PyPI 源即 CPU 构建）。

### 1.2 兼容性结论与依据

| 结论 | 依据 | 状态 |
| --- | --- | --- |
| funasr 1.4.16 兼容 Python 3.11.9 | PyPI 元数据 `requires_python: ">=3.7.0"`（README 口径 ≥3.8，两者均含 3.11） | [已验证]（元数据） |
| torch 2.5.1 提供 Windows cp311 CUDA 12.1 wheel | 官方索引 `download.pytorch.org/whl/cu121/torch/` 列有 `torch-2.5.1+cu121-cp311-cp311-win_amd64.whl` | [已验证]（官方索引） |
| torchaudio 2.5.1 同标签 wheel 存在（与 torch 严格同版本配对） | 官方索引 `.../cu121/torchaudio/` 列有 `torchaudio-2.5.1+cu121-cp311-cp311-win_amd64.whl` | [已验证]（官方索引） |
| RTX 3070 Ti Laptop 可用 CUDA 12.1（Ampere，计算能力 8.6） | 本机 `nvidia-smi`：驱动 **610.88**、显存 **8192 MiB**；CUDA 12.1 Windows 最低驱动约 531.x，610.88 远超 | 驱动版本 [已验证]；sm_86 支持 [依据 NVIDIA CUDA GPU 能力表] |
| python-multipart 0.0.32 兼容 3.11.9 | PyPI 元数据 `requires_python: ">=3.10"`，无依赖 | [已验证]（元数据） |
| soundfile 0.14.0 兼容 3.11.9，满足 funasr 的 `soundfile>=0.12.1` | PyPI 元数据 `requires_python: ">=3.10"`；`requires_dist: ["cffi>=1.0","numpy","typing-extensions"]`；funasr 1.4.16 元数据声明 `soundfile>=0.12.1` | [已验证]（元数据） |
| numpy 选择 1.26.4（钉死） | funasr 1.4.16 元数据对 numpy **无约束**；但其传递依赖 umap-learn 引入 numba，numba 对 numpy 有版本上限（具体上限 [未验证]）。1.26.4 为 numpy 1.x 末代，与 py3.11 / torch 2.5.1 / scipy / librosa 兼容面最大，属**确定性选择** | 元数据 [已验证]；numba 上限 [未验证]；运行期以 §7-B/C 验收确证 |
| **torch、torchaudio 必须显式写入 requirements** | funasr 1.4.16 的 `requires_dist` **不含** torch/torchaudio（仅 README 指示手动安装）；`pip install funasr` 不会带上 PyTorch | [已验证]（元数据） |

### 1.3 直接依赖 vs 传递依赖（不盲目写入 requirements）

- **直接依赖（我方代码 import 或安装器必需）**：funasr、torch、torchaudio、numpy、soundfile（`server/services/audio.py` 直接用其读 wav 校验，同时满足 funasr 约束）、python-multipart（FastAPI multipart 表单解析必需）。
- **传递依赖（由 funasr 1.4.16 自动拉取，不写入）**：modelscope（模型下载链）、scipy、librosa、PyYAML、websockets、omegaconf、hydra-core、huggingface_hub、safetensors、transformers、tiktoken、sentencepiece、kaldiio、jieba、jamo、jaconv、umap-learn、rapidfuzz、torch_complex、tensorboardX、oss2 等（funasr `requires_dist` 全量声明）。
- **与 AGENTS §10.1 已批准依赖无重叠冲突**：现有 8 项（fastapi/SQLAlchemy/openai/pydantic/pydantic-settings/pytest/httpx/uvicorn）不改动；新增 6 项全部属于本节 [待批] 块。
- 安装体积与磁盘：**安装发生在项目 venv（E 盘）**，但 pip 下载缓存默认在 C 盘（C: 仅余 14G）→ 安装时必须 `PIP_CACHE_DIR` 指向 E 盘（§3.3）。cu121 torch wheel 下载约 2.5GB+/安装后更大，CPU wheel 约数百 MB [均未实测]。

---

## 2. 队长二选一（A/B 方案）

| 维度 | **A：GPU 演示稳定方案（推荐）** | B：CPU 降级方案 |
| --- | --- | --- |
| 依赖 | torch/torchaudio 2.5.1**+cu121**（官方 cu121 索引） | torch/torchaudio 2.5.1（PyPI，Windows 即 CPU 构建） |
| 安装体积 | 下载 ~2.5GB+，安装后 ~5GB [未实测] | 下载数百 MB，安装后 ~1GB [未实测] |
| 硬件要求 | RTX 3070 Ti 8GB + 驱动 610.88（本机已具备 [已验证]）；显存占用 [未验证]（paraformer-large 推理常见 <2GB，需实测） | 无 GPU 要求；纯 CPU 推理 |
| 首次启动 | 多下载 ~2GB，模型解析稍慢；推理快 | 安装快；首次推理同样需模型下载 |
| 离线可用性 | 安装+模型缓存完成后离线可用 | 同左 |
| M2 演示风险 | 单题短音频转写延迟低（亚秒~秒级 [未验证]），演示节奏好；风险=CUDA/driver 异常路径 | 实现最简、故障面最小；风险=RTF 未测，若单题转写 >3–5s 会拖慢演示节奏 [未验证] |
| 切换成本 | — | A 失败时改 2 行 requirements 重装（§1.1），业务代码零改动（设备由 `ASR_DEVICE` 配置） |

**明确推荐：A（GPU）**。理由：目标硬件已验证在位（RTX 3070 Ti + 驱动 610.88 + 8GB 显存），评分/JD 已按"质量优先允许慢"走云端，语音链路的本地延迟是演示体验关键。**CUDA 失败行为定稿：`ASR_DEVICE=cuda` 时若 CUDA 初始化失败，自动回退 CPU 推理并记录 WARN 日志；CPU 也失败才返回 503 `ASR_UNAVAILABLE`。** B 保留为文档化降级路径——切换只改 requirements 两行 + `ASR_DEVICE=cpu`，不触发任何代码变更。**若队长选择 B，T5 施工照常，仅依赖块换为 B 版；两种方案的运行兼容性均须安装后以真实模型验收（§7-B），当前不宣称已验证。**

---

## 3. 模型资产（存储、下载、离线复用）

### 3.1 模型与目录（禁止占用 C 盘默认缓存）

- 模型：`paraformer-zh`（funasr 别名，对应 ModelScope `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch`；别名映射依据 funasr 官方文档 [别名机制已验证于文档，模型体积/下载耗时 未验证]）。
- 存储位置：**`E:\ai_models\funasr\`**（E 盘、仓库 `E:\ai_interview_hub` 之外）。结构由 funasr/modelscope 下载器自建（`hub/iic/...`），不手工造文件。
- 模型大小、下载耗时：**[未验证]**（本次未下载任何资产）。
- 用途限定：仅 ASR；TTS（edge-tts）不需要模型文件（云端合成，T4 已就绪）。

### 3.2 所需环境变量

| 变量 | 值 | 作用 |
| --- | --- | --- |
| `ASR_MODEL_CACHE_DIR`（应用配置键，见 §4） | `E:\ai_models\funasr` | 服务端以 `AutoModel(..., cache_dir=<该值>)` 传入，覆盖默认 `~/.cache`（C 盘） |
| `MODELSCOPE_CACHE`（安装/下载会话级） | `E:\ai_models\modelscope` | 约束 modelscope 包自身缓存目录（依据 modelscope 官方文档的环境变量约定 [未本机验证生效路径]） |
| `PIP_CACHE_DIR`（安装会话级） | `E:\ai_hub_cache\pip` | 避免 ~2.5GB torch 下载缓存写满 C 盘（C: 余 14G [已验证]） |

### 3.3 首次下载与离线复用（T5 施工时执行，[待批]）

```powershell
# 一次性创建缓存目录（项目外）
New-Item -ItemType Directory -Force "E:\ai_models\funasr" | Out-Null

# 首次下载（需联网；仅下载、不转写）——退出码保留判据
$env:PIP_CACHE_DIR = "E:\ai_hub_cache\pip"
python -c "from funasr import AutoModel; AutoModel(model='paraformer-zh', cache_dir=r'E:\ai_models\funasr', disable_update=True)"
if ($LASTEXITCODE -ne 0) { throw "模型下载失败: $LASTEXITCODE" } | Select-Object -First 50

# 离线复用：同一 cache_dir 再次 AutoModel 即从本地加载；disable_update=True 关闭更新检查
```

- 断网验证（验收矩阵 H）判据：缓存就绪后，在无网络条件下 `AutoModel` 初始化 + 对本地 wav 转写成功。断网实施手段（禁用网卡/防火墙规则/MODELSCOPE 离线开关）**[未验证]**，T5 施工时定并留痕。
- 首次下载授权单列于 §8（一次性联网动作）。

---

## 4. 精确配置草案（建议加入 `.env.example` 与 `server/config.py`，[待批]）

沿用现有 `Field(..., validation_alias=AliasChoices(...))` 风格（与 T4 的 `TTS_*` 键一致）。**生产代码不得硬编码模型名/路径/设备/超时/ffmpeg 路径。**

| 键 | 类型 | 默认值 | 敏感性 | 说明 |
| --- | --- | --- | --- | --- |
| `ASR_ENABLED` | bool | `true` | 公开 | 关闭时语音端点返回 503 `ASR_UNAVAILABLE`（不新增第五个错误码） |
| `ASR_PROVIDER` | str | **必填，仅允许 `funasr`** | 公开 | T5 锁定 `funasr`：配置其他值（如 xfyun）时启动即拒绝，防止服务进入未实现的分支；讯飞为后续任务缺口（§10） |
| `ASR_MODEL_NAME` | str | **必填（无默认值）** | 公开 | funasr 模型别名；示例值 `paraformer-zh` 只写入 `.env.example`；缺失时启动失败 |
| `ASR_DEVICE` | str | `cpu` | 公开 | `cpu\|cuda`；演示机置 `cuda`；CUDA 初始化失败自动回退 CPU 并记 WARN，CPU 也失败才 503（§2 定稿） |
| `ASR_MODEL_CACHE_DIR` | str | **必填（无默认值）** | 公开（本机路径） | AutoModel cache_dir；示例值 `E:\ai_models\funasr` 只写入 `.env.example`；必须为 E 盘项目外目录，缺失时启动失败 |
| `ASR_TIMEOUT_S` | float | `30.0` | 公开 | 单次转写超时；超时→503 ASR_UNAVAILABLE |
| `ASR_MAX_UPLOAD_MB` | int | `20` | 公开 | 上传音频上限，超出→413 |
| `ASR_SAMPLE_RATE` | int | `16000` | 公开 | 转码目标采样率（AGENTS §4 契约值，避免硬编码） |
| `ASR_TEMP_DIR` | str\|None | `None`（=系统临时目录） | 公开 | 转码中间 wav 目录；请求结束必须清理（§7-G） |
| `FFMPEG_PATH` | str | `ffmpeg` | 公开 | 默认走 PATH；P0 已验证 PATH 存在 |
| `FFPROBE_PATH` | str | `ffprobe` | 公开 | 同上 |
| `XFYUN_APP_ID` | str | 空 | **敏感** | 讯飞备用链路占位，本任务不接入、不编造 SDK 能力 |
| `XFYUN_API_KEY` | str | 空 | **敏感** | 同上 |
| `XFYUN_WS_URL` | str | 空 | 公开（URL） | 同上 |

---

## 5. API 与错误契约申请（[待批]）

端点名已在 AGENTS §8 契约列名（`POST /api/sessions/{sid}/answers (audio, duration_s, pause_cnt)`）；本节为其**实施细则**，新增错误码与校验范围仍需批准后方可实施。

### 5.1 请求（multipart/form-data）

| 字段 | 类型 | 必填 | 校验 | 失败 |
| --- | --- | --- | --- | --- |
| `audio` | file（webm/opus） | 是 | 非空；前 4 字节为 EBML 魔数 `1A 45 DF A3`（初筛）；大小 ≤ `ASR_MAX_UPLOAD_MB` | 缺失/非法字段 422（FastAPI 格式）；魔数不符 422 `AUDIO_INVALID`；超限 413 `AUDIO_TOO_LARGE`；魔数通过但内容损坏（截断/内部损坏）按 §5.4 判据同样归 422 `AUDIO_INVALID` |
| `duration_s` | float | 是 | `0.1 ≤ duration_s ≤ 600.0` | 越界 422 |
| `pause_cnt` | int | 是 | `0 ≤ pause_cnt ≤ 10000` | 越界 422 |

### 5.2 服务端计算（与 AGENTS §6.3 对齐，禁止依赖 ASR 词级时间戳）

- `answer_text` = FunASR 对 16kHz wav 的转写文本（服务端独占生成）。
- `filler_cnt` = 既有 `count_filler_words(answer_text)` 正则计数（嗯|那个|就是|然后|这个）。
- `wpm` = `round(去空白转写字符数 / duration_s × 60, 1)`（语速=字数/时长）。
- `duration_s`、`pause_cnt` 按客户端提交值落库（duration_s=说话时长，由前端 AnalyserNode 统计；服务端不采信转写时长替代）。

### 5.3 成功响应

复用既有 `AnswerResponse` 联合类型（含 T4 的 `transition_audio_url`），与文本端点完全同形：
`{"type":"followup","question":{...},"transition_audio_url":...}` / `{"type":"next",...}` / `{"type":"done","report_id":N,...}`

### 5.4 错误契约（区分四类失败）

| 阶段 | 错误 | 语义 | 状态推进 | 可重试 |
| --- | --- | --- | --- | --- |
| 并发/状态 | 404 `SESSION_NOT_FOUND`；409 `SESSION_COMPLETED` / `ANSWER_IN_PROGRESS` / `SESSION_RESET_REQUIRED` | 复用现有语义 | 否 | 409 视情况 |
| 上传校验（租约前，廉价检查不占锁） | 422 字段校验；422 `AUDIO_INVALID`（魔数不符/过短）；413 `AUDIO_TOO_LARGE` | 客户端输入问题 | 否 | 修正后重试 |
| 转码/内容损坏 | 422 `AUDIO_INVALID`；503 `AUDIO_PROCESS_FAILED` | **阶段判定（stderr 只记日志与诊断，不作为业务分类依据）**：① 魔数初筛不符 → 422 `AUDIO_INVALID`；② `ffprobe` 可执行但对上传文件返回非零（无法解析容器/音频流，覆盖各类截断与内部损坏，无论错误文案是 `Invalid data`、`End of file` 还是其他）→ 422 `AUDIO_INVALID`；③ `ffprobe` 通过后 `ffmpeg` 转码仍失败 → 503 `AUDIO_PROCESS_FAILED`；④ ffprobe/ffmpeg 不存在、无执行权限或启动失败（FileNotFoundError/PermissionError 等）→ 503 `AUDIO_PROCESS_FAILED`。P0 实测损坏输入（退出码 183）落阶段②归 422 | 否（释放租约回 active） | 422 须更换文件后重试；503 可原样重试 |
| ASR | 503 `ASR_UNAVAILABLE` | funasr 异常/超时/未加载 | 否（释放租约回 active） | 是 |

### 5.5 重试与防重复推进

1. **处理期幂等**：租约机制（现有 `lease_token` 原子抢占）保证同一会话同时只有一个提交在处理；并发重复请求得到 409 `ANSWER_IN_PROGRESS`，**不会重复推进**（§7-F）。
2. **失败路径**：503 类错误不创建 `Answer`、不推进 `pending_question_json`，会话回到 `active`，客户端可重发同一音频——与 §8.1"本次回答与状态推进一并回滚"同语义。
3. **成功后重发**：依赖 §8.1 客户端契约（提交期间禁用按钮、网络结果不明不自动重发）；成功后再提交同一音频将被视为对下一题的新回答，服务端**不做**成功态幂等去重（避免扩展数据模型）。此边界写入前端 T6 契约。
4. 转码/ASR 在租约持有的事务 2（业务阶段）内执行，超时/异常走现有"释放租约+心跳取消"路径；`Answer` 与状态推进仍在一个事务原子提交（事务 3）。

---

## 6. T5 实施文件边界（[待批]，不含 T6/TTS/评分/讯飞）

| 文件 | 动作 | 理由 |
| --- | --- | --- |
| `requirements.txt` | 修改 | 追加 §1.1 六项依赖块（A 或 B 版本，队长二选一） |
| `.env.example`、`server/config.py` | 修改 | §4 十四项 ASR/ffmpeg 配置键 |
| `server/services/audio.py` | **新增** | ffmpeg/ffprobe 子进程封装：转码、魔数/时长探测、临时 wav 生命周期（对齐 T4 已有的临时文件原子清理风格）、真实 returncode 判据 |
| `server/services/asr.py` | 修改 | FunASR 单例加载（进程内一次）+ 真实 `transcribe`；保留 `count_filler_words`；`ASR_PROVIDER` 仅留分支位，**不实现讯飞** |
| `server/api/sessions.py` | 修改 | 新增 `POST /{sid}/answers`（multipart），复用租约与原子落库骨架，§5.4 错误映射 |
| `server/schemas.py` | 修改（最小） | 如 multipart 需要辅助校验模型则最小追加；响应复用现有类型不改 |
| `tests/test_audio_flow.py` | **新增** | §7 矩阵；B/H（真实模型、断网）用 `ASR_ACCEPTANCE_REAL=1` 门控，默认 skip；D/E/F/G 用 monkeypatch 假 ASR/假 ffmpeg——**测试夹具与真实模型实测明确区分** |
| `scripts/`（任何文件） | **不改** | 首次模型下载使用 §3.3 文档命令，不新增脚本，控制范围 |
| `server/main.py` | **不改** | sessions router 已挂载 |

- **明确不含**：T6 录音界面/电平环（web/ 零改动）、TTS 重构（tts.py 零改动）、评分重构（scoring.py 零改动）、讯飞真实接入。
- **Dockerfile**：当前仓库无 Dockerfile（worktree 顶层实测无此文件 [已验证]）。AGENTS §4 明确"Dockerfile 必须安装 ffmpeg"，因此**新增 Dockerfile 列为待队长批准的扩界申请（§8-7，内容须含 ffmpeg 安装）**；T5 施工范围不含它，排期落点由队长指定（建议：M3 冻结前的部署准备批次）。

---

## 7. 自动化验收矩阵（tests/test_audio_flow.py + 人工步骤）

| # | 用例 | 方法（PowerShell 适配，保留真实退出码） | 通过判据 |
| --- | --- | --- | --- |
| A | 真实 webm/opus → 16k 单声道 wav | `ffmpeg -hide_banner -loglevel error -y -i sample.webm -ac 1 -ar 16000 -c:a pcm_s16le out.wav; if ($LASTEXITCODE -ne 0) { throw "ffmpeg $LASTEXITCODE" }`；`ffprobe -v error -show_entries stream=codec_name,sample_rate,channels -of default=nw=1 out.wav \| Select-Object -First 10` | 退出码 0；`pcm_s16le/16000/1` |
| B | 真实中文短音频非空转写（`ASR_ACCEPTANCE_REAL=1` 门控，模型缓存就绪后跑） | 服务内对真实 wav 调 `transcribe`；`$LASTEXITCODE` 记录 | 已知中文语音 → 非空文本，语义人工比对；失败判据=空文本/异常退出 |
| C | duration_s/wpm/pause_cnt/filler_cnt 正确 | 定长样本+已知文本提交后查 answers 行 | `duration_s`=提交值；`wpm == round(去空白转写字数/duration_s×60, 1)`；`pause_cnt`=提交值；`filler_cnt`=正则计数 |
| D | 损坏文件明确失败且不推进会话 | 提交至少三类样本：①魔数非法文件；②**头部截断**（丢弃 webm 前 1KB）；③**中部破坏**（数据段翻转/替换若干字节）。②③构造后先经 ffprobe 验证解析失败 | ①②③**均稳定返回 422 `AUDIO_INVALID`**（阶段判定 §5.4）；session 仍 `active`；answers 计数不变。边界记录：尾部截断（cue 区丢失）可能通过 ffprobe 而在 ffmpeg 阶段失败，按阶段规则归 503，不作为 D 的 422 样本 [未验证，施工时实测归档] |
| E | ASR 异常不产生 Answer | monkeypatch `transcribe` 抛异常 | 503 `ASR_UNAVAILABLE`；answers 计数不变；session 回 `active`、租约清空 |
| F | 并发重复请求不重复推进 | 并发两个相同请求（或首请求处理中再发；成功后的重发防护属客户端契约 §5.5-3，不入本用例） | 第二请求 409 `ANSWER_IN_PROGRESS`；answers 计数恰 +1 |
| G | 临时 wav 必清理 | 请求成功与失败路径各跑一次后检查 `ASR_TEMP_DIR` | 目录无残留 .wav（实现：finally 删除，对齐 T4 临时文件清理风格） |
| H | 模型已缓存不访问网络（`ASR_ACCEPTANCE_REAL=1` 门控） | 预置缓存后断网运行 B 同款（断网手段 T5 定，[未验证]） | 初始化+转写成功且无网络依赖报错 |
| I | T1–T4 全量回归 | 项目 venv 内 `python -m pytest tests -q \| Select-Object -First 50` | 全部通过（seeds/text_flow/scoring/llm/tts 既有用例零回归） |
| J | 30 秒人工验收 | ①`uvicorn server.main:app` 启动；②`curl.exe -s -X POST "http://127.0.0.1:8000/api/sessions/1/answers" -F "audio=@sample.webm" -F "duration_s=6.2" -F "pause_cnt=1" \| Select-Object -First 50`；③看返回 `type=next/followup`；④`curl.exe -s http://127.0.0.1:8000/api/reports/1`（若走完六题） | ②返回合法三态 JSON 之一；无 5xx；控制台无 traceback |

---

## 8. 待队长批准清单（全部单列，批准前不实施）

| # | 申请 | 说明 |
| --- | --- | --- |
| 1 | **方案 A/B 二选一** | 推荐 A（GPU，torch 2.5.1+cu121）；B 为降级（CPU 2.5.1）。切换成本=requirements 两行 |
| 2 | requirements.txt 追加 6 项 | funasr==1.4.16、torch/torchaudio==2.5.1(+cu121)、numpy==1.26.4、soundfile==0.14.0、python-multipart==0.0.32；安装限项目 venv 且 `PIP_CACHE_DIR` 指 E 盘 |
| 3 | `.env.example`/`config.py` 新增 14 键 | §4 键表；`ASR_MODEL_NAME`/`ASR_MODEL_CACHE_DIR` 必填无默认（示例值仅入 `.env.example`）；`ASR_PROVIDER` 锁定 `funasr`；`XFYUN_*` 仅占位 |
| 4 | API 实施细则 + 4 个新错误码 | `422 AUDIO_INVALID`、`413 AUDIO_TOO_LARGE`、`503 AUDIO_PROCESS_FAILED`、`503 ASR_UNAVAILABLE`；端点名本身已在 AGENTS §8 契约列名 |
| 5 | 文件边界（§6） | 新增 audio.py / test_audio_flow.py；改 asr.py、sessions.py、schemas.py(最小)、config.py、.env.example、requirements.txt；scripts/ 零改动（首次下载用 §3.3 命令） |
| 6 | 模型目录与一次性联网下载 | `E:\ai_models\funasr` 创建；首次下载 paraformer-zh（§3.3）；此后离线复用 |
| 7 | Dockerfile：**待批扩界（新增文件）** | 仓库现无 Dockerfile；按 AGENTS §4"必须安装 ffmpeg"新增，T5 施工不含，排期落点由队长指定（建议 M3 冻结前部署准备批次） |

---

## 9. [未验证] 汇总（禁止据此宣称）

1. paraformer-zh 模型体积、下载耗时、首次加载耗时（本次未下载任何资产）。
2. funasr 1.4.16 + torch 2.5.1 + numpy 1.26.4 在本机的实际运行兼容性（含 umap-learn→numba 的 numpy 上限；pip 解析器行为安装时确认）。
3. GPU 推理显存占用、单条短音频转写延迟（A 方案）；CPU RTF（B 方案）。
4. 断网验证的具体实施手段（防火墙/禁用网卡/MODELSCOPE 离线开关的精确行为）。
5. MediaRecorder 真实输出的容器参数（P0 以 48kHz 单声道正弦造数近似；T6 联调以真实采样为准）。
6. `MODELSCOPE_CACHE` 对 funasr 下载路径的实际约束力（cache_dir 参数为主，前者为辅）。
7. 讯飞 WS 备用链路的一切能力（无凭据、未调研，仅占位键）。
8. T5-P0 遗留：审查所见 `.venv` 启动失败场景（复测未复现）；T5 施工以重建后 venv 为准。
9. 尾部截断（EBML cue 区丢失）类损坏通过 ffprobe 探测、在 ffmpeg 阶段失败的具体行为——按 §5.4 阶段规则归 503 `AUDIO_PROCESS_FAILED`，T5 施工构造验收样本时实测归档。

## 10. 未解决事项

- 队长对 §8-1 的 A/B 二选一未决（审查建议 A：torch/torchaudio 2.5.1+cu121，保留 CPU 运行时降级）；其余批准项依赖该选择。
- CUDA 失败回退已定稿（§2：自动回退 CPU + WARN 日志；CPU 也失败才 503 ASR_UNAVAILABLE），随 §8 批准生效。
- **讯飞备用链路为后续任务缺口**：`XFYUN_*` 键仅占位，无任何实现与调研；立项与否、何时接入由队长在后续任务票决定，立项前 `ASR_PROVIDER` 仅允许 `funasr`。
- 验收 H 的断网手段与 J 的真实样本音频（建议用 T4 已产出的 TTS 音频转播为 webm 造数，或人工录一段）在 T5 施工首日确定。
- Dockerfile 扩界的排期落点（§8-7）待队长指定。
