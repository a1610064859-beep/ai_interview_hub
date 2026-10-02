"""修复 附件1：参赛项目概况表_已填写.xlsx 中的 Wingdings 2 字体导致的乱码问题。"""

from pathlib import Path
import shutil
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_FILE = PROJECT_ROOT / "附件1：参赛项目概况表_已填写.xlsx"
BACKUP_FILE = PROJECT_ROOT / "附件1：参赛项目概况表_已填写.xlsx.bak"


def fix_xlsx_font():
    if not TARGET_FILE.exists():
        raise FileNotFoundError(f"Target file not found: {TARGET_FILE}")

    # 1. 备份原文件
    shutil.copy2(TARGET_FILE, BACKUP_FILE)
    print(f"Backed up to: {BACKUP_FILE}")

    # 2. 读取并替换
    file_map = {}
    with zipfile.ZipFile(TARGET_FILE, "r") as zin:
        for info in zin.infolist():
            file_map[info.filename] = zin.read(info.filename)

    styles_xml = file_map.get("xl/styles.xml")
    if not styles_xml:
        raise ValueError("xl/styles.xml not found in xlsx")

    if b"Wingdings 2" not in styles_xml:
        print("Wingdings 2 not found in xl/styles.xml, already fixed or clean.")
        return

    # 替换 Wingdings 2 为 仿宋_GB2312
    old_target = b'<x:name val="Wingdings 2" />'
    new_target = '<x:name val="仿宋_GB2312" />'.encode("utf-8")

    if old_target in styles_xml:
        new_styles_xml = styles_xml.replace(old_target, new_target)
    else:
        new_styles_xml = styles_xml.replace(b'Wingdings 2', '仿宋_GB2312'.encode("utf-8"))

    file_map["xl/styles.xml"] = new_styles_xml

    # 3. 写回 xlsx
    with zipfile.ZipFile(TARGET_FILE, "w", compression=zipfile.ZIP_DEFLATED) as zout:
        for name, content in file_map.items():
            zout.writestr(name, content)

    print("Successfully replaced Wingdings 2 with 仿宋_GB2312 in 附件1：参赛项目概况表_已填写.xlsx!")


if __name__ == "__main__":
    fix_xlsx_font()
