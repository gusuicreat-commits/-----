"""把示例参数表排版为可抽取文本的三页资料。"""
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import SAMPLES_DIR
from app.ingest.pdf import extract_pages

def wrap(text: str, width: float, size: float) -> list[str]:
    lines: list[str] = []
    line = ""
    for char in text:
        if pymupdf.get_text_length(line + char, fontname="china-s", fontsize=size) > width:
            lines.append(line)
            line = char
        else:
            line += char
    if line:
        lines.append(line)
    return lines


def generate() -> Path:
    source = (SAMPLES_DIR / "示例技术参数表.md").read_text(encoding="utf-8")
    sections = re.split(r"^## 第\d+页\s*$", source, flags=re.MULTILINE)[1:]
    output = SAMPLES_DIR / "示例技术参数表.pdf"
    with pymupdf.open() as doc:
        for index, section in enumerate(sections, 1):
            page = doc.new_page(width=595, height=842)
            y = 55.0
            for raw in section.strip().splitlines():
                line = raw.strip()
                if not line:
                    y += 9
                    continue
                if line.startswith("|"):
                    cells = [cell.strip() for cell in line.strip("|").split("|")]
                    if all(re.fullmatch(r"[-: ]+", cell) for cell in cells):
                        continue
                    for column, cell in enumerate(cells[:2]):
                        x = 45 + column * 252.5
                        page.draw_rect(pymupdf.Rect(x, y, x + 252.5, y + 30), color=(0.35, 0.4, 0.45), width=0.5)
                        page.insert_text((x + 10, y + 20), cell, fontname="china-s", fontsize=11)
                    y += 30
                else:
                    size = 18 if line.startswith("# ") else 14 if line.startswith("## ") else 11
                    text = re.sub(r"^#{1,2} ", "", line)
                    for fragment in wrap(text, 505, size):
                        y += size * 1.6
                        page.insert_text((45, y), fragment, fontname="china-s", fontsize=size,
                                         render_mode=2 if size == 18 else 0, border_width=0.015)
                if y > 770:
                    raise ValueError("示例内容超出页面，请调整排版")
            page.draw_line((45, 789), (550, 789), color=(0.65, 0.65, 0.65), width=0.5)
            page.insert_text((45, 810), "演示示例资料", fontname="china-s", fontsize=9)
            page.insert_text((425, 810), f"第 {index} 页 / 共 {len(sections)} 页", fontname="china-s", fontsize=9)
        doc.save(output, garbage=4, deflate=True)
    pages = extract_pages(output)
    assert "主梁总长" in pages[1]["text"] and "104 m" in pages[1]["text"]
    print(f"已生成并自检：{output}，共 {len(pages)} 页")
    return output


if __name__ == "__main__":
    generate()
