import pytest
from decimal import Decimal, ROUND_HALF_UP
from unittest.mock import AsyncMock, patch

from server.services.scoring import (
    validate_evidence,
    calculate_dimension_average,
    calculate_overall,
    ScoringUnavailableError,
    score_interview,
    SingleDimensionScore,
    SingleScoringResult,
    compute_acoustic_fluency,
)


def test_evidence_validation_success():
    answers = [
        "我通常使用CANoe和CANalyzer排查汽车总线故障，首先确认硬件接线。",
        "遇到报文丢失时，我会分析时间戳和节点丢包率。",
    ]
    # 合规：长度 <= 25，且为某条回答的原文字面连续子串
    assert validate_evidence("使用CANoe和CANalyzer", answers) is True
    assert validate_evidence("分析时间戳和节点丢包率", answers) is True
    assert validate_evidence("硬件接线", answers) is True


def test_evidence_validation_failure():
    answers = [
        "我通常使用CANoe排查总线故障。",
        "遇到报文丢失时分析时间戳。",
    ]
    # 空白或空串
    assert validate_evidence("", answers) is False
    assert validate_evidence("   ", answers) is False
    assert validate_evidence(None, answers) is False
    # 超长 (> 25 字)
    long_text = "这是一段非常非常长的引用原话用于测试证据是否超过二十五个字符的严格限制标准"
    assert validate_evidence(long_text, answers) is False
    # 跨回答拼接（两句话各取一部分，但不是任一回答的连续子串）
    assert validate_evidence("排查总线故障遇到报文丢失", answers) is False
    # 凭空编造
    assert validate_evidence("精通Python多线程并发编程", answers) is False


def test_calculate_dimension_average_success():
    d1 = SingleDimensionScore(score=85.0, evidence="使用CANoe分析", reason="熟练掌握工具链")
    d2 = SingleDimensionScore(score=86.0, evidence="使用CANoe分析", reason="熟练掌握工具链")
    
    avg_score, evidence, reason = calculate_dimension_average(d1, d2)
    assert avg_score == 85.5
    assert evidence == "使用CANoe分析"
    assert reason == "熟练掌握工具链"


def test_calculate_dimension_average_rounding_half_up():
    # 85.25 -> 85.3 (Decimal ROUND_HALF_UP)
    d1 = SingleDimensionScore(score=85.2, evidence="使用CANoe分析", reason="熟练")
    d2 = SingleDimensionScore(score=85.3, evidence="使用CANoe分析", reason="熟练")
    avg_score, _, _ = calculate_dimension_average(d1, d2)
    assert avg_score == 85.3


def test_calculate_dimension_average_mismatch_or_none():
    d1 = SingleDimensionScore(score=85.0, evidence="使用CANoe分析", reason="熟练")
    d2 = None
    avg_score, evidence, reason = calculate_dimension_average(d1, d2)
    assert avg_score is None
    assert evidence is None
    assert "未获得通过校验的双次评分" in reason


def test_calculate_overall():
    # 有效维度均值
    dims = {
        "professional_match": {"score": 88.0},
        "logic_structure": {"score": 82.5},
        "expression_fluency": {"score": None},  # 文本模式缺失
        "job_competence": {"score": 83.5},
    }
    # (88.0 + 82.5 + 83.5) / 3 = 254.0 / 3 = 84.6666... -> 84.7
    overall = calculate_overall(dims)
    assert overall == 84.7

    # 全部为 None
    all_none_dims = {
        "professional_match": {"score": None},
        "logic_structure": {"score": None},
        "expression_fluency": {"score": None},
        "job_competence": {"score": None},
    }
    assert calculate_overall(all_none_dims) is None


@pytest.mark.anyio
async def test_score_interview_success():
    answers = [
        "我熟悉智能驾驶仿真测试，主要用CANoe排查总线。",
        "面对突发Bug会首先保护现场日志，其次抓取节点报文。",
    ]
    job_info = {
        "title": "智驾测试",
        "jd_digest": "负责车载总线与智驾系统测试",
        "terms": ["CANoe", "总线"],
    }

    mock_result_1 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="用CANoe排查总线", reason="掌握CANoe"),
        logic_structure=SingleDimensionScore(score=85.0, evidence="首先保护现场日志", reason="结构清晰"),
        job_competence=SingleDimensionScore(score=80.0, evidence="首先保护现场日志", reason="素养良好"),
        highlights=["测试技能扎实"],
        concerns=["深度还需加强"],
        improvement=["建议阅读更多规范"],
    )
    mock_result_2 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=88.0, evidence="用CANoe排查总线", reason="掌握CANoe"),
        logic_structure=SingleDimensionScore(score=85.0, evidence="首先保护现场日志", reason="结构清晰"),
        job_competence=SingleDimensionScore(score=82.0, evidence="首先保护现场日志", reason="素养良好"),
        highlights=["技能熟练"],
        concerns=["经验需积累"],
        improvement=["加强规范阅读"],
    )

    with patch("server.services.scoring.call_scoring_llm", AsyncMock(side_effect=[mock_result_1, mock_result_2])):
        final_report = await score_interview(answers=answers, job_info=job_info, mode="text")
        
        # 表达流畅度在文本模式必须为 None
        assert final_report["dimensions"]["expression_fluency"]["score"] is None
        assert final_report["dimensions"]["expression_fluency"]["evidence"] is None
        assert "文本模式" in final_report["dimensions"]["expression_fluency"]["reason"]

        # 专业匹配度 (90 + 88) / 2 = 89.0
        assert final_report["dimensions"]["professional_match"]["score"] == 89.0
        assert final_report["dimensions"]["professional_match"]["evidence"] == "用CANoe排查总线"

        # overall (89.0 + 85.0 + 81.0) / 3 = 85.0
        assert final_report["overall"] == 85.0
        assert len(final_report["highlights"]) > 0
        assert len(final_report["improvement"]) > 0


@pytest.mark.anyio
async def test_score_interview_infra_failure():
    answers = ["回答1"]
    job_info = {"title": "智驾测试", "jd_digest": "...", "terms": []}

    with patch("server.services.scoring.call_scoring_llm", AsyncMock(side_effect=Exception("LLM down"))):
        with pytest.raises(ScoringUnavailableError):
            await score_interview(answers=answers, job_info=job_info, mode="text")


def test_evidence_validation_exact_string_spaces():
    """复现阻断 2：证据检查和实际保存的字符串必须一致，长度和匹配针对原字符串"""
    answers = ["我通常使用CANoe排查总线故障。"]
    # 回答中只有"CANoe"，没有带首尾空格的" CANoe "，必须校验失败
    assert validate_evidence(" CANoe ", answers) is False
    assert validate_evidence("CANoe", answers) is True


def test_evidence_match_after_cjk_normalize_without_relaxing_validate():
    """T5-FIX：CJK 间隔折叠后，连续中文 evidence 可通过现有严格 validate_evidence；规则本身未放宽。"""
    from server.services.asr import normalize_asr_text

    raw_spaced = [
        "超 声 波 雷 达用于测距，我 们 使 用 CANoe 做 总 线 测 试",
        "坚 持 功 能 安 全 底 线",
    ]
    continuous_evidence = "超声波雷达"
    canoe_evidence = "使用 CANoe 做总线测试"
    safety_evidence = "功能安全底线"

    # 规范化前：连续中文不是字面子串 → 失败（复现 sid=5 冲突面）
    assert validate_evidence(continuous_evidence, raw_spaced) is False
    assert validate_evidence(safety_evidence, raw_spaced) is False

    normalized = [normalize_asr_text(a) for a in raw_spaced]
    assert normalized[0] == "超声波雷达用于测距，我们使用 CANoe 做总线测试"
    assert normalized[1] == "坚持功能安全底线"

    # 规范化后：同函数、同规则可通过
    assert validate_evidence(continuous_evidence, normalized) is True
    assert validate_evidence(canoe_evidence, normalized) is True
    assert validate_evidence(safety_evidence, normalized) is True

    # 严格性未放宽：超长、虚构、首尾空格仍失败
    too_long = "超声波雷达用于测距，我们使用 CANoe 做总线测试坚持"
    assert len(too_long) > 25
    assert validate_evidence(too_long, normalized) is False
    assert validate_evidence("精通Python并发", normalized) is False
    assert validate_evidence(" 超声波雷达", normalized) is False


@pytest.mark.anyio
async def test_score_interview_partial_dimensions_preserved():
    """逐维保留有效结果；重试后依然无效的维度置 None，不影响其余有效维度"""
    answers = ["我熟悉CANoe工具链", "具备安全红线意识"]
    job_info = {"title": "智驾测试", "jd_digest": "...", "terms": ["CANoe"]}

    # mock 结果中 logic_structure 证据无效（不在 answers 中）
    res1 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="熟悉CANoe", reason="掌握工具"),
        logic_structure=SingleDimensionScore(score=80.0, evidence="回答结构良好不存在于文本", reason="无效证据"),
        job_competence=SingleDimensionScore(score=85.0, evidence="具备安全红线意识", reason="素养好"),
        highlights=["亮点1"],
        concerns=[],
        improvement=["建议1"],
    )
    res2 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=86.0, evidence="熟悉CANoe", reason="掌握工具"),
        logic_structure=SingleDimensionScore(score=82.0, evidence="另一个凭空造的证据", reason="无效证据"),
        job_competence=SingleDimensionScore(score=85.0, evidence="具备安全红线意识", reason="素养好"),
        highlights=["亮点2"],
        concerns=[],
        improvement=["建议2"],
    )

    async def mock_chat(stage, messages, model):
        # 无论首次还是重试均返回含有无效维度的结果
        if "亮点2" in str(messages) or len(messages) > 1 and "professional_match(专业匹配度)" in str(messages):
            pass
        return res1 if "亮点1" not in str(messages) else res2

    # 使用 side_effect 支持 call 1 (首次+重试) 和 call 2 (首次+重试)
    with patch("server.services.scoring.chat_json", AsyncMock(side_effect=[res1, res1, res2, res2])):
        report = await score_interview(answers=answers, job_info=job_info, mode="text")
        # 专业匹配度 (90 + 86)/2 = 88.0，岗位素养 85.0 均保留
        assert report["dimensions"]["professional_match"]["score"] == 88.0
        assert report["dimensions"]["job_competence"]["score"] == 85.0
        # 逻辑结构因重试后仍无效置 None
        assert report["dimensions"]["logic_structure"]["score"] is None
        assert "未获得通过校验的双次评分" in report["dimensions"]["logic_structure"]["reason"]
        # overall 计算保留的两个有效维度均值 (88.0 + 85.0)/2 = 86.5
        assert report["overall"] == 86.5


@pytest.mark.anyio
async def test_score_interview_all_invalid_evidence_produces_null_report_not_503():
    """两次均无有效证据应生成全空报告，绝不能误判为基础设施 503"""
    answers = ["回答A", "回答B"]
    job_info = {"title": "智驾测试", "jd_digest": "...", "terms": []}

    res_all_invalid = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="假证据1", reason="r1"),
        logic_structure=SingleDimensionScore(score=80.0, evidence="假证据2", reason="r2"),
        job_competence=SingleDimensionScore(score=85.0, evidence="假证据3", reason="r3"),
        highlights=[],
        concerns=[],
        improvement=["建议多练习"],
    )

    with patch("server.services.scoring.chat_json", AsyncMock(side_effect=[res_all_invalid, res_all_invalid, res_all_invalid, res_all_invalid])):
        # 不能抛出 ScoringUnavailableError
        report = await score_interview(answers=answers, job_info=job_info, mode="text")
        assert report["overall"] is None
        assert report["dimensions"]["professional_match"]["score"] is None
        assert report["dimensions"]["logic_structure"]["score"] is None
        assert report["dimensions"]["job_competence"]["score"] is None
        assert report["dimensions"]["expression_fluency"]["score"] is None


@pytest.mark.anyio
async def test_score_interview_retry_evidence_correction_success():
    """测试 evidence 不合规时针对性重试 1 次：第一次证据无效，第二次一次性修正成功"""
    answers = ["我通常使用CANoe分析报文时间戳", "具备极强的安全底线意识"]
    job_info = {"title": "智驾测试", "jd_digest": "负责车载总线测试", "terms": ["CANoe"]}

    # 调用 1 首次：logic_structure 证据为无效的"凭空编造的逻辑"，professional_match 证据有效
    res1_attempt0 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="使用CANoe分析报文", reason="掌握工具"),
        logic_structure=SingleDimensionScore(score=80.0, evidence="凭空编造的逻辑", reason="待修正"),
        job_competence=SingleDimensionScore(score=85.0, evidence="具备极强的安全底线意识", reason="素养好"),
        highlights=["亮点1"],
        concerns=[],
        improvement=["建议1"],
    )
    # 调用 1 重试：logic_structure 证据被修正为候选人原话"分析报文时间戳"（有效！）
    res1_attempt1 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="使用CANoe分析报文", reason="掌握工具"),
        logic_structure=SingleDimensionScore(score=82.0, evidence="分析报文时间戳", reason="结构清晰"),
        job_competence=SingleDimensionScore(score=85.0, evidence="具备极强的安全底线意识", reason="素养好"),
        highlights=["亮点1"],
        concerns=[],
        improvement=["建议1"],
    )

    # 调用 2：全维度一次性成功
    res2 = SingleScoringResult(
        professional_match=SingleDimensionScore(score=88.0, evidence="使用CANoe分析报文", reason="掌握工具"),
        logic_structure=SingleDimensionScore(score=84.0, evidence="分析报文时间戳", reason="结构清晰"),
        job_competence=SingleDimensionScore(score=85.0, evidence="具备极强的安全底线意识", reason="素养好"),
        highlights=["亮点2"],
        concerns=[],
        improvement=["建议2"],
    )

    correction_prompts_seen = []

    async def mock_chat_json(stage, messages, model):
        # 如果 messages 长度大于 2，说明是追加了修正提示的重试
        if len(messages) > 2:
            correction_prompts_seen.append(messages[-1]["content"])
            return res1_attempt1
        # 首次调用：给调用 1 返回含错误的结果，给调用 2 返回全正确的结果
        # 判断是调用 1 还是调用 2：调用 1 第一次遇到，返回 res1_attempt0
        if not hasattr(mock_chat_json, "call1_done"):
            mock_chat_json.call1_done = True
            return res1_attempt0
        return res2

    with patch("server.services.scoring.chat_json", mock_chat_json):
        report = await score_interview(answers=answers, job_info=job_info, mode="text")

        # 验证修正重试发生且一次性指明了无效维度
        assert len(correction_prompts_seen) == 1
        assert "logic_structure(逻辑结构)" in correction_prompts_seen[0]

        # 验证重试修正后，logic_structure 成功保留并计算均值 (82.0 + 84.0)/2 = 83.0
        assert report["dimensions"]["logic_structure"]["score"] == 83.0
        assert report["dimensions"]["logic_structure"]["evidence"] == "分析报文时间戳"
        assert report["dimensions"]["professional_match"]["score"] == 89.0
        assert report["dimensions"]["job_competence"]["score"] == 85.0
        # overall: (89.0 + 83.0 + 85.0)/3 = 85.666... -> 85.7
        assert report["overall"] == 85.7


def test_compute_acoustic_fluency_normal_range_full_score():
    """B：正常语速区间内（220-280字/分）满分，结果确定且与输入顺序无关"""
    samples = [
        {"duration_s": 30.0, "wpm": 250.0, "pause_cnt": 2, "filler_cnt": 1},
        {"duration_s": 30.0, "wpm": 260.0, "pause_cnt": 1, "filler_cnt": 1},
    ]
    result = compute_acoustic_fluency(samples)
    assert result["score"] == 100.0
    assert 0.0 <= result["score"] <= 100.0
    assert result["evidence"] is None  # 声学数字不得冒充原文引用
    assert "语速" in result["reason"]
    assert "停顿" in result["reason"]
    assert "填充词" in result["reason"]
    # 确定性：与输入顺序无关
    assert result == compute_acoustic_fluency(list(reversed(samples)))


def test_compute_acoustic_fluency_penalizes_deviation_not_constant():
    """B：评分确实随 wpm/pause_cnt/filler_cnt 变化，不是固定常量（正常区间220-280）"""
    base = {"duration_s": 60.0, "wpm": 250.0, "pause_cnt": 3, "filler_cnt": 2}
    normal = compute_acoustic_fluency([base])["score"]
    too_fast = compute_acoustic_fluency([{**base, "wpm": 330.0}])["score"]        # (330-280)*0.2=10
    too_slow = compute_acoustic_fluency([{**base, "wpm": 180.0}])["score"]        # (220-180)*0.2=8
    pause_heavy = compute_acoustic_fluency([{**base, "pause_cnt": 12}])["score"]  # (12-6)*2=12
    filler_heavy = compute_acoustic_fluency([{**base, "filler_cnt": 15}])["score"]  # (15-5)*3=30

    assert normal == 100.0
    assert too_fast == 90.0
    assert too_slow == 92.0
    assert pause_heavy == 88.0
    assert filler_heavy == 70.0
    assert len({normal, too_fast, too_slow, pause_heavy, filler_heavy}) == 5


def test_compute_acoustic_fluency_reason_contains_actual_stats():
    """B：reason 必须由实际统计值生成"""
    result = compute_acoustic_fluency(
        [{"duration_s": 60.0, "wpm": 330.0, "pause_cnt": 3, "filler_cnt": 2}]
    )
    assert "语速330字/分" in result["reason"]
    assert "扣10.0分" in result["reason"]
    assert result["evidence"] is None


def test_compute_acoustic_fluency_missing_data_returns_null():
    """C：声学数据缺失不得虚构评分"""
    assert compute_acoustic_fluency([])["score"] is None
    assert compute_acoustic_fluency(None)["score"] is None
    result = compute_acoustic_fluency(
        [{"duration_s": 60.0, "wpm": None, "pause_cnt": 2, "filler_cnt": 1}]
    )
    assert result["score"] is None
    assert result["evidence"] is None
    assert "声学数据不足" in result["reason"]


@pytest.mark.anyio
async def test_score_interview_voice_mode_computes_acoustic_fluency():
    """B：语音模式表达流畅度由声学规则量化，参与 overall"""
    answers = ["我熟悉智能驾驶仿真测试，主要用CANoe排查总线。"]
    job_info = {"title": "智驾测试", "jd_digest": "...", "terms": ["CANoe"]}
    mock_result = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="熟悉智能驾驶仿真测试", reason="掌握"),
        logic_structure=SingleDimensionScore(score=85.0, evidence="熟悉智能驾驶仿真测试", reason="清晰"),
        job_competence=SingleDimensionScore(score=80.0, evidence="熟悉智能驾驶仿真测试", reason="良好"),
        highlights=[], concerns=[], improvement=[],
    )
    with patch("server.services.scoring.call_scoring_llm", AsyncMock(side_effect=[mock_result, mock_result])):
        report = await score_interview(
            answers=answers, job_info=job_info, mode="voice",
            acoustic_samples=[{"duration_s": 60.0, "wpm": 250.0, "pause_cnt": 3, "filler_cnt": 2}],
        )
    fluency = report["dimensions"]["expression_fluency"]
    assert fluency["score"] == 100.0
    assert fluency["evidence"] is None
    assert "语速250字/分" in fluency["reason"]
    # overall 含 fluency：(90.0 + 85.0 + 80.0 + 100.0)/4 = 88.75 -> 88.8
    assert report["overall"] == 88.8


@pytest.mark.anyio
async def test_score_interview_voice_mode_missing_acoustics_null_overall_excludes_fluency():
    """C：语音模式声学缺失 → fluency null，overall 只按其他有效维度计算，不补零"""
    answers = ["我熟悉智能驾驶仿真测试，主要用CANoe排查总线。"]
    job_info = {"title": "智驾测试", "jd_digest": "...", "terms": ["CANoe"]}
    mock_result = SingleScoringResult(
        professional_match=SingleDimensionScore(score=90.0, evidence="熟悉智能驾驶仿真测试", reason="掌握"),
        logic_structure=SingleDimensionScore(score=85.0, evidence="熟悉智能驾驶仿真测试", reason="清晰"),
        job_competence=SingleDimensionScore(score=80.0, evidence="熟悉智能驾驶仿真测试", reason="良好"),
        highlights=[], concerns=[], improvement=[],
    )
    with patch("server.services.scoring.call_scoring_llm", AsyncMock(side_effect=[mock_result, mock_result])):
        report = await score_interview(answers=answers, job_info=job_info, mode="voice", acoustic_samples=[])
    fluency = report["dimensions"]["expression_fluency"]
    assert fluency["score"] is None
    assert fluency["evidence"] is None
    assert "声学数据不足" in fluency["reason"]
    # overall 只算其他三维：(90+85+80)/3 = 85.0（fluency 不补零参与）
    assert report["overall"] == 85.0
