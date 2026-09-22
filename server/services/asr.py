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


async def transcribe_wav(wav_path: str) -> str:
    """对 16kHz wav 执行本地批处理转写；推理在线程池执行，超时/异常统一 ASRUnavailableError。"""

    def _infer() -> str:
        model = _load_model()
        result = model.generate(input=wav_path)
        if not result:
            return ""
        return str(result[0].get("text", "") or "")

    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(_infer), timeout=settings.asr_timeout_s
        )
    except asyncio.TimeoutError as exc:
        raise ASRUnavailableError("ASR 转写超时") from exc
    except ASRUnavailableError:
        raise
    except Exception as exc:
        raise ASRUnavailableError(f"ASR 转写失败: {exc}") from exc
    # 落库前规范化：wpm/filler 与评分 evidence 共用同一文本
    return normalize_asr_text(raw)
