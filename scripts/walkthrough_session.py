"""M3 贯通走查辅助：以指定学生身份完成一场真实文本训练会话。

用法：python scripts/walkthrough_session.py [user_id] [job_id] [mode]
输出 JSON：{sid, report_id, questions, answers, elapsed_s}
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

BASE = "http://127.0.0.1:8000"

ANSWER_POOL = [
    "我在学校系统学习过汽车理论与测试基础，做过CAN总线报文采集的小项目。使用CANoe搭建过仿真工程，分析过时间戳异常和丢包率问题，定位过一次报文丢失的节点。我认为智驾测试需要把场景用例设计和数据分析结合起来，我愿意从测试用例执行做起，逐步积累实车与台架经验。",
    "我用STAR结构说明：在课程项目中，我负责底盘信号的台架测试。背景是团队需要验证CAN信号在极限工况下的稳定性；我的任务是设计测试用例并记录数据；行动上我制定了正常、边界、异常三类工况，用CANoe记录并对比时间戳；结果是发现两处信号延迟超阈值并提交了报告，老师采纳后修正了采样配置。这段经历让我学会先定义判据再动手测试。",
    "三电方向我了解电池管理系统BMS的基本功能：SOC估算、均衡控制、高压安全。知道绝缘检测是高压安全的重要环节，回馈制动涉及电机控制器的能量回收策略。我希望通过岗位训练明确自己在BMS测试或VCU诊断方向的差距，按学习路径补齐UDS诊断和ISO 26262功能安全的基础知识。",
    "遇到不确定的问题时，我先复述问题确认理解，再拆解成已知部分和未知部分。例如被问到不熟悉的传感器标定，我会先说明我掌握的相关原理，再坦诚边界，最后给出我的验证思路，比如查阅器件手册设计小实验。我不会不懂装懂，测试岗位尤其需要如实标注不确定的结论。",
    "我的职业规划是先成为合格的智能驾驶测试工程师，两年内独立负责一个测试模块，包括用例设计、执行和问题闭环。长期希望向测试开发方向发展，做自动化测试框架。我知道这需要补齐Python编程和数据分析能力，我的计划是每季度完成一个实操小项目来验证学习成果。",
    "情景题：如果路测中发现偶发的感知误检，我会先保留现场数据不急于重启，记录发生时间、地点、天气和车速等上下文；然后回放数据对比多传感器输出，确认是单传感器异常还是融合层问题；再尝试在台架复现，统计复现率；最后按流程提交缺陷报告，附上数据片段和初步分析，推动研发定位。整个过程保持数据可追溯。",
]


def main() -> None:
    user_id = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    job_id = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    mode = sys.argv[3] if len(sys.argv) > 3 else "新生"

    started = time.monotonic()
    timeline = []
    with httpx.Client(timeout=180.0) as client:
        resp = client.post(f"{BASE}/api/sessions", json={"user_id": user_id, "job_id": job_id, "mode": mode})
        resp.raise_for_status()
        body = resp.json()
        sid = body["sid"]
        question = body["question"]
        print(f"session={sid} 首题 seq={question['seq']}")

        answer_idx = 0
        report_id = None
        while True:
            answer_text = ANSWER_POOL[answer_idx % len(ANSWER_POOL)]
            answer_idx += 1
            t0 = time.monotonic()
            resp = client.post(
                f"{BASE}/api/sessions/{sid}/answers/text",
                json={"answer_text": answer_text},
            )
            elapsed = round(time.monotonic() - t0, 1)
            resp.raise_for_status()
            result = resp.json()
            timeline.append(
                {"seq": question["seq"] if question else None,
                 "type": result.get("type"), "elapsed_s": elapsed}
            )
            print(f"  seq={question['seq'] if question else '-'} -> {result['type']} ({elapsed}s)")
            if result["type"] == "done":
                report_id = result["report_id"]
                break
            question = result.get("question")
            if question is None:
                raise RuntimeError(f"unexpected response without question: {result}")

    print(json.dumps({
        "sid": sid, "report_id": report_id,
        "timeline": timeline, "elapsed_s": round(time.monotonic() - started, 1),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
