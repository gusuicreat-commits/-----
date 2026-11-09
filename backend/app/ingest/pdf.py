from pathlib import Path
import re
import pymupdf


def extract_pages(pdf_path: Path) -> list[dict]:
    with pymupdf.open(pdf_path) as doc:
        return [{"page": page.number + 1, "text": page.get_text("text")} for page in doc]


def normalize(s: str) -> str:
    # 保留范围符号～，仅折叠全角数字、字母和空格。
    table = {ord(c): ord(c) - 0xFEE0 for c in "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"}
    table[ord("　")] = ord(" ")
    return re.sub(r"\s+", "", s.translate(table))
