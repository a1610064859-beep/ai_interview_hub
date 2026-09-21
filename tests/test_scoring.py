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


@pytest.mark.anyio
async def test_score_interview_partial_dimensions_preserved():
    """复现阻断 1：逐维保留有效结果；某维缺失/证据无效仅影响该维，不丢弃整次评分"""
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

    with patch("server.services.scoring.chat_json", AsyncMock(side_effect=[res1, res2])):
        report = await score_interview(answers=answers, job_info=job_info, mode="text")
        # 专业匹配度 (90 + 86)/2 = 88.0，岗位素养 85.0 均保留
        assert report["dimensions"]["professional_match"]["score"] == 88.0
        assert report["dimensions"]["job_competence"]["score"] == 85.0
        # 逻辑结构因证据无效置 None，不能使整个报告失败
        assert report["dimensions"]["logic_structure"]["score"] is None
        assert "未获得通过校验的双次评分" in report["dimensions"]["logic_structure"]["reason"]
        # overall 计算保留的两个有效维度均值 (88.0 + 85.0)/2 = 86.5
        assert report["overall"] == 86.5


@pytest.mark.anyio
async def test_score_interview_all_invalid_evidence_produces_null_report_not_503():
    """复现阻断 1：两次均无有效证据应生成全空报告，绝不能误判为基础设施 503"""
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

    with patch("server.services.scoring.chat_json", AsyncMock(side_effect=[res_all_invalid, res_all_invalid])):
        # 不能抛出 ScoringUnavailableError
        report = await score_interview(answers=answers, job_info=job_info, mode="text")
        assert report["overall"] is None
        assert report["dimensions"]["professional_match"]["score"] is None
        assert report["dimensions"]["logic_structure"]["score"] is None
        assert report["dimensions"]["job_competence"]["score"] is None
        assert report["dimensions"]["expression_fluency"]["score"] is None

