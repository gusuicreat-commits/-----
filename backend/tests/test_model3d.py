from pathlib import Path

import pytest
import numpy as np
import trimesh

from app.model3d import (
    build_parametric, build_rig, dims_check, import_step, motion_speedup,
    read_glb_nodes, triangle_count,
)


FACTS = {
    "F_girder_length": 104, "F_overall_height": 51, "F_span": 88,
    "F_lift_height": 45, "F_girder_height": 6.5,
}


@pytest.fixture
def parametric(tmp_path: Path) -> dict:
    return build_parametric(FACTS, tmp_path / "crane.glb")


def test_parametric_dimensions_and_hierarchy(parametric: dict) -> None:
    result = parametric
    nodes = {node["name"]: node for node in read_glb_nodes(Path(result["glb"]))}
    assert nodes["crane"]["parent"] is None
    expected = {
        "crane": None, "girder": "crane", "leg_left": "crane", "leg_right": "crane",
        "rail_left": "crane", "rail_right": "crane", "cab": "crane", "trolley": "crane",
        "hoist_hook": "trolley", "rope": "trolley",
    }
    for name, parent in expected.items():
        assert nodes[name]["parent"] == parent
    assert set(result["nodes"]) == set(expected)
    assert result["bbox_m"]["x"] == pytest.approx(104, abs=0.5)
    assert result["bbox_m"]["y"] == pytest.approx(51, abs=0.5)
    assert result["bbox_m"]["z"] == pytest.approx(120)
    assert 0 < triangle_count(Path(result["glb"])) < 60_000
    assert result["assumed"] == []
    scene = trimesh.load_scene(result["glb"])
    assert scene.bounds[0, 1] == pytest.approx(0)
    rope_transform, rope_geometry = scene.graph["rope"]
    rope = scene.geometry[rope_geometry]
    assert rope.bounds[:, 1] == pytest.approx([-1, 0])
    assert rope_transform[1, 3] == pytest.approx(45.5)
    assert rope_transform[1, 1] == pytest.approx(45.5 - (0.6 * 51 + 4.1))
    assert scene.graph["hoist_hook"][0][1, 3] == pytest.approx(0.6 * 51)


def test_parametric_defaults(tmp_path: Path) -> None:
    result = build_parametric({"F_girder_length": 100}, tmp_path / "nested" / "default.glb")
    assert "F_span" in result["assumed"]
    assert result["used"]["F_span"] == 85
    assert len(result["assumed"]) == 4
    assert result["used"]["F_lift_height"] == pytest.approx(0.88 * 51)


def test_rig_ranges_and_provenance(parametric: dict) -> None:
    rig = build_rig(FACTS, parametric["bbox_m"], "parametric", parametric["nodes"])
    assert rig["axes"]["gantry"]["range_m"] == [-40, 40]
    assert rig["axes"]["trolley"]["range_m"] == [-38, 38]
    assert rig["axes"]["hoist"]["range_m"] == [2, 36]
    assert rig["bbox_m"] is parametric["bbox_m"]
    assert set(rig["derived_from"]) == {"F_span", "F_overall_height", "F_lift_height", "F_girder_height"}
    assert rig["kind"] == "parametric"
    assert motion_speedup(rig, "trolley", -30, 30, 6, 30) == {"real_s": 120, "speedup": 20}
    assert motion_speedup(rig, "trolley", 0, 1, 10, 60) == {"real_s": 1, "speedup": 1}
    assert motion_speedup(rig, "trolley", 0, 39, 6, 30) == {"error": "超出行程范围 [-38, 38]"}
    assert "error" in motion_speedup(rig, "hoist", 2, 10, 0, 30)
    assert "error" in motion_speedup(rig, "hoist", 2, 10, 6, 0)


def test_rig_missing_parts() -> None:
    rig = build_rig(FACTS, {}, "step", ["crane", "girder"])
    assert list(rig["axes"]) == ["gantry"]
    assert rig["derived_from"] == []
    assert "error" in motion_speedup(rig, "trolley", 0, 1, 1, 1)
    rig = build_rig({"F_girder_length": 100}, {}, "parametric", ["crane", "trolley"])
    assert rig["axes"]["trolley"]["range_m"] == [-36.5, 36.5]
    assert rig["derived_from"] == ["F_girder_length"]


def test_sample_step(tmp_path: Path) -> None:
    sample = Path(__file__).resolve().parents[2] / "samples" / "示例简化模型.step"
    result = import_step(sample, tmp_path / "imported.glb")
    assert result["unit"] == "mm"
    assert result["rotated"] is True
    assert set(result["nodes"]) >= {
        "crane", "girder", "leg_left", "leg_right", "trolley", "hoist_hook", "cab", "rail_left", "rail_right",
    }
    assert result["unmapped"] == []
    assert result["bbox_m"]["x"] == pytest.approx(104, abs=1)
    assert result["bbox_m"]["y"] == pytest.approx(51, abs=1)
    assert all(item["ok"] for item in dims_check(result["bbox_m"], FACTS))
    nodes = {node["name"]: node for node in read_glb_nodes(Path(result["glb"]))}
    assert nodes["trolley"]["parent"] == "crane"
    assert nodes["hoist_hook"]["parent"] == "trolley"
    scene = trimesh.load_scene(result["glb"])
    assert scene.bounds[0, 1] == pytest.approx(0, abs=1e-6)
    assert scene.bounds[:, [0, 2]].mean(axis=0) == pytest.approx([0, 0], abs=1e-6)


@pytest.mark.parametrize("mesh_scale", [1, 1000])
def test_step_mapping_and_transforms(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mesh_scale: int) -> None:
    from app.model3d import step

    source = trimesh.Scene()
    source.graph.update(frame_to="MAIN_BEAM", matrix=trimesh.transformations.translation_matrix([12, 10, 0]))
    source.add_geometry(trimesh.creation.box((104, 6, 3)), node_name="solid", parent_node_name="MAIN_BEAM")
    for name, position in (("TROLLEY", (4, 20, 0)), ("HOOK", (4, 5, 0)), ("other", (12, -2, 0))):
        source.add_geometry(trimesh.creation.box((2, 2, 2)), node_name=name,
                            transform=trimesh.transformations.translation_matrix(position))

    def convert(path: str, output: str, **kwargs: object) -> None:
        assert kwargs == {"tol_linear": 0.05, "tol_angular": 0.5, "merge_primitives": True}
        converted = source.copy()
        converted.apply_scale(mesh_scale)
        Path(output).write_bytes(converted.export(file_type="glb"))

    monkeypatch.setattr(step.cascadio, "step_to_glb", convert)
    input_path = tmp_path / "fixture.step"
    input_path.touch()
    result = import_step(input_path, tmp_path / "output.glb")
    assert result["unit"] == ("mm" if mesh_scale == 1000 else "m")
    assert result["rotated"] is False
    assert result["unmapped"] == ["other"]
    loaded = trimesh.load_scene(result["glb"])
    assert loaded.extents == pytest.approx(source.extents)
    assert loaded.graph["hoist_hook"][0][:3, 3] == pytest.approx([-8, 7, 0])
    assert "crane_misc" in loaded.graph.nodes


def test_dims_check() -> None:
    checked = dims_check({"x": 98.2, "y": 51}, FACTS)
    assert checked[0]["ok"] is False
    assert checked[0]["message"] == "模型长度 98.2 m 与文档主梁总长 104 m 相差 5.6%"
    assert checked[1]["ok"] is True
    assert dims_check({"x": 103, "y": 51}, {"F_girder_length": 100})[0]["ok"] is True
    assert dims_check({}, {}) == []


def test_glbinfo_invalid_header(tmp_path: Path) -> None:
    path = tmp_path / "invalid.glb"
    path.write_bytes(b"invalid")
    with pytest.raises(ValueError, match="文件头"):
        read_glb_nodes(path)


@pytest.mark.parametrize("length,height,span,gh,wheels", [(104, 51, 88, 6.5, 32), (120, 63, 96, 8, 63), (80, 42, 68, 5, 128)])
def test_detailed_model_exact_dimensions_and_wheels(
    tmp_path: Path, length: float, height: float, span: float, gh: float, wheels: int,
) -> None:
    facts = {"F_girder_length": length, "F_overall_height": height, "F_span": span,
             "F_girder_height": gh, "F_wheel_count": wheels}
    result = build_parametric(facts, tmp_path / "detailed.glb")
    scene = trimesh.load_scene(result["glb"])
    assert scene.extents[0] == pytest.approx(length, abs=.01)
    assert scene.bounds[:, 1] == pytest.approx([0, height], abs=.01)
    assert all(row["ok"] for row in dims_check(result["bbox_m"], facts))
    assert result["used"]["F_wheel_count"] == wheels
    rail_centers = []
    for node in ("rail_left_steel", "rail_right_steel"):
        matrix, geometry = scene.graph[node]
        rail_centers.append(trimesh.transform_points(scene.geometry[geometry].bounds, matrix)[:, 0].mean())
    assert rail_centers[1] - rail_centers[0] == pytest.approx(span, abs=.01)
    anchors = sorted(node for node in scene.graph.nodes if node.startswith("wheel_"))
    assert len(anchors) == wheels
    for node in anchors:
        center = scene.graph[node][0][:3, 3]
        leg = "leg_left" if center[0] < 0 else "leg_right"
        steel = scene.geometry[scene.graph[f"{leg}_steel"][1]]
        # 每个标记必须对应实际轮缘顶点，不能只靠空节点满足轮数。
        radius = center[1] - .3
        target = center + [.475, radius+.07, 0]
        assert np.linalg.norm(steel.vertices - target, axis=1).min() < .001
    assert {mesh.visual.material.name for mesh in scene.geometry.values()} == {
        "paint", "primer", "steel", "glass", "rubber", "hazard",
    }
    assert len(scene.geometry) < 35
    assert triangle_count(Path(result["glb"])) <= 300_000
    assert scene.geometry[scene.graph["leg_left_paint"][1]].volume > 0


@pytest.mark.parametrize("count", [0, 3, 4.5, float("nan"), float("inf"), 513])
def test_invalid_wheel_count(tmp_path: Path, count: float) -> None:
    with pytest.raises(ValueError, match="车轮总数"):
        build_parametric({**FACTS, "F_wheel_count": count}, tmp_path / "invalid.glb")
