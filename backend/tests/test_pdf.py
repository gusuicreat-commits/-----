from app.ingest.pdf import extract_pages, normalize


def test_sample_pdf(sample_pdf):
    pages = extract_pages(sample_pdf)
    assert [page["page"] for page in pages] == [1, 2, 3]
    assert "主梁总长" in pages[1]["text"] and "104 m" in pages[1]["text"]
    assert "0.5 mm" in pages[2]["text"]
    for index, page in enumerate(pages, 1):
        assert f"第{index}页/共3页" in normalize(page["text"])
        assert "演示示例资料" in page["text"]


def test_normalize():
    assert normalize("ＡＢＣ　１２３\n ０～８ ｍ/ｍｉｎ\t") == "ABC1230～8m/min"
