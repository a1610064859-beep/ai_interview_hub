# Windows 复测包

复测包面向 Windows x64 电脑。目标电脑不需要预装 Python、Node.js、FFmpeg 或 LM Studio。首次运行 `start_portable.bat` 会在项目目录的 `runtime/` 中安装私有运行时，在 `.venv/` 中安装依赖，并安装网页依赖；之后可直接启动。

首次安装和首次启动需要联网：安装脚本从 Python、Node.js 官方站点及 FFmpeg 构建站点下载运行时，pip/npm 安装依赖，FunASR 首次加载时下载语音模型。预留约 8 GB 可用空间。大模型通过包内 `.env` 中的云端 API 密钥调用。复测 ZIP 将包含已授权的个人 API 密钥，请只发给获准测试的人；密钥轮换后需同步替换包内 `.env`。

## 使用

1. 解压整个 ZIP 到可写目录，例如 `C:\AIInterviewHub`。
2. 双击 `start_portable.bat`。首次运行会自动安装依赖、构建网页、导入种子岗位并启动服务，过程需要联网和数 GB 可用磁盘空间。
3. 注册或登录后在网页端复测；本机地址为 `http://127.0.0.1:3000/`。
4. 完成测试后双击 `stop_portable.bat`。

也可以先运行 `setup_portable.bat` 完成安装，再运行 `start_portable.bat`。

## 运行方式

- 大模型只走 `LLM_FLAGSHIP_*` 云端 API；LM Studio、Ollama 和本地大模型回退关闭。
- 云端模型编排超时设为 15 秒，给本 API 的推理响应留出时间；报告评分超时仍为 60 秒。
- 语音识别检测可用 NVIDIA GPU，优先安装 CUDA 版并尝试 CUDA；没有兼容 GPU/驱动或 CUDA 初始化失败时自动使用 CPU。
- SQLite 数据库、运行时和语音模型缓存均在解压目录生成，不带原电脑的数据库、学生信息、简历、音频或模型缓存。
- 首次启动时会下载语音模型，完成前请保持窗口打开。CPU 推理速度取决于目标电脑性能。
- 服务只绑定 `127.0.0.1`，用于目标电脑本机浏览器复测。

如果启动失败，保留 `logs/portable-*.err.txt` 与 `logs/portable-*.out.txt` 供排查。复测包含密钥，不要公开上传。
