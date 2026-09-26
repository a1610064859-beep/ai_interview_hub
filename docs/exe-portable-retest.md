# 智驾未来·AI面试仓：免安装复测包

适用于 Windows 10/11 x64。解压完整 ZIP 到可写目录，双击 `AIInterviewHub.exe`。启动器会启动后端和网页，并打开 `http://127.0.0.1:3000/`。保持启动器窗口开启；按 Enter 结束两个服务。

包内已含 Python、Node.js、FFmpeg、应用依赖与中文语音识别模型。目标电脑不需要另外安装运行库，也不需要 LM Studio。首次启动无需下载这些依赖。大模型 API、edge-tts 语音合成仍需联网。CUDA 加速需要兼容的 NVIDIA 显卡与驱动；不可用时语音识别自动回退 CPU。

如需先检查包内运行文件，打开命令提示符执行 `AIInterviewHub.exe --check`。成功时会显示 `Bundled runtime and speech model are ready.`。

请将 **整个目录** 一起保留，不要单独复制 EXE。程序需要在可写目录生成 SQLite 数据库和日志；不包含打包电脑的学生数据、简历或录音。包内 `.env` 含有经授权用于复测的个人 API 密钥，仅交付给可信测试者。更换密钥后直接修改解压目录中的 `.env`。

如果启动失败，请检查 `logs/portable-api.err.txt`、`logs/portable-web.err.txt`。如果 8000 或 3000 端口已被占用，先关闭旧服务再启动本程序。
