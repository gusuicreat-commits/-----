import pytest
from app import events, llm, storage
from app.ingest.facts import extract_facts, update_fact


def test_replay_verification_and_manual_preservation(project, sample_pdf):
    pid = project["id"]
    result = extract_facts(pid, "r1", sample_pdf)
    assert len(result["facts"]) == 14
    assert sum(item["status"] == "verified" for item in result["facts"]) == 13
    assert sum(item["status"] == "needs_review" for item in result["facts"]) == 1
    assert events.read_events(pid)[-1]["summary"] == "核验 14 条参数：13 条通过，1 条待人工确认"
    fixed = update_fact(pid, "F_leg_height", {"value": 41, "status": "rejected"})
    assert fixed["status"] == "confirmed" and fixed["value"] == 41
    update_fact(pid, "F_span", {"status": "rejected"})
    update_fact(pid, "F_girder_length", {"unit": "米"})
    assert storage.read_json(pid, "facts.json")["facts"][1]["status"] == "verified"
    again = {item["id"]: item for item in extract_facts(pid, "r2", sample_pdf)["facts"]}
    assert again["F_leg_height"]["status"] == "confirmed" and again["F_leg_height"]["value"] == 41
    assert again["F_span"]["status"] == "rejected"


def test_duplicate_missing_page_and_number_mismatch(monkeypatch, project, sample_pdf):
    items = [
        {"id":"F_span", "name":"跨度", "value":88, "unit":"m", "page":2, "quote":"跨度\n88 m"},
        {"id":"F_span", "name":"重复", "value":99, "unit":"m", "page":2, "quote":"错误99"},
        {"id":"F_missing", "name":"错页", "value":88, "unit":"m", "page":99, "quote":"跨度\n88 m"},
        {"id":"F_mismatch", "name":"数值不符", "value":89, "unit":"m", "page":2, "quote":"跨度\n88 m"},
    ]
    monkeypatch.setattr(llm, "complete_json", lambda *args, **kwargs: {"facts": items})
    result = extract_facts(project["id"], "r1", sample_pdf)["facts"]
    assert len(result) == 3
    assert result[0]["value"] == 88 and result[0]["status"] == "verified"
    assert all(item["status"] == "needs_review" for item in result[1:])


@pytest.mark.parametrize("patch", [{"name": "不能改"}, {"status": "unknown"}, {"value": None}, {"unit": 1}, {"value": float("nan")}])
def test_invalid_patch(project, patch):
    with pytest.raises(ValueError):
        update_fact(project["id"], "F_span", patch)


def test_missing_fact(project):
    with pytest.raises(KeyError):
        update_fact(project["id"], "F_missing", {"status": "confirmed"})
