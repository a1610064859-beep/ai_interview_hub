"""
为 50 个实验样本 DOCX 补充随机求职要求与求职照片。
1. 写入 word/media/image1.jpg 并建立 drawing 关联，使前端简历能够直接展示候选人照片；
2. 依据各候选人的学历与专业方向，随机生成包含五大维度的真实求职要求；
3. 同步写入 data/experiment_resumes/、data/experiment_resumes_50.zip 与 live 数据库目录 data/resumes/。
"""

import io
import random
import re
import sqlite3
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PHOTO_PATH = ROOT / "data" / "experiment_resumes" / "EXP260925A-002-photo.jpg"
EXP_DIR = ROOT / "data" / "experiment_resumes"
RESUMES_DIR = ROOT / "data" / "resumes"
ZIP_PATH = ROOT / "data" / "experiment_resumes_50.zip"
DB_PATH = ROOT / "data" / "interview.db"

PHOTO_BYTES = PHOTO_PATH.read_bytes()

DRAWING_P = (
    '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
    '<w:r><w:drawing>'
    '<wp:inline xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<wp:extent cx="1007999" cy="1260000"/>'
    '<wp:docPr id="1" name="Picture 1"/>'
    '<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
    '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic><pic:nvPicPr>'
    '<pic:cNvPr id="0" name="photo.jpg"/><pic:cNvPicPr/>'
    '</pic:nvPicPr>'
    '<pic:blipFill>'
    '<a:blip r:embed="rId10"/>'
    '<a:stretch><a:fillRect/></a:stretch>'
    '</pic:blipFill>'
    '<pic:spPr>'
    '<a:xfrm><a:off x="0" y="0"/><a:ext cx="1007999" cy="1260000"/></a:xfrm>'
    '<a:prstGeom prst="rect"/>'
    '</pic:spPr>'
    '</pic:pic></a:graphicData></a:graphic>'
    '</wp:inline></w:drawing></w:r></w:p>'
)

OVERTIME_WILLINGNESS_POOL = [
    "加班意愿：配合整车研发交付节奏，接受适度项目攻关加班与试验场跟车测试排班。",
    "加班意愿：可接受阶段性封闭测试加班，日常测试期希望保持规律作息与双休。",
    "加班意愿：服从技术团队排班要求，能配合夜间道路数据采集与回灌测试排班。",
    "加班意愿：希望工作时间相对规范，按国家法定节假日休息，遇重大新车发布可配合攻坚。",
    "加班意愿：能适应新能源汽车产业研发节奏，可接受阶段性出差与试验台架轮值排班。",
    "加班意愿：不接受无意义的长期疲劳加班，重大节点测试与版本冲刺期服从统筹安排。",
    "加班意愿：可接受外场试验与整车标定期间的项目制弹性工作制，平时注重工作效率。",
    "加班意愿：愿意配合团队完成各阶段实车测试任务，期望周末能保证基本休息时间。",
]

OVERTIME_COMPENSATION_POOL = [
    "加班费 / 补偿：依法足额发放加班工资，并在加班前明确排班通知。",
    "加班费 / 补偿：按照国家法定标准提供加班补贴或安排对等调休。",
    "加班费 / 补偿：支持依法调休或发放加班费，希望有规范透明的考勤记录与补贴机制。",
    "加班费 / 补偿：重大测试攻坚期间依法享有项目津贴及调休保障。",
    "加班费 / 补偿：服从公司统一的考勤与工时管理制度，按规定结算加班补偿。",
    "加班费 / 补偿：依劳动法规执行，加班计入有效工时并按比例折算调休或补贴。",
]

SALARY_POOL_BY_EDU = {
    "中职": [
        "期望薪资：税前 4500–5500 元/月，可结合实际岗位要求与试用期表现面议。",
        "期望薪资：税前 5000–6000 元/月，希望公司提供工作餐或住宿补贴。",
        "期望薪资：税前 4800–5800 元/月，愿从基础台架测试做起，注重技能成长。",
    ],
    "高职/大专": [
        "期望薪资：税前 5500–7000 元/月，可结合实际职责与试用期表现协商。",
        "期望薪资：税前 6000–7500 元/月，希望有完善的五险一金及技能津贴。",
        "期望薪资：税前 6500–8000 元/月，愿在智能汽车测试一线深耕技术。",
        "期望薪资：税前 5800–7200 元/月，接受多工种轮岗，期望有季度考核绩效。",
    ],
    "本科": [
        "期望薪资：税前 7000–9000 元/月，可结合岗位定级与技术能力协商。",
        "期望薪资：税前 8000–10000 元/月，希望有年终绩效奖金与项目分红。",
        "期望薪资：税前 7500–9500 元/月，注重技术研发与标定实操，五险一金规范缴纳。",
        "期望薪资：税前 8500–11000 元/月，期望技术路线长期发展，岗位职责明确。",
    ],
    "硕士": [
        "期望薪资：税前 11000–14000 元/月，具体可结合科研成果与岗位职责协商。",
        "期望薪资：税前 12000–16000 元/月，期望参与核心算法评测与测试工具链开发。",
        "期望薪资：税前 10000–13500 元/月，希望有技术创新奖励和清晰的职级通道。",
    ],
    "博士": [
        "期望薪资：税前 16000–22000 元/月，期望主导前瞻智驾算法评测体系建设。",
        "期望薪资：税前 18000–25000 元/月，结合科研项目经历与专家定级协商。",
    ],
}

LOCATION_POOL = [
    "工作地点：上海（嘉定汽车城或临港研发中心），接受线下全职到岗。",
    "工作地点：合肥（经开区或新桥智能电动汽车产业园），接受现场办公。",
    "工作地点：苏州/昆山，可接受长三角区域内协同研发与试验场驻点。",
    "工作地点：武汉（车谷经开区智能网联试验区），希望线下到岗。",
    "工作地点：芜湖/南京，接受阶段性派驻整车厂实车测试与台架联调。",
    "工作地点：江浙沪核心产业园区优先，接受主机厂与试验基地现场办公。",
    "工作地点：常州/无锡智能制造基地，接受实车场地测试与线下出勤。",
]

OTHER_REQUIREMENTS_POOL = [
    "其他要求：希望有资深工程师一对一带教，能在智驾实车与台架测试中快速成长。",
    "其他要求：期望从事智能网联汽车测试一线岗位，有明确的技术职级晋升通道。",
    "其他要求：希望团队技术交流氛围活跃，严格遵循测试规范与试验安全操作规程。",
    "其他要求：期望公司提供员工宿舍或过渡期租房补贴，便于入职后快速投入工作。",
    "其他要求：愿从助理测试工程师做起，踏实积累实车路测、数据回灌与故障排查经验。",
    "其他要求：希望岗位职责、KPI 指标与技术培训体系健全透明。",
    "其他要求：期望有接触前沿整车电子电气架构和智驾测试工具链的实践机会。",
]


def get_user_education_map() -> dict[str, str]:
    if not DB_PATH.exists():
        return {}
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    rows = cur.execute("select student_no, education_level, resume_storage_key from users where student_no is not null").fetchall()
    edu_map = {}
    key_map = {}
    for sno, edu, key in rows:
        edu_map[sno] = edu or "高职/大专"
        if key:
            key_map[sno] = key
    con.close()
    return edu_map, key_map


def patch_docx(docx_bytes: bytes, sno: str, edu: str) -> bytes:
    rng = random.Random(f"EXP-RAND-{sno}")
    overtime_will = rng.choice(OVERTIME_WILLINGNESS_POOL)
    overtime_comp = rng.choice(OVERTIME_COMPENSATION_POOL)
    salary_pool = SALARY_POOL_BY_EDU.get(edu, SALARY_POOL_BY_EDU["高职/大专"])
    salary = rng.choice(salary_pool)
    loc = rng.choice(LOCATION_POOL)
    other = rng.choice(OTHER_REQUIREMENTS_POOL)

    in_buf = io.BytesIO(docx_bytes)
    out_buf = io.BytesIO()

    with zipfile.ZipFile(in_buf, "r") as zin, zipfile.ZipFile(out_buf, "w") as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == "word/document.xml":
                xml = content.decode("utf-8")
                # Insert photo drawing after title paragraph if drawing not yet present
                if "<w:drawing>" not in xml:
                    first_p_end = xml.find("</w:p>")
                    if first_p_end != -1:
                        first_p_end += len("</w:p>")
                        xml = xml[:first_p_end] + DRAWING_P + xml[first_p_end:]

                # Replace or append求职要求
                req_heading_pattern = r"<w:p[ >][^<]*<w:r[ >][^<]*(?:<w:rPr>.*?</w:rPr>)?[^<]*<w:t>求职要求</w:t>.*?</w:p>"
                match = re.search(req_heading_pattern, xml)
                new_req_xml = (
                    "<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>求职要求</w:t></w:r></w:p>"
                    f"<w:p><w:r><w:t>{overtime_will}</w:t></w:r></w:p>"
                    f"<w:p><w:r><w:t>{overtime_comp}</w:t></w:r></w:p>"
                    f"<w:p><w:r><w:t>{salary}</w:t></w:r></w:p>"
                    f"<w:p><w:r><w:t>{loc}</w:t></w:r></w:p>"
                    f"<w:p><w:r><w:t>{other}</w:t></w:r></w:p>"
                )
                if match:
                    # from match start to </w:body> or <w:sectPr
                    sect_pos = xml.find("<w:sectPr", match.start())
                    if sect_pos != -1:
                        xml = xml[: match.start()] + new_req_xml + xml[sect_pos:]
                    else:
                        body_end = xml.rfind("</w:body>")
                        if body_end != -1:
                            xml = xml[: match.start()] + new_req_xml + xml[body_end:]
                else:
                    # append before <w:sectPr
                    sect_pos = xml.find("<w:sectPr")
                    if sect_pos != -1:
                        xml = xml[:sect_pos] + new_req_xml + xml[sect_pos:]
                    else:
                        body_end = xml.rfind("</w:body>")
                        if body_end != -1:
                            xml = xml[:body_end] + new_req_xml + xml[body_end:]

                content = xml.encode("utf-8")
            elif item.filename == "word/_rels/document.xml.rels":
                rels = content.decode("utf-8")
                if "rId10" not in rels:
                    rels = rels.replace(
                        "</Relationships>",
                        '<Relationship Id="rId10" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.jpg"/></Relationships>',
                    )
                content = rels.encode("utf-8")
            elif item.filename == "[Content_Types].xml":
                types = content.decode("utf-8")
                if 'Extension="jpg"' not in types:
                    types = types.replace(
                        "<Types ",
                        '<Types ><Default Extension="jpg" ContentType="image/jpeg"/>',
                    )
                content = types.encode("utf-8")
            elif item.filename == "word/media/image1.jpg":
                continue

            # write back item
            zout.writestr(item, content)

        # write photo
        zout.writestr("word/media/image1.jpg", PHOTO_BYTES)

    return out_buf.getvalue()


def main():
    edu_map, key_map = get_user_education_map()
    print(f"Loaded {len(edu_map)} student education mappings from DB.")

    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    zip_files: dict[str, bytes] = {}

    for idx in range(1, 51):
        sno = f"EXP260925A-{idx:03d}"
        filename = f"{sno}.docx"
        file_path = EXP_DIR / filename
        if not file_path.exists():
            print(f"Skipping {filename}: file not found")
            continue

        raw = file_path.read_bytes()
        edu = edu_map.get(sno, "高职/大专")
        patched = patch_docx(raw, sno, edu)

        # 1. Write back to data/experiment_resumes/
        file_path.write_bytes(patched)
        zip_files[filename] = patched

        # 2. Write to data/resumes/ if mapped
        if sno in key_map:
            dest = RESUMES_DIR / key_map[sno]
            dest.write_bytes(patched)

    # 3. Update data/experiment_resumes_50.zip
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for fname, data in sorted(zip_files.items()):
            zout.writestr(fname, data)

    print(f"Successfully patched {len(zip_files)} resumes with photos and randomized preferences!")
    print(f"Updated {ZIP_PATH} ({ZIP_PATH.stat().st_size} bytes).")


if __name__ == "__main__":
    main()
