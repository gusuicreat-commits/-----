import pytest

from app import events, storage
from app.agent.analogy import compute
from app.agent.validator import validate


def shot(kind="title", **updates):
    result = {"id": "S1", "kind": kind, "source": "model", "duration_s": 40,
              "narration": "主梁长{{F_length}}。", "fact_refs": ["F_length"], "asset_refs": [], "analogy_refs": [],
              "params": {}, "review": {"status": "approved", "note": "已复核"}}
    result.update(updates)
    return result


@pytest.fixture
def scenario(project):
    pid = project["id"]
    project["model"] = {"kind": "parametric", "dims_check": [{"ok": True}], "assumed": []}
    storage.write_json(pid, "project.json", project)
    storage.write_json(pid, "facts.json", {"facts": [
        {"id": "F_length", "value": 104, "unit": "m", "status": "verified"},
        {"id": "F_speed", "value": 30, "unit": "m/min", "status": "confirmed"},
    ]})
    storage.write_json(pid, "assets.json", {"assets": [{"id": "IMG_01", "provenance": "reference"}]})
    storage.write_json(pid, "model/rig.json", {"axes": {"trolley": {"range_m": [-30, 30], "speed_fact": "F_speed"}}})
    storage.write_json(pid, "shotlist.json", {"shots": [shot()], "analogies": []})
    return pid


def write_shot(pid, item, analogies=None):
    storage.write_json(pid, "shotlist.json", {"shots": [item], "analogies": analogies or []})


def codes(pid):
    return {item["code"] for item in validate(pid, "r1")["issues"]}


def test_valid_resolve_and_persistence(scenario):
    assert validate(scenario, "r1") == {"issues": []}
    assert storage.read_json(scenario, "issues.json") == {"issues": []}
    assert storage.read_json(scenario, "shotlist.json")["shots"][0]["narration_resolved"] == "主梁长104米。"
    assert events.read_events(scenario)[-1]["summary"] == "校验 1 个镜头：0 个阻断、0 个警告"


@pytest.mark.parametrize("updates,expected", [
    ({"narration": "{{F_missing}}"}, "UNKNOWN_FACT"),
    ({"fact_refs": ["F_missing"]}, "UNKNOWN_FACT"),
    ({"params": {"facts": ["F_missing"]}}, "UNKNOWN_FACT"),
    ({"params": {"fact": "F_missing"}}, "UNKNOWN_FACT"),
    ({"narration": "三十米"}, "UNSOURCED_NUMBER"),
    ({"narration": "{{A_missing}}"}, "ANALOGY_MISSING"),
    ({"analogy_refs": ["A_missing"]}, "ANALOGY_MISSING"),
    ({"kind": "analogy", "params": {"analogy": "missing"}}, "ANALOGY_PARAM"),
    ({"source": "real"}, "SOURCE_MISMATCH"),
    ({"kind": "motion", "params": {"axis": "hoist"}}, "MOTION_AXIS_UNAVAILABLE"),
    ({"kind": "motion", "params": {"axis": "trolley", "from_m": -31, "to_m": 0}}, "MOTION_OUT_OF_RANGE"),
    ({"asset_refs": ["missing"]}, "ASSET_MISSING"),
    ({"kind": "real_media", "source": "real", "params": {"asset": "missing"}}, "ASSET_MISSING"),
    ({"narration": "我们的设备", "asset_refs": ["IMG_01"]}, "REFERENCE_ASSET_CLAIM"),
    ({"narration": "这台设备", "asset_refs": ["IMG_01"]}, "REFERENCE_ASSET_CLAIM"),
    ({"narration": "本机", "asset_refs": ["IMG_01"]}, "REFERENCE_ASSET_CLAIM"),
    ({"narration": "这里的工程结构值得仔细观察。" * 20}, "NARRATION_TOO_LONG"),
    ({"duration_s": 20}, "DURATION_OUT_OF_RANGE"),
    ({"duration_s": 61}, "DURATION_OUT_OF_RANGE"),
    ({"review": {"status": "pending"}}, "NOT_REVIEWED"),
    ({"params": None}, "CHECK_ERROR"),
])
def test_issue_codes(scenario, updates, expected):
    write_shot(scenario, shot(**updates))
    assert expected in codes(scenario)
    issue = next(i for i in storage.read_json(scenario, "issues.json")["issues"] if i["code"] == expected)
    assert issue["message"] and issue["hint"]
    assert issue["shot"] == (None if expected in {"DURATION_OUT_OF_RANGE", "NOT_REVIEWED"} else "S1")


@pytest.mark.parametrize("field", ["prompt", "caption"])
@pytest.mark.parametrize("word", ["起重机", "门机", "龙门吊", "吊车", "主梁", "支腿", "吊钩", "小车", "CRANE", "gantry", "hook", "girder"])
def test_equipment_words(scenario, field, word):
    write_shot(scenario, shot("ai_broll", source="ai", params={field: word}))
    assert "AI_SHOWS_EQUIPMENT" in codes(scenario)
    write_shot(scenario, shot("ai_broll", source="ai", params={field: "晨光与海面"}))
    assert "AI_SHOWS_EQUIPMENT" not in codes(scenario)


@pytest.mark.parametrize("status,expected", [("rejected", "REJECTED_FACT"), ("needs_review", "UNVERIFIED_FACT"),
                                            ("verified", None), ("confirmed", None)])
def test_fact_status_and_indirect_analogy(scenario, status, expected):
    facts = storage.read_json(scenario, "facts.json")
    facts["facts"][0]["status"] = status
    storage.write_json(scenario, "facts.json", facts)
    analogy = compute("A_length_football_field", facts["facts"][0], "football_field", "length")
    write_shot(scenario, shot("analogy", fact_refs=[], narration="{{A_length_football_field}}", params={"analogy": analogy["id"]}), [analogy])
    found = codes(scenario)
    assert (expected in found) if expected else not found
    saved = storage.read_json(scenario, "shotlist.json")["shots"][0]
    assert saved["narration_resolved"] == analogy["text"]


@pytest.mark.parametrize("status", ["verified", "confirmed", "needs_review", "rejected", "missing"])
def test_motion_speedup_and_unsourced(scenario, status):
    facts = storage.read_json(scenario, "facts.json")
    if status == "missing":
        facts["facts"].pop()
    else:
        facts["facts"][1]["status"] = status
    storage.write_json(scenario, "facts.json", facts)
    motion = shot("motion", params={"axis": "trolley", "from_m": -30, "to_m": 30, "speedup": 999})
    write_shot(scenario, motion)
    found = codes(scenario)
    speedup = storage.read_json(scenario, "shotlist.json")["shots"][0]["params"]["speedup"]
    assert speedup == (3 if status in {"verified", "confirmed"} else 1)
    assert ("MOTION_SPEED_UNSOURCED" in found) == (status not in {"verified", "confirmed"})
    motion["params"]["to_m"] = 31
    write_shot(scenario, motion)
    assert "MOTION_OUT_OF_RANGE" in codes(scenario)
    saved = storage.read_json(scenario, "shotlist.json")["shots"][0]["params"]
    assert saved.get("speedup") in (None, 1)


def test_model_metadata_and_aggregate_review(scenario):
    project = storage.read_json(scenario, "project.json")
    project["model"].update(dims_check=[{"ok": False, "message": "尺寸不符"}], assumed=["F_span"])
    storage.write_json(scenario, "project.json", project)
    storage.write_json(scenario, "shotlist.json", {"shots": [shot(id=f"S{i}", duration_s=20, review={"status": "pending"}) for i in (1, 2)]})
    issues = validate(scenario, "r1")["issues"]
    assert {i["code"] for i in issues} == {"MODEL_DIMS_MISMATCH", "MODEL_ASSUMED", "NOT_REVIEWED"}
    assert len([i for i in issues if i["code"] == "NOT_REVIEWED"]) == 1
    assert "2 个" in issues[-1]["message"]
    project["model"]["kind"] = "step"
    storage.write_json(scenario, "project.json", project)
    assert "MODEL_ASSUMED" not in codes(scenario)


@pytest.mark.parametrize("kind", ["title", "outro", "data_card", "model_orbit", "analogy", "motion", "exploded", "weld_macro", "real_media", "ai_broll"])
@pytest.mark.parametrize("has_model", [True, False])
def test_source_rules(scenario, kind, has_model):
    project = storage.read_json(scenario, "project.json")
    if not has_model:
        project["model"] = None
    storage.write_json(scenario, "project.json", project)
    source = "ai" if kind == "ai_broll" else "real" if kind == "real_media" else "graphic" if not has_model and kind in {"title", "outro", "data_card"} else "model"
    write_shot(scenario, shot(kind, source=source))
    assert "SOURCE_MISMATCH" not in codes(scenario)
    write_shot(scenario, shot(kind, source="real" if source != "real" else "ai"))
    assert "SOURCE_MISMATCH" in codes(scenario)


@pytest.mark.parametrize("provenance,narration", [("own", "这台设备"), ("reference", "像这样的造船门机")])
def test_asset_safe_claim(scenario, provenance, narration):
    storage.write_json(scenario, "assets.json", {"assets": [{"id": "IMG_01", "provenance": provenance}]})
    write_shot(scenario, shot("real_media", source="real", params={"asset": "IMG_01"}, narration=narration))
    assert not codes(scenario)


def test_checks_continue_after_bad_data(scenario):
    broken = shot(params=None, narration="三十米")
    storage.write_json(scenario, "shotlist.json", {"shots": [broken, None, shot(id="S3", narration="{{F_unknown}}")]})
    found = codes(scenario)
    assert {"CHECK_ERROR", "UNKNOWN_FACT", "UNSOURCED_NUMBER"} <= found
    assert events.read_events(scenario)[-1]["status"] == "warn"
    (storage.project_dir(scenario) / "facts.json").write_text("{", encoding="utf-8")
    assert "CHECK_ERROR" in codes(scenario)
    storage.write_json(scenario, "shotlist.json", None)
    assert "CHECK_ERROR" in codes(scenario)


def test_check_error_from_motion_does_not_hide_other_checks(scenario, monkeypatch):
    from app.agent import validator
    def broken(*args):
        raise RuntimeError("局部失败")
    monkeypatch.setattr(validator, "motion_speedup", broken)
    write_shot(scenario, shot("motion", params={"axis": "trolley", "from_m": 0, "to_m": 1}, asset_refs=["missing"]))
    assert {"CHECK_ERROR", "ASSET_MISSING"} <= codes(scenario)


@pytest.mark.parametrize("duration", [30, 60])
def test_duration_boundaries(scenario, duration):
    write_shot(scenario, shot(duration_s=duration))
    assert not codes(scenario)
