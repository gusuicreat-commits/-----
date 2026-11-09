from copy import deepcopy
import json
import pytest

from app import config, events, llm, storage
from app.agent import planner
from app.agent.planner import plan, repair, revise_shot
from app.agent.validator import validate
from app.ingest.facts import extract_facts
from app.model3d import build_parametric, build_rig


def setup_sample(project: dict) -> str:
    pid = project["id"]
    extracted = extract_facts(pid, "r1", config.SAMPLES_DIR / "示例技术参数表.pdf")
    facts = [f for f in extracted["facts"] if f["status"] == "verified"]
    storage.write_json(pid, "facts.json", {"facts": facts})
    values = {f["id"]: f["value"] for f in facts}
    model = build_parametric(values, storage.project_dir(pid) / "model/crane.glb")
    rig = build_rig(values, model["bbox_m"], "parametric", model["nodes"])
    storage.write_json(pid, "model/rig.json", rig)
    project.update(brief="口语化解释超大门机的尺寸、结构、运动与焊缝精度，亲切且有出处。",
                   model={"kind": "parametric", "glb": "model/crane.glb", "assumed": model["assumed"]})
    storage.write_json(pid, "project.json", project)
    storage.write_json(pid, "assets.json", {"assets": [
        {"id": f"IMG_{i:02d}", "title": title, "tags": ["参考实拍"], "kind": "image", "provenance": "reference",
         "file": f"assets/{i}.jpg", "credit": "示例素材署名"}
        for i, title in enumerate(["船厂全景", "装配现场", "焊缝近景", "轨道视角", "夜间船厂"], 1)
    ]})
    return pid


@pytest.fixture
def sample(project):
    return setup_sample(project)


def test_replay_plan_repair(sample, monkeypatch):
    monkeypatch.setenv("KEPU_LLM_MODE", "replay")
    result = plan(sample, "r1")
    shots = result["shots"]
    assert len(shots) == 8 and len({s["kind"] for s in shots}) == 8
    assert [s["id"] for s in shots] == [f"S{i}" for i in range(1, 9)]
    assert {key: result[key] for key in ("version", "fps", "width", "height")} == {
        "version": 1, "fps": 30, "width": 1920, "height": 1080}
    assert all(s["review"] == {"status": "pending", "note": ""} for s in shots)
    assert [s["source"] for s in shots] == ["model", "model", "model", "model", "model", "real", "ai", "model"]
    assert shots[2]["params"] == planner.PARAM_DEFAULTS["model_orbit"]
    assert shots[1]["params"] == {"analogy": "A_girder_length_football_field"}
    assert result["analogies"][0]["ratio"] == .99
    assert result["analogies"][1]["ratio"] == 7.143
    assert shots[4]["params"]["fact"] == "F_weld_tolerance"
    assert result["notes"] == []
    assert storage.read_json(sample, "shotlist.json") == result
    issues = validate(sample, "r1")
    blocks = [i for i in issues["issues"] if i["severity"] == "block"]
    assert [(i["shot"], i["code"]) for i in blocks] == [("S3", "UNSOURCED_NUMBER")]
    before = deepcopy(storage.read_json(sample, "shotlist.json"))
    repaired = repair(sample, "r1", issues)
    assert repaired["shots"][2]["narration"] == "主梁和支腿搭起骨架，小车沿主梁移动。"
    assert all(repaired["shots"][i] == before["shots"][i] for i in range(8) if i != 2)
    assert not [i for i in validate(sample, "r1")["issues"] if i["severity"] == "block"]
    history = events.read_events(sample)
    for tool in ("llm.opus.plan", "llm.opus.repair"):
        assert [e["status"] for e in history if e["tool"] == tool] == ["start", "ok"]
    assert any(e["tool"] == "analogy.compute" and "计算 2 个类比" in e["summary"] for e in history)
    assert all(log["backend"] == "replay" for path in (storage.project_dir(sample) / "llm").glob("*.json")
               for log in [json.loads(path.read_text())])


def test_replay_revise_keeps_id_and_resets_review(sample):
    plan(sample, "r1")
    saved = storage.read_json(sample, "shotlist.json")
    saved["shots"][1]["review"] = {"status": "approved", "note": "原先已审核"}
    storage.write_json(sample, "shotlist.json", saved)
    result = revise_shot(sample, "r2", "S2", "改用公交车作长度类比，保持口语化。")
    item = result["shots"][1]
    assert item["id"] == "S2" and item["review"] == {"status": "pending", "note": ""}
    assert item["params"]["analogy"] == "A_girder_length_bus"
    assert {a["id"] for a in result["analogies"]} == {"A_girder_length_bus", "A_weld_tolerance_hair"}
    assert next(a for a in result["analogies"] if a["ref"] == "bus")["ratio"] == 8.667
    assert [e["status"] for e in events.read_events(sample) if e["tool"] == "llm.opus.revise"] == ["start", "ok"]


def test_prompt_context_and_optional_params(sample):
    context = planner._context(sample)
    assert len(context["facts"]) == 13
    assert len(context["assets"]) == 5 and all(a["provenance"] == "reference" for a in context["assets"])
    assert "hoist_hook" in context["model"]["nodes"]
    assert set(context["model"]["rig"]["axes"]) == {"trolley", "gantry", "hoist"}
    assert all(f["page"] in (2, 3) for f in context["facts"])
    facts = storage.read_json(sample, "facts.json")
    facts["facts"][0]["status"] = "rejected"
    facts["facts"][1]["status"] = "needs_review"
    storage.write_json(sample, "facts.json", facts)
    assert len(planner._context(sample)["facts"]) == 11
    params = planner.PLAN_SCHEMA["properties"]["shots"]["items"]["properties"]["params"]
    assert "required" not in params and set(params["properties"]) == {
        "title", "subtitle", "from_deg", "to_deg", "elevation_deg", "distance", "highlight", "analogy", "axis",
        "from_m", "to_m", "parts", "spread_m", "facts", "asset", "effect", "caption", "recipe", "palette", "prompt", "fact"}
    contract = (config.ROOT / "docs/CONTRACTS.md").read_text()
    assert planner.KIND_DESCRIPTIONS in contract


def raw_shot(kind="title", **updates):
    result = {"id": "anything", "kind": kind, "source": "ai", "duration_s": 5,
              "narration": "观察结构。", "fact_refs": [], "asset_refs": [], "analogy_requests": [], "params": {}}
    result.update(updates)
    return result


def test_defaults_invalid_requests_and_no_model(project, monkeypatch):
    payload = {"title": "示例", "shots": [raw_shot(kind, params={"unrelated": "删除"}) for kind in planner.PARAM_DEFAULTS]}
    payload["shots"][3]["analogy_requests"] = [
        {"fact": "F_missing", "ref": "bus", "axis": "length"},
        {"fact": "F_length", "ref": "bus", "axis": "height"},
    ]
    storage.write_json(project["id"], "facts.json", {"facts": [{"id": "F_length", "name": "长", "value": 104, "unit": "m", "status": "verified"}]})
    monkeypatch.setattr(llm, "complete_json", lambda *args, **kwargs: deepcopy(payload))
    result = plan(project["id"], "r1")
    assert len(result["notes"]) == 2
    for shot in result["shots"]:
        assert shot["params"] == planner.PARAM_DEFAULTS[shot["kind"]]
        if shot["kind"] in {"title", "outro", "data_card"}:
            assert shot["source"] == "graphic"
    assert result["analogies"] == []


def test_repair_only_blocks_and_noop(sample, monkeypatch):
    plan(sample, "r1")
    def forbidden(*args, **kwargs):
        pytest.fail("无阻断不应调用模型")
    monkeypatch.setattr(llm, "complete_json", forbidden)
    assert repair(sample, "r1", [{"severity": "warn", "shot": "S1"}]) == storage.read_json(sample, "shotlist.json")


@pytest.mark.parametrize("replacements", [[], [raw_shot(id="S99")], [raw_shot(id="S3"), raw_shot(id="S3")]])
def test_repair_rejects_wrong_set_without_partial_write(sample, monkeypatch, replacements):
    plan(sample, "r1")
    before = storage.read_json(sample, "shotlist.json")
    monkeypatch.setattr(llm, "complete_json", lambda *args, **kwargs: {"shots": replacements})
    with pytest.raises(llm.LLMError):
        repair(sample, "r1", [{"severity": "block", "shot": "S3"}])
    assert storage.read_json(sample, "shotlist.json") == before


def test_edit_recomputes_analogies_after_fact_change(sample, monkeypatch):
    plan(sample, "r1")
    facts = storage.read_json(sample, "facts.json")
    next(f for f in facts["facts"] if f["id"] == "F_girder_length")["value"] = 210
    storage.write_json(sample, "facts.json", facts)
    monkeypatch.setattr(llm, "complete_json", lambda *args, **kwargs: {"shots": [raw_shot("model_orbit", id="S3")]})
    result = repair(sample, "r1", [{"severity": "block", "shot": "S3"}])
    assert next(a for a in result["analogies"] if a["ref"] == "football_field")["ratio"] == 2
