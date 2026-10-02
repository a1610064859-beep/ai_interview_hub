"""Extract page references and check final report structure without reading logs."""
from pathlib import Path
import argparse
import json
import re
import shutil
from pypdf import PdfReader
import pdfplumber
from docx import Document

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PDF = ROOT / "tmp/report05_qa/项目报告书_命题05.pdf"
SOURCE = HERE / "项目报告书_命题05.md"
TOC = HERE / "toc_pages.json"

def main():
    args = argparse.ArgumentParser()
    args.add_argument("--update-toc", action="store_true")
    args.add_argument("--finalize", action="store_true")
    options = args.parse_args()
    source = SOURCE.read_text(encoding="utf-8")
    titles = [line[2:] for line in source.splitlines() if re.match(r"# (第[一二三四五六七八九十]+章|附录[AB])", line)]
    reader = PdfReader(PDF)
    texts = [page.extract_text() for page in reader.pages]
    pages = {}
    normalize = lambda text: re.sub(r"\s+", "", text)
    for i, text in enumerate(texts):
        if i < 3:
            continue
        lines = [normalize(line) for line in text.splitlines()]
        for title in titles:
            if normalize(title) in lines:
                pages[title] = i + 1
    blanks = [i+1 for i, text in enumerate(texts) if len(text) < 60]
    overflows = []
    with pdfplumber.open(PDF) as pdf:
        for i, page in enumerate(pdf.pages):
            chars = [c for c in page.chars if c.get("text", "").strip()]
            if any(c["x0"] < -0.5 or c["x1"] > page.width + 0.5 or c["top"] < -0.5 or c["bottom"] > page.height + 0.5 for c in chars):
                overflows.append(i+1)
    doc = Document(ROOT / "deliverables/项目报告书_命题05.docx")
    if options.update_toc:
        TOC.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")
    forbidden = ("上海工程技术大学", "张庭辉", "王云遥", "魏孜艺", "陈俊龙", "汪文婷")
    found_forbidden = [w for w in forbidden if w in "".join(texts)]
    result = {
        "page_count": len(texts),
        "chapter_count": len(pages),
        "chapter_pages": pages,
        "blank_pages": blanks,
        "characters_outside_page": overflows,
        "replacement_glyph_present": any("\ufffd" in text for text in texts),
        "blind_review_compliant": len(found_forbidden) == 0,
        "forbidden_found": found_forbidden,
        "table_count": len(doc.tables),
        "figure_count": len(doc.inline_shapes),
        "pdf_bytes": PDF.stat().st_size,
        "toc_matches": json.loads(TOC.read_text(encoding="utf-8")) == pages,
        "visual_review": "pending",
    }
    print(json.dumps(result, ensure_ascii=False))
    assert len(pages) == len(titles) and not blanks and not overflows
    assert not result["replacement_glyph_present"] and result["blind_review_compliant"]
    if options.finalize:
        assert result["toc_matches"]
        assert PDF.stat().st_size < 100_000_000
        shutil.copy2(PDF, ROOT / "deliverables/项目报告书_命题05.pdf")
        (HERE / "qa_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
