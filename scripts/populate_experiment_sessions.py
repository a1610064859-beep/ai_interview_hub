"""Populate experiment candidates with completed sessions and reports in interview.db.

Ensures every experiment student (users 5..54) and demo users (3, 4, 55) has:
1. Valid resume_storage_key pointing to a patched docx resume with photo & job requirements.
2. Completed sessions and reports for Job 1 (text and voice cohorts).
3. Realistic varied scores so sorting and radar charts display clearly.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from server.db import SessionLocal
from server.models import Job, Report, Session, User

RANDOM_SEEDS = [
    # (prof, logic, voice_fluency, comp, highlight, concern, improve)
    (88.0, 85.0, 86.0, 84.0, "熟悉CAN总线与诊断协议", "高阶算法推导需深化", "多参与实车标定实践"),
    (92.0, 90.0, 91.0, 89.0, "熟练掌握CANoe/CANalyzer工具链", "极限工况经验较少", "建议拓展ISO 26262标准学习"),
    (78.0, 82.0, 80.0, 79.0, "具备规范的测试用例编写能力", "自动化脚本编写稍弱", "加强Python测试脚本开发"),
    (84.0, 79.0, 83.0, 81.0, "熟悉HIL台架测试与故障注入", "实车偶发故障排查略显生疏", "多积累Corner Case处理经验"),
    (95.0, 93.0, 94.0, 92.0, "实车路测与底盘电子测试经验丰富", "报告书面表达可进一步精简", "保持技术敏感度，跟踪前沿法规"),
    (72.0, 74.0, 75.0, 73.0, "基础测试流程掌握规范", "对智能驾驶系统架构理解偏浅", "系统学习智能网联汽车电子电气架构"),
    (81.0, 86.0, 82.0, 80.0, "逻辑结构清晰，STAR陈述完整", "传感器底层原理掌握较基础", "加强毫米波雷达与相机数据流理解"),
    (89.0, 87.0, 88.0, 88.0, "动力总成与三电系统测试知识扎实", "软件回归测试经验较少", "拓展CI/CD自动化测试管线应用"),
    (76.0, 78.0, 77.0, 75.0, "动手能力强，实训接线排查严谨", "表达略有冗长，需提升精炼度", "多练习结构化技术沟通"),
    (90.0, 92.0, 89.0, 91.0, "测试规范性高，安全意识强", "实车高速场景测试相对较少", "增加封闭场地高速避障实训"),
]


def populate():
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == 1).first()
        if not job:
            print("Job 1 not found!")
            return

        # 1. Update users 3, 4, 55 with unique student_no
        u4 = db.query(User).filter(User.id == 4).first()
        if u4:
            u4.student_no = "DEMO-STU-004"
            u4.name_masked = "张*华"
            u4.education_level = "中职"
            u4.school_tier = "中职/技校"
            u4.resume_storage_key = "8361e478485f42eca79c6e5376827b14.docx"
            u4.resume_original_name = "张小华_中职_简历.docx"

        u55 = db.query(User).filter(User.id == 55).first()
        if u55:
            u55.student_no = "DEMO-STU-055"
            u55.name_masked = "李*明"
            u55.education_level = "高职/大专"
            u55.school_tier = "高职/大专"
            u55.resume_storage_key = "033fb8c3a95049b2890f4ad4ee705755.docx"
            u55.resume_original_name = "李明_高职大专_简历.docx"

        u3 = db.query(User).filter(User.id == 3).first()
        if u3:
            u3.student_no = "DEMO-STU-003"
            u3.name_masked = "王*强"
            u3.education_level = "本科"
            u3.school_tier = "普通本科"
            u3.resume_storage_key = "ae7f064e5050435991df6cf8b57b0d03.docx"
            u3.resume_original_name = "王志强_本科_简历.docx"

        db.commit()

        # 2. Check existing sessions for experiment users
        exp_users = db.query(User).filter(User.id.between(5, 54), User.role == "student").all()
        print(f"Found {len(exp_users)} experiment students in DB.")

        base_time = datetime(2026, 9, 25, 9, 0, 0)
        created_sessions = 0
        created_reports = 0

        for idx, u in enumerate(exp_users):
            seed_data = RANDOM_SEEDS[idx % len(RANDOM_SEEDS)]
            # Add small random perturbation based on user id
            offset = ((u.id * 17) % 15) - 7  # -7 to +7
            prof_score = round(min(98.0, max(60.0, seed_data[0] + offset * 0.8)), 1)
            logic_score = round(min(98.0, max(60.0, seed_data[1] + offset * 0.7)), 1)
            voice_score = round(min(98.0, max(60.0, seed_data[2] + offset * 0.6)), 1)
            comp_score = round(min(98.0, max(60.0, seed_data[3] + offset * 0.9)), 1)

            # Check if user already has completed session for job 1
            existing = db.query(Session).filter(
                Session.user_id == u.id,
                Session.job_id == 1,
                Session.status == "completed"
            ).first()

            if not existing:
                # Create text session
                sess_time = base_time + timedelta(hours=idx * 2, minutes=(idx * 13) % 60)
                sess_text = Session(
                    user_id=u.id,
                    job_id=1,
                    mode="毕业生",
                    started_at=sess_time,
                    status="completed",
                    input_mode="text",
                )
                db.add(sess_text)
                db.flush()
                created_sessions += 1

                overall_text = round((prof_score + logic_score + comp_score) / 3.0, 1)
                rep_text = Report(
                    session_id=sess_text.id,
                    scoring_version="v1",
                    overall=overall_text,
                    dimensions_json={
                        "professional_match": {
                            "score": prof_score,
                            "evidence": f"熟练掌握{seed_data[4][:12]}",
                            "reason": f"在专业测试技能测试中表现稳定，{seed_data[4]}",
                        },
                        "logic_structure": {
                            "score": logic_score,
                            "evidence": "运用STAR原则条理清晰地阐述项目",
                            "reason": "结构严谨，因果分析明确",
                        },
                        "expression_fluency": {
                            "score": None,
                            "evidence": None,
                            "reason": "文本模式未评估语音流畅度",
                        },
                        "job_competence": {
                            "score": comp_score,
                            "evidence": "态度积极，具备团队协作与责任心",
                            "reason": "展现良好的职业道德与工程素养",
                        },
                    },
                    highlights_json=[seed_data[4], "回答条理清晰完整", "具备规范的工程测试素养"],
                    concerns_json=[seed_data[5]],
                    improvement_json=[seed_data[6]],
                )
                db.add(rep_text)
                created_reports += 1

                # For half the users, also create a voice session so voice cohort has rich data
                if idx % 2 == 0:
                    voice_time = sess_time + timedelta(days=1, hours=3)
                    sess_voice = Session(
                        user_id=u.id,
                        job_id=1,
                        mode="毕业生",
                        started_at=voice_time,
                        status="completed",
                        input_mode="voice",
                    )
                    db.add(sess_voice)
                    db.flush()
                    created_sessions += 1

                    overall_voice = round((prof_score + logic_score + voice_score + comp_score) / 4.0, 1)
                    rep_voice = Report(
                        session_id=sess_voice.id,
                        scoring_version="v1",
                        overall=overall_voice,
                        dimensions_json={
                            "professional_match": {
                                "score": prof_score,
                                "evidence": f"熟练掌握{seed_data[4][:12]}",
                                "reason": f"专业知识匹配度高，{seed_data[4]}",
                            },
                            "logic_structure": {
                                "score": logic_score,
                                "evidence": "回答重点突出，逻辑清晰连贯",
                                "reason": "条理性好，表述完整",
                            },
                            "expression_fluency": {
                                "score": voice_score,
                                "evidence": "语速适中（约245字/分），停顿平稳",
                                "reason": "语音语调自然，无多余语气词",
                            },
                            "job_competence": {
                                "score": comp_score,
                                "evidence": "工程规范严谨，团队协作意愿高",
                                "reason": "符合智能汽车行业岗位综合素养要求",
                            },
                        },
                        highlights_json=[seed_data[4], "语音语速平稳流畅", "表达自信专业"],
                        concerns_json=[seed_data[5]],
                        improvement_json=[seed_data[6]],
                    )
                    db.add(rep_voice)
                    created_reports += 1

        db.commit()
        print(f"Successfully committed! Created {created_sessions} sessions and {created_reports} reports.")
    finally:
        db.close()


if __name__ == "__main__":
    populate()
