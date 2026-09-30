"""Build the contest core-code booklet from one immutable Git commit.

Usage: python scripts/build_core_code_pdf.py --commit <sha>
Only the selected, line-numbered source excerpts enter the PDF. The sidecar
manifest is written under tmp/pdfs for review and is not a deliverable.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import subprocess

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "deliverables" / "核心代码_统一终稿.pdf"
MANIFEST = ROOT / "tmp" / "pdfs" / "core_code_manifest.json"
FONT_PATH = Path(r"C:\Windows\Fonts\simhei.ttf")
PAGE_W, PAGE_H = A4
INK = colors.HexColor("#152742")
BLUE = colors.HexColor("#2468C8")
MUTED = colors.HexColor("#65758D")
PALE = colors.HexColor("#F1F5FA")
RULE = colors.HexColor("#DCE5F0")
LEFT = 43
RIGHT = PAGE_W - 43
BOTTOM = 56


@dataclass(frozen=True)
class Selection:
    label: str
    path: str
    kind: str
    target: str | tuple[int, int]


@dataclass(frozen=True)
class Chapter:
    title: str
    purpose: str
    selections: tuple[Selection, ...]


def fn(label: str, path: str, name: str) -> Selection:
    return Selection(label, path, "function", name)


def block(label: str, path: str, start: int, end: int) -> Selection:
    return Selection(label + " [独立逻辑块]", path, "block", (start, end))


CHAPTERS = (
    Chapter("01 数据骨架与身份", "证明学生、岗位、答题、报告的关系和访问边界均由服务端保存。", (
        fn("学生档案", "server/models.py", "User"),
        fn("会话快照与租约字段", "server/models.py", "Session"),
        fn("回答与报告", "server/models.py", "Answer"),
        fn("报告记录", "server/models.py", "Report"),
        fn("会话鉴权", "server/api/auth.py", "require_current_user"),
        fn("学生角色门禁", "server/api/auth.py", "require_student"),
        block("会话路由角色依赖", "server/api/sessions.py", 40, 40),
        fn("会话本人访问校验", "server/api/sessions.py", "_ensure_student_session_access"),
    )),
    Chapter("02 六题装配与开场", "证明题库按两道通用、三道专业、一道情景装配，缺题拒绝创建；开场并行预取语音。", (
        block("题型数量与缺题异常", "server/services/question_bank.py", 6, 10),
        fn("题库完整性", "server/services/question_bank.py", "get_interview_questions"),
        fn("创建会话与并行预取", "server/api/sessions.py", "create_session"),
        fn("问题语音预取", "server/services/tts.py", "prefetch_session_questions"),
    )),
    Chapter("03 服务端状态与追问", "证明待答题快照可恢复，追问受提示词和每题一次的服务端判断约束。", (
        fn("状态恢复", "server/api/sessions.py", "get_session_state"),
        fn("追问判断与失败降级", "server/services/orchestrator.py", "evaluate_followup"),
        block("原题指引、追问与六题推进", "server/api/sessions.py", 311, 387),
    )),
    Chapter("04 答题并发与落库", "证明文本与语音共享服务端推进规则；租约互斥，失去 token 的请求不能写入最终结果。", (
        block("文本回答租约抢占", "server/api/sessions.py", 203, 277),
        block("租约续期", "server/api/sessions.py", 284, 309),
        block("失去租约时取消业务", "server/api/sessions.py", 398, 411),
        block("文本最终 token 条件提交", "server/api/sessions.py", 472, 524),
        block("语音上传边界", "server/api/sessions.py", 566, 588),
        block("语音转写进入同一推进链", "server/api/sessions.py", 698, 717),
        block("语音最终 token 条件提交", "server/api/sessions.py", 910, 958),
    )),
    Chapter("05 ASR 与可复现声学规则", "证明音频先转码再转写，文本归一化和填充词计数有确定规则；数值规则不等于测量效度证明。", (
        fn("音频转码", "server/services/audio.py", "transcode_to_16k_wav"),
        fn("转写归一化", "server/services/asr.py", "normalize_asr_text"),
        fn("填充词计数", "server/services/asr.py", "count_filler_words"),
        fn("语速计算", "server/api/sessions.py", "_compute_wpm"),
        block("声学阈值常量", "server/services/scoring.py", 86, 96),
        fn("声学流畅度", "server/services/scoring.py", "compute_acoustic_fluency"),
    )),
    Chapter("06 评分证据与模型回退", "证明两次独立评分、缺维空值、原文子串校验，以及三档模型回退与用量记录。", (
        fn("原文证据字面校验", "server/services/scoring.py", "validate_evidence"),
        fn("维度合成", "server/services/scoring.py", "calculate_dimension_average"),
        fn("有效维度总分", "server/services/scoring.py", "calculate_overall"),
        fn("单次评分及校验", "server/services/scoring.py", "call_scoring_llm"),
        fn("两次独立评分", "server/services/scoring.py", "score_interview"),
        fn("模型回退链", "server/services/llm.py", "LLMClient._chain"),
        fn("调用、校验重试与用量", "server/services/llm.py", "LLMClient._attempts"),
    )),
    Chapter("07 成长记录与曲线", "证明历史按本人同岗查询，综合分按严格口径比较；同版本且输入模式已知时可比较共同的非声学维度。", (
        fn("已完成报告筛选", "server/services/growth.py", "iter_qualified"),
        fn("综合分可比性", "server/services/growth.py", "_compare_overall"),
        fn("共同有效维度", "server/services/growth.py", "_dimension_changes"),
        fn("成长趋势与跨模式维度门禁", "server/services/growth.py", "build_trend"),
        block("综合分分组键", "web/lib/growth-data.ts", 609, 615),
        block("缺失点与分口径曲线", "web/lib/growth-data.ts", 617, 743),
    )),
    Chapter("08 企业同源初筛", "证明候选人来自真实会话报告，每人同岗位取最近合格记录；权重含学历学校且可配置。", (
        fn("六因素权重与旧配置默认", "server/services/recruiter.py", "parse_job_weights"),
        fn("有效项加权", "server/services/recruiter.py", "compute_weighted_score"),
        fn("同源报告查询", "server/services/recruiter.py", "_eligible_reports_for_cohort"),
        fn("每人最近一份", "server/services/recruiter.py", "pick_latest_eligible_per_user"),
        fn("候选人与溯源标识", "server/services/recruiter.py", "build_candidate_item"),
        fn("候选排序", "server/services/recruiter.py", "build_candidates_response"),
    )),
    Chapter("09 新生咨询与学习", "证明咨询连接现有岗位；学习菜单让新生先识别题型，再写自己的答案，STAR 只用于经历题。", (
        fn("岗位路径咨询", "server/services/counsel.py", "build_counsel_response"),
        block("题型识别练习", "web/lib/learning.ts", 20, 39),
        block("学习菜单与 STAR 边界", "web/lib/learning.ts", 41, 50),
        block("识别-诊断-搭建-自写练习", "web/app/learn/learn-content.tsx", 118, 170),
    )),
    Chapter("10 逐题反馈隔离", "证明仅新生本人可读取最新答案的练习反馈；它不推进会话，也不写正式报告。", (
        block("反馈路由角色依赖", "server/api/answer_feedback.py", 10, 14),
        fn("逐题反馈接口", "server/api/answer_feedback.py", "get_answer_feedback"),
        fn("模型片段扩展为展示原句", "server/services/answer_feedback.py", "_complete_evidence_quote"),
        fn("练习评分与回退", "server/services/answer_feedback.py", "evaluate_answer"),
    )),
)


def git_text(commit: str, path: str) -> list[str]:
    result = subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout.decode("utf-8-sig").splitlines()


def resolved_commit(raw: str) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"{raw}^{{commit}}"], cwd=ROOT,
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return result.stdout.strip()


def resolve_selection(sel: Selection, lines: list[str]) -> tuple[int, int]:
    if sel.kind == "block":
        start, end = sel.target
    else:
        tree = ast.parse("\n".join(lines) + "\n")
        names = str(sel.target).split(".")
        candidates = tree.body
        node = None
        for name in names:
            node = next(
                (item for item in candidates if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name),
                None,
            )
            if node is None:
                raise ValueError(f"Missing symbol {sel.target} in {sel.path}")
            candidates = node.body
        start, end = node.lineno, node.end_lineno
    if not 1 <= start <= end <= len(lines):
        raise ValueError(f"Invalid range {sel.path}:{start}-{end}")
    if sel.kind == "block" and sel.path.endswith(".py"):
        tree = ast.parse("\n".join(lines) + "\n")
        code_lines = [
            number for number in range(start, end + 1)
            if lines[number - 1].strip() and not lines[number - 1].lstrip().startswith("#")
        ]
        first, last = code_lines[0], code_lines[-1]
        complete = False
        for parent in (tree, *ast.walk(tree)):
            for attr in ("body", "orelse", "finalbody"):
                siblings = getattr(parent, attr, None)
                if not isinstance(siblings, list):
                    continue
                selected = [
                    node for node in siblings
                    if isinstance(node, ast.stmt) and first <= node.lineno <= node.end_lineno <= last
                ]
                if selected and selected[0].lineno == first and selected[-1].end_lineno == last:
                    complete = True
                    break
            if complete:
                break
        if not complete:
            raise ValueError(f"Block cuts a Python statement: {sel.path}:{start}-{end}")
    return start, end


def wrap_code(value: str, width: float, size: float = 7.45) -> list[str]:
    if not value:
        return [""]
    chunks: list[str] = []
    current = ""
    for char in value:
        if current and pdfmetrics.stringWidth(current + char, "SimHei", size) > width:
            chunks.append(current)
            current = char
        else:
            current += char
    chunks.append(current)
    return chunks


class Booklet:
    def __init__(self, commit: str, toc: dict[str, int] | None):
        self.buffer = BytesIO()
        self.pdf = canvas.Canvas(self.buffer, pagesize=A4, pageCompression=1)
        self.pdf.setTitle("智驾未来 AI面试仓 - 核心代码统一终稿")
        self.pdf.setAuthor("智驾未来 AI面试仓项目组")
        self.commit = commit
        self.toc = toc or {}
        self.page = 0
        self.y = 0.0
        self.chapter = ""
        self.chapters: dict[str, int] = {}
        self.entries: list[dict] = []

    def new_page(self, chapter: str):
        if self.page:
            self._footer()
            self.pdf.showPage()
        self.page += 1
        self.chapter = chapter
        p = self.pdf
        p.setFillColor(BLUE)
        p.rect(LEFT, PAGE_H - 40, RIGHT - LEFT, 3, stroke=0, fill=1)
        p.setFillColor(INK)
        p.setFont("SimHei", 8.8)
        p.drawString(LEFT, PAGE_H - 57, "智驾未来 · AI面试仓  /  核心代码")
        p.setFillColor(MUTED)
        p.setFont("SimHei", 7.7)
        p.drawRightString(RIGHT, PAGE_H - 57, chapter)
        self.y = PAGE_H - 83

    def _footer(self):
        p = self.pdf
        p.setStrokeColor(RULE)
        p.line(LEFT, 43, RIGHT, 43)
        p.setFillColor(MUTED)
        p.setFont("SimHei", 7.1)
        p.drawString(LEFT, 29, f"统一源码提交 {self.commit[:12]}  |  真实路径与行号")
        p.drawRightString(RIGHT, 29, f"{self.page:02d}")

    def ensure(self, height: float):
        if self.y - height < BOTTOM:
            self.new_page(self.chapter)

    def text(self, value: str, size: float = 9, leading: float = 15, color=INK):
        self.ensure(leading)
        self.pdf.setFillColor(color)
        self.pdf.setFont("SimHei", size)
        self.pdf.drawString(LEFT, self.y, value)
        self.y -= leading

    def cover(self):
        self.new_page("统一终稿")
        self.y = PAGE_H - 183
        self.text("核心代码", 29, 49, INK)
        self.text("智驾未来 · AI面试仓", 17, 34, BLUE)
        self.y -= 25
        self.text("上海第九届青少年AI创新大赛  /  智能面试仓的开发与应用", 11, 28)
        self.text("功能选编 · 统一提交 · 可追溯行号", 10.5, 33, MUTED)
        self.y -= 45
        for label, value in (
            ("源码基线", self.commit),
            ("编制日期", date.today().isoformat()),
            ("阅读方式", "每段标注仓库路径及原文件行号；长行视觉软换行，原文件行号不变。"),
            ("材料范围", "精选当前功能的关键实现；不是完整源码或模型效果证明。"),
        ):
            self.pdf.setFillColor(PALE)
            self.pdf.roundRect(LEFT, self.y - 15, RIGHT - LEFT, 43, 6, stroke=0, fill=1)
            self.pdf.setFillColor(MUTED)
            self.pdf.setFont("SimHei", 9)
            self.pdf.drawString(LEFT + 12, self.y + 6, label)
            self.pdf.setFillColor(INK)
            self.pdf.setFont("SimHei", 8.6)
            self.pdf.drawString(LEFT + 88, self.y + 6, value)
            self.y -= 56

    def contents(self):
        self.new_page("目录")
        self.text("目录与使用说明", 18, 35)
        self.text("所有摘录均由同一 Git 提交读取；页脚短 SHA 对应封面完整 SHA。", 9, 27, MUTED)
        for chapter in (*CHAPTERS, Chapter("答辩说明与实现边界", "", ())):
            self.ensure(36)
            self.pdf.setFillColor(PALE)
            self.pdf.roundRect(LEFT, self.y - 9, RIGHT - LEFT, 30, 4, stroke=0, fill=1)
            self.pdf.setFillColor(INK)
            self.pdf.setFont("SimHei", 10)
            self.pdf.drawString(LEFT + 12, self.y + 3, chapter.title)
            page_no = self.toc.get(chapter.title)
            if page_no:
                self.pdf.drawRightString(RIGHT - 13, self.y + 3, f"{page_no:02d}")
            self.y -= 39
        self.y -= 11
        self.text("目录页码对应页脚编号。", 9, 17, MUTED)

    def heading(self, chapter: Chapter):
        self.new_page(chapter.title)
        self.chapters[chapter.title] = self.page
        self.text(chapter.title, 18, 31)
        self.text(chapter.purpose, 9, 18, MUTED)
        self.y -= 9

    def excerpt(self, sel: Selection, lines: list[str], start: int, end: int):
        estimated_rows = sum(len(wrap_code(lines[number - 1], RIGHT - LEFT - 55)) for number in range(start, end + 1))
        # A short excerpt should remain on one page whenever it can fit there.
        self.ensure(estimated_rows * 10.65 + 48 if estimated_rows <= 25 else 46)
        first_page = self.page
        p = self.pdf
        p.setFillColor(BLUE)
        p.setFont("SimHei", 10)
        p.drawString(LEFT, self.y, sel.label)
        self.y -= 16
        p.setFillColor(MUTED)
        p.setFont("SimHei", 7.8)
        p.drawString(LEFT, self.y, f"{sel.path}  /  行 {start}-{end}")
        self.y -= 14
        panel_top = self.y + 4
        for number in range(start, end + 1):
            chunks = wrap_code(lines[number - 1], RIGHT - LEFT - 55)
            for idx, chunk in enumerate(chunks):
                if self.y - 11 < BOTTOM:
                    self.new_page(self.chapter)
                    p = self.pdf
                    p.setFillColor(MUTED)
                    p.setFont("SimHei", 7.5)
                    p.drawString(LEFT, self.y, f"{sel.label}  /  续  /  {sel.path}")
                    self.y -= 16
                    panel_top = self.y + 4
                if idx == 0 and number % 2 == 0:
                    p.setFillColor(PALE)
                    p.rect(LEFT, self.y - 2, RIGHT - LEFT, 11, stroke=0, fill=1)
                p.setFont("SimHei", 7.45)
                if idx == 0:
                    p.setFillColor(MUTED)
                    p.drawRightString(LEFT + 34, self.y, str(number))
                p.setFillColor(INK)
                p.drawString(LEFT + 43, self.y, chunk)
                self.y -= 10.65
        p.setStrokeColor(RULE)
        p.line(LEFT, self.y + 2, RIGHT, self.y + 2)
        self.y -= 13
        self.entries.append({
            "chapter": self.chapter, "label": sel.label, "path": sel.path,
            "start_line": start, "end_line": end,
            "start_page": first_page, "end_page": self.page,
        })

    def closing(self):
        self.new_page("答辩说明")
        self.chapters["答辩说明与实现边界"] = self.page
        self.text("答辩说明与实现边界", 18, 37)
        points = (
            ("一条可演示的链", "学生登录后选择岗位，六题面试生成报告；同一报告进入成长记录与企业初筛。新生咨询可引向这两个岗位。"),
            ("评分证据的边界", "正式评分只校验 evidence 是回答的连续原文、长度不超过 25 字；这不保证模型评价在语义上正确。"),
            ("逐题反馈的展示原句", "反馈模型给出最多 25 字片段；程序扩展成原回答中的整句供展示。练习反馈与正式报告分离。"),
            ("声学数值的边界", "语速、停顿和填充词计算可复现；尚不能据此宣称其测量效度、就业效果或能力提升。"),
            ("并发与重试", "租约防止并发写入；最终提交须持有 token。网络结果不明时先查询状态，不能把 409 解释为自动安全重投。"),
            ("模型用量指标", "当前非流式调用的 ttft_ms 记录响应可用耗时，不是真正的首 token 时延。"),
            ("成长口径", "综合分跨输入模式不直接比较；同评分版本且输入模式均已知时，共同有效的非声学维度可比较。缺失值保留为空。"),
            ("企业排序的性质", "默认旧配置把面试、学历、学校权重分为 60%/20%/20%；可配置，仅供初筛偏好，不能等同面试能力，需人工复核。"),
        )
        for title, detail in points:
            self.ensure(68)
            self.pdf.setFillColor(BLUE)
            self.pdf.setFont("SimHei", 10)
            self.pdf.drawString(LEFT, self.y, title)
            self.y -= 17
            for line in wrap_code(detail, RIGHT - LEFT - 6, 9):
                self.text(line, 9, 15)
            self.y -= 7

    def finish(self) -> bytes:
        self._footer()
        self.pdf.showPage()
        self.pdf.save()
        return self.buffer.getvalue()


def build(commit: str, toc: dict[str, int] | None):
    book = Booklet(commit, toc)
    cache: dict[str, list[str]] = {}
    book.cover()
    book.contents()
    for chapter in CHAPTERS:
        book.heading(chapter)
        for sel in chapter.selections:
            lines = cache.setdefault(sel.path, git_text(commit, sel.path))
            start, end = resolve_selection(sel, lines)
            book.excerpt(sel, lines, start, end)
    book.closing()
    content = book.finish()
    return content, book


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="one immutable source commit")
    args = parser.parse_args()
    if not FONT_PATH.exists():
        raise FileNotFoundError(FONT_PATH)
    pdfmetrics.registerFont(TTFont("SimHei", str(FONT_PATH)))
    commit = resolved_commit(args.commit)
    _, draft = build(commit, None)
    content, final = build(commit, draft.chapters)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(content)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source_commit": commit, "pdf": str(OUTPUT), "page_count": final.page,
        "chapter_pages": final.chapters, "excerpts": final.entries,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"pdf": str(OUTPUT), "pages": final.page, "manifest": str(MANIFEST), "commit": commit}, ensure_ascii=False))


if __name__ == "__main__":
    main()
