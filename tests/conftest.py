"""Pytest 全局隔离夹具：在任何 server 模块导入之前，把数据库/音频/日志路径指向临时目录。

关键机制：conftest.py 顶层代码先于测试模块的 import 执行；而 server/db.py 在 import
时就根据 settings.database_url 创建 engine，server/config.py 的 Settings() 也在 import
时实例化。因此必须在这里直接设置 os.environ（env 变量优先级高于 .env 文件），
才能让 engine 落在临时库上，避免跑一次 pytest 就清空 data/interview.db 演示数据。
"""
import os
import tempfile

# 单次 pytest 会话共享一个临时目录；不主动清理，便于失败后排查
_TMP_DIR = tempfile.mkdtemp(prefix="aihub-test-")

# sqlite URL 统一用正斜杠，兼容 Windows 盘符路径（sqlite:///C:/...）
_DB_PATH = os.path.join(_TMP_DIR, "test.db").replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["AUTH_REQUIRED"] = "false"

os.environ["TTS_OUTPUT_DIR"] = os.path.join(_TMP_DIR, "audio")
os.environ["LLM_USAGE_LOG_PATH"] = os.path.join(_TMP_DIR, "logs", "llm_usage.jsonl")
os.environ["ASR_TEMP_DIR"] = os.path.join(_TMP_DIR, "asr_tmp")

# 预建目录，避免依赖各服务首写时的 mkdir 行为
for _d in (
    os.environ["TTS_OUTPUT_DIR"],
    os.path.dirname(os.environ["LLM_USAGE_LOG_PATH"]),
    os.environ["ASR_TEMP_DIR"],
):
    os.makedirs(_d, exist_ok=True)
