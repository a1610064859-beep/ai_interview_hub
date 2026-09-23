"""ASR 服务（T5）：FunASR Paraformer 本地批处理。

ASR_PROVIDER 仅允许 funasr（config 层 Literal 锁定，配置其他值启动即失败）；
CUDA 初始化失败自动回退 CPU 并记 WARN（队长批准方案 A），CPU 也失败才抛 ASRUnavailableError（503）。
funasr 在首次加载模型时才导入，依赖缺失不影响本模块被其他生产代码导入。
"""
import asyncio
import logging
import os
import re
import threading
import time
import shutil
import tempfile
from concurrent.futures import Future
from pathlib import Path

from server.config import settings

logger = logging.getLogger(__name__)


class ASRUnavailableError(Exception):
    """ASR 基础设施不可用 → 503 ASR_UNAVAILABLE"""


# CJK 统一汉字：仅折叠两端均为该集合时的空白；英文/数字侧空格保留。
_CJK_CHAR_CLASS = r"\u4e00-\u9fff"
_CJK_INTER_SPACE = re.compile(
    rf"(?<=[{_CJK_CHAR_CLASS}])[ \t\r\n\u3000]+(?=[{_CJK_CHAR_CLASS}])"
)


def normalize_asr_text(text: str) -> str:
    """折叠 FunASR 常见的汉字间空白，保留英文词、数字及非 CJK–CJK 间隔。

    只处理 CJK（\\u4e00-\\u9fff）字符之间的一个或多个空白（含空格/制表/换行/全角空格）；
    不修改 validate_evidence，不在此函数处理文本答题路径。
    """
    if not text:
        return text
    return _CJK_INTER_SPACE.sub("", text)


def count_filler_words(text: str) -> int:
    """统计填充词（嗯|那个|就是|然后|这个）频次"""
    pattern = r"(嗯|那个|就是|然后|这个)"
    return len(re.findall(pattern, text))


_model = None
_model_lock = threading.Lock()


def _load_model():
    """进程内单例加载 Paraformer 模型。"""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            # funasr 1.4.x 的模型下载/读取实际走 modelscope，缓存位置由 MODELSCOPE_CACHE 决定；
            # 统一以 ASR_MODEL_CACHE_DIR 注入该变量，保证模型资产落在 E 盘指定目录（而非 C 盘默认缓存）。
            os.environ.setdefault("MODELSCOPE_CACHE", settings.asr_model_cache_dir)
            from funasr import AutoModel
        except ImportError as exc:
            raise ASRUnavailableError(f"funasr 未安装: {exc}") from exc

        try:
            _model = AutoModel(
                model=settings.asr_model_name,
                device=settings.asr_device,
                disable_update=True,
            )
        except Exception as exc:
            if settings.asr_device == "cuda":
                logger.warning("CUDA 初始化失败，自动回退 CPU: %s", exc)
                try:
                    _model = AutoModel(
                        model=settings.asr_model_name,
                        device="cpu",
                        disable_update=True,
                    )
                except Exception as cpu_exc:
                    raise ASRUnavailableError(
                        f"CUDA 与 CPU 均初始化失败: {cpu_exc}"
                    ) from cpu_exc
            else:
                raise ASRUnavailableError(f"ASR 模型初始化失败: {exc}") from exc
    return _model


_worker_lock = threading.Lock()


def service_status() -> dict:
    return {"enabled": settings.asr_enabled, "ready": _model is not None,
            "busy": _worker_lock.locked()}


async def _run_serial(work):
    """One owned job, no unbounded queue. Cancellation never releases a live worker."""
    if not _worker_lock.acquire(blocking=False):
        raise ASRUnavailableError("语音识别服务繁忙，请稍后重试")
    result = Future()
    def run():
        try:
            value = work()
        except BaseException as exc:
            _worker_lock.release()
            result.set_exception(exc)
        else:
            _worker_lock.release()
            result.set_result(value)
    try:
        threading.Thread(target=run, name="asr-worker", daemon=True).start()
    except BaseException:
        _worker_lock.release()
        raise
    pending = asyncio.wrap_future(result)
    # Retrieve late exceptions even if the HTTP waiter has timed out or disconnected.
    pending.add_done_callback(lambda f: None if f.cancelled() else f.exception())
    try:
        return await asyncio.wait_for(asyncio.shield(pending), settings.asr_timeout_s)
    except asyncio.TimeoutError as exc:
        raise ASRUnavailableError("ASR 转写超时，后台任务尚在结束，请稍后重试") from exc
    except ASRUnavailableError:
        raise
    except Exception as exc:
        raise ASRUnavailableError("ASR 转写失败，请稍后重试") from exc


async def warmup() -> None:
    started = time.perf_counter()
    try:
        await _run_serial(_load_model)
        logger.info("asr stage=warmup total_ms=%.1f", (time.perf_counter() - started) * 1000)
    except ASRUnavailableError:
        logger.warning("ASR 预热未完成；服务保留文本功能", exc_info=True)


async def transcribe_wav(wav_path: str) -> str:
    # The worker owns this copy until inference exits, independently of the request.
    if _worker_lock.locked():
        raise ASRUnavailableError("语音识别服务繁忙，请稍后重试")
    owned = tempfile.TemporaryDirectory(prefix="asr_worker_", dir=settings.asr_temp_dir or None)
    path = str(Path(owned.name) / "input.wav")
    shutil.copyfile(wav_path, path)
    entered = threading.Event()
    def infer():
        entered.set()
        begin = time.perf_counter()
        try:
            model = _load_model()
            loaded = time.perf_counter()
            result = model.generate(input=path)
            logger.info("asr stage=inference load_ms=%.1f infer_ms=%.1f",
                        (loaded - begin) * 1000, (time.perf_counter() - loaded) * 1000)
            return str(result[0].get("text", "") or "") if result else ""
        finally:
            owned.cleanup()
    try:
        raw = await _run_serial(infer)
        return normalize_asr_text(raw)
    except BaseException:
        # A rejected job never transfers ownership; a running job cleans itself.
        if not entered.is_set():
            owned.cleanup()
        raise
