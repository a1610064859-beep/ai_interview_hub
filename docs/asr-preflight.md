# T5-P0：ASR 与转码链路环境预检报告

| 项 | 值 |
| --- | --- |
| 任务 | T5-P0「ASR 与转码链路环境预检」（只读核验，为 M2 真实语音链路提供前置条件审计） |
| 分支 / worktree | `feature/T5-asr-preflight` / `E:\ai_interview_hub_t5_preflight` |
| 基线 | main `4169c18`（2026-09-21） |
| 预检方式 | 仅执行只读命令与临时目录往返实测；**未安装任何依赖、未下载任何模型、未启动任何长期服务、未修改任何生产文件** |
| 范围 | ffmpeg/ffprobe 转码链路（AGENTS §4 语音链路）、FunASR 及其运行依赖、GPU/模型资产现状。TTS（edge-tts，T4）不在本次范围 |

**标记约定**：`[已验证]`=本机实测取证；`[未验证]`=本次未测、不得推断；`[缺口]`=与 M2 目标态相比缺失，需 T5 任务票批准后补齐。

---

## 1. 核验结论总表

| # | 检查项 | 结果 | 证据 | 状态 |
| --- | --- | --- | --- | --- |
| 1 | ffmpeg 存在性 | 可用 | `command -v ffmpeg` → `/c/Users/administator/AppData/Local/Microsoft/WinGet/Links/ffmpeg` | [已验证] |
| 2 | ffmpeg 版本 | 8.1-full_build（gyan.dev，WinGet 安装） | `ffmpeg -version` 前 3 行 | [已验证] |
| 3 | ffprobe 存在性与版本 | 可用，8.1-full_build 同源 | `ffprobe -version` | [已验证] |
| 4 | Opus 解码器 | `opus`（native）与 `libopus` 双解码器在列 | `ffmpeg -decoders \| grep -i opus` | [已验证] |
| 5 | Opus 编码器 | `libopus` 在列（本链路仅需解码，编码用于测试造数） | `ffmpeg -encoders \| grep -i opus` | [已验证] |
| 6 | WebM/Matroska 解复用 | `matroska,webm` demuxer 在列 | `ffmpeg -demuxers` | [已验证] |
| 7 | WAV 封装 | `wav` muxer 在列 | `ffmpeg -muxers` | [已验证] |
| 8 | webm/opus → 16kHz 单声道 wav 往返 | 成功：1s 正弦造数 webm/opus（48kHz/单声道/matroska,webm）→ `pcm_s16le / 16000 Hz / channels=1 / bits_per_sample=16`，duration=1.000000 | ffprobe 前后对比（§3 步骤 1–4） | [已验证] |
| 9 | 损坏输入失败判据 | 非法 webm 输入：ffmpeg 退出码 **183**，stderr 含 `Invalid data found when processing input`（EBML header parsing failed） | 临时目录实测（§3 步骤 5） | [已验证] |
| 10 | Python 解释器 | CPython 3.11.9，`C:\Users\administator\AppData\Local\Programs\Python\Python311\python.exe` | `python --version`、`sys.executable` | [已验证] |
| 11 | FunASR 可导入 | **不可导入**：`ModuleNotFoundError: No module named 'funasr'`；requirements.txt 亦未声明 | 导入矩阵（§3 步骤 6） | [缺口] |
| 12 | FunASR 关键运行依赖 | `torch`、`torchaudio`、`soundfile`、`librosa`、`modelscope`、`scipy`、`multiprocess` 全部 `ModuleNotFoundError`；仅 `numpy 2.4.6` 在装 | 同上 | [缺口] |
| 13 | GPU 硬件 | NVIDIA GeForce RTX 3070 Ti Laptop GPU（nvidia-smi 可列出） | `nvidia-smi -L` | [已验证] |
| 14 | GPU 经 torch 可用性 | 未测（torch 未安装） | — | [未验证] |
| 15 | FunASR 模型资产 | 本地无缓存：`~/.cache/modelscope/hub`、`~/.cache/funasr` 均为空；paraformer-zh 首跑需联网下载 | `ls` 两缓存目录为空 | [已验证]（无资产）；模型可下载性与体积 [未验证] |
| 16 | 磁盘余量 | C: 剩余 **14G**（已用 96%）——模型下载与 torch 安装的可用空间偏紧 | `df -h ~` | [已验证] |
| 17 | numpy 2.4.6 与 funasr/torch 兼容性 | 未测（funasr/torch 未装；历史版本对 numpy 2.x 的约束未知） | — | [未验证] |
| 18 | ASR/TTS 配置键 | `.env.example` 与 `server/config.py` 无任何 ASR/讯飞/模型路径配置键；`server/services/asr.py` 仍为 M1 mock（`transcribe` 返回固定文本） | 读仓库文件 | [缺口] |
| 19 | 中文识别效果（准确率/延迟） | 未测（模型未下载、依赖未装） | — | [未验证] |

---

## 2. 环境与代码基线（读仓库文件核实）

- `requirements.txt`（8 项）：fastapi / SQLAlchemy / openai / pydantic / pydantic-settings / pytest / httpx / uvicorn。**无 funasr、torch、soundfile、librosa、modelscope，亦无 python-multipart**（音频 multipart 上传为 T5/T6 必需，AGENTS §10.1 已注明"留到音频任务单单列"）。[已验证]
- `server/services/asr.py`：M1 mock，仅 `count_filler_words` 真实存在；`transcribe()` 返回 `"Mock ASR 转写文本"`。M2 真实链路按计划在 T5 实现。[已验证]
- `.env.example` / `server/config.py`：仅 LLM 与租约配置；无 ASR 相关键。[已验证]
- AGENTS §4 约定目标链路：前端 MediaRecorder(webm) → 后端 ffmpeg 转 16k mono wav → FunASR(Paraformer) 本地批处理，讯飞 WS 为备；禁止依赖 ASR 词级时间戳。本报告只核验前置环境，不设计实现。

---

## 3. 实测记录（临时目录，已清理）

**步骤 1–4：往返转换（成功路径）**
```
1) 造数：ffmpeg -f lavfi -i "sine=frequency=440:duration=1" -ac 1 -ar 48000 -c:a libopus -b:a 32k test.webm
   → ENCODE_OK；ffprobe：codec=opus, 48000 Hz, 1 ch, format_name=matroska,webm
2) 转换：ffmpeg -i test.webm -ac 1 -ar 16000 -c:a pcm_s16le test.wav
   → CONVERT_OK
3) 验证：ffprobe test.wav
   → codec_name=pcm_s16le, sample_rate=16000, channels=1, bits_per_sample=16, duration=1.000000
```

**步骤 5：失败判据（损坏输入）**
```
echo "not-a-webm" > bad.webm && ffmpeg -i bad.webm -ac 1 -ar 16000 bad.wav
→ 退出码 183；stderr: "EBML header parsing failed" / "Invalid data found when processing input"
（注：首轮实测曾把退出码误记为 0，系管道吞码；已脱离管道单独重测，183 为 ffmpeg 真实退出码）
```

**步骤 6：Python 导入矩阵**
```
MISSING funasr / torch / torchaudio / soundfile / librosa / modelscope / scipy / multiprocess
OK     numpy 2.4.6
```

---

## 4. 最小转换命令（M2 后端应采用的形式）

```bash
# 转码：webm/opus → 16kHz 单声道 16bit wav（FunASR 友好格式）
ffmpeg -hide_banner -loglevel error -y -i input.webm -ac 1 -ar 16000 -c:a pcm_s16le output.wav

# 时长/参数校验（服务端应以此读取真实时长，禁止依赖词级时间戳）
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels:format=duration -of default=nw=1 output.wav
```

| 判据 | 内容 |
| --- | --- |
| 成功 | ffmpeg 退出码 0；ffprobe 显示 `codec_name=pcm_s16le`、`sample_rate=16000`、`channels=1` |
| 失败 | 退出码非 0（实测损坏输入为 183）；stderr 典型：`Invalid data found when processing input`（非音频/容器损坏）、`No such file or directory`、`Decoder (opus) not found`（ffmpeg 缺编解码的精简发行版） |
| 服务端处置约定 | 转码失败必须走明确错误路径，不得把空转写当正常结果静默通过（与 AGENTS §5"降级静默可用"不冲突：转码失败属输入/环境错误，非 LLM 降级） |

## 5. 最小 ASR 验收命令（M2 验收用，本次预检**未执行**）

```bash
# 前置：funasr+torch 等依赖经任务票批准安装后；首跑将联网下载 paraformer-zh 模型
python -c "from funasr import AutoModel; m=AutoModel(model='paraformer-zh', disable_update=True); print(m.generate(input='test.wav')[0]['text'])"
```

| 判据 | 内容 |
| --- | --- |
| 成功 | 对一段已知中文语音（人工可辨内容的短音频）输出与预期语义一致的转写文本；退出码 0 |
| 失败 | `ModuleNotFoundError`（依赖缺失）；模型下载失败/超时（网络）；CUDA 初始化失败（GPU 路径）；输出空文本或乱码（对已知音频） |
| 本次状态 | **未执行**：依赖未安装、模型未下载（任务约束禁止）。执行时需网络 + 磁盘（C: 仅余 14G） |

---

## 6. 缺口清单（T5 施工前须按任务票批准补齐，本预检不处理）

1. **依赖安装**：funasr、torch（+torchaudio）、soundfile、modelscope（librosa/scipy 视 funasr 依赖树）；音频上传另需 python-multipart。AGENTS §11.3：新依赖须任务单明确列出，**禁止本预检自行安装**。
2. **配置键**：`.env.example`/`config.py` 需新增 ASR 相关键（如模型名、设备选择、缓存目录、讯飞备用 WS 凭据占位）；凭据只进 `.env`。
3. **磁盘**：C: 剩余 14G（96% 已用）。torch（CPU 版约数百 MB 起，GPU 版更大）+ paraformer 模型（体积 [未验证]）叠加后偏紧，安装前应确认目标盘或清理。
4. **numpy 2.4.6 兼容性**：安装 funasr/torch 时可能触发 numpy 降级/冲突，安装方案须先声明版本组合并验证 [未验证]。

## 7. [未验证] 汇总（禁止据此猜测或宣称）

- GPU 经 torch（CUDA）实际可用性、显存余量、应选 CUDA wheel 版本
- FunASR 模型资产：paraformer-zh 可下载性、体积、下载耗时、许可证
- 中文识别效果：准确率、对 16kHz wav 的延迟、标点/热词表现
- funasr 与 Python 3.11.9 / numpy 2.4.6 的版本兼容矩阵
- 讯飞 WS 备用链路（无凭据配置，完全未测）
- 浏览器 MediaRecorder 实际输出的 webm/opus 参数（本次以 48kHz/单声道造数近似；M2/T6 联调时以真实采样为准）

## 8. 结论

- **转码前置条件：就绪** [已验证]。ffmpeg 8.1 全功能版覆盖 webm/opus 解码 → 16kHz 单声道 pcm_s16le wav 全链路，成功与失败判据均有实测证据，可支撑 AGENTS §4 语音链路与 Dockerfile 中的 ffmpeg 要求。
- **ASR 前置条件：未就绪** [已验证缺口]。Python 3.11.9 在位，但 funasr 及全部关键运行依赖缺失，本地无模型缓存；GPU 硬件在位（RTX 3070 Ti）但可用性未验。
- **建议**：T5 正式任务票列明依赖清单与版本组合（含 python-multipart）、`.env` 配置键扩界、磁盘/下载方案，经批准后安装并跑 §5 最小验收命令；在此之前语音链路保持 mock，不影响 M1/M2 现有测试。
