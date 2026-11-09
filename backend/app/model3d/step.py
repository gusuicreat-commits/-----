"""导入装配模型，统一单位、朝向和运动节点。"""

from pathlib import Path
import re
from tempfile import TemporaryDirectory
from typing import Any

import cascadio
import numpy as np
import trimesh

from .glbinfo import read_glb_nodes
from .rig import dims_check


KEYWORDS = {
    "girder": ("主梁", "girder", "beam", "main_beam"),
    "leg_left": ("刚性腿", "支腿1", "leg_l", "rigid_leg", "leg1"),
    "leg_right": ("柔性腿", "支腿2", "leg_r", "flexible_leg", "leg2"),
    "trolley": ("小车", "trolley", "crab"),
    "hoist_hook": ("吊钩", "吊具", "hook"),
    "cab": ("司机室", "cab"),
    "rail": ("轨道", "rail"),
}


def import_step(step_path: Path, out_glb: Path) -> dict[str, Any]:
    step_path, out_glb = Path(step_path), Path(out_glb)
    if not step_path.is_file():
        raise ValueError(f"模型文件不存在：{step_path}")
    with TemporaryDirectory(prefix="kepu-step-") as temporary:
        converted = Path(temporary) / "converted.glb"
        cascadio.step_to_glb(
            str(step_path), str(converted), tol_linear=0.05, tol_angular=0.5, merge_primitives=True,
        )
        if not converted.is_file():
            raise ValueError("模型转换未生成文件")
        source = trimesh.load_scene(converted)
        original_nodes = {item["name"]: item for item in read_glb_nodes(converted)}
    if source.bounds is None or not source.geometry:
        raise ValueError("模型不包含有效网格")
    oversized = max(source.extents) > 1000
    # 转换器可能已将毫米换算为米；源单位与网格缩放需分别判断。
    source_text = step_path.read_text(encoding="utf-8", errors="replace")
    source_mm = re.search(r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", source_text, re.I)
    unit = "mm" if oversized or source_mm else "m"
    scale = 0.001 if oversized else 1.0
    dimensions = source.extents * scale
    rotated = bool(dimensions[0] >= max(dimensions[1:]) and dimensions[2] > dimensions[1])
    alignment = np.diag([scale, scale, scale, 1.0])
    if rotated:
        alignment = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ alignment

    parts: list[tuple[str, str | None, trimesh.Trimesh]] = []
    for name in sorted(source.graph.nodes_geometry):
        transform, geometry = source.graph[name]
        mesh = source.geometry[geometry].copy()
        mesh.apply_transform(alignment @ transform)
        # 产品名称可能在网格节点的祖先上，优先采用最近的匹配名称。
        candidate: str | None = str(name)
        mapped = None
        visited: set[str] = set()
        while candidate is not None and candidate not in visited:
            visited.add(candidate)
            lowered = candidate.casefold()
            try:
                repaired = candidate.encode("latin1").decode("utf-8")
                lowered = repaired.casefold()
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            mapped = next((key for key, words in KEYWORDS.items() if any(word in lowered for word in words)), None)
            if mapped:
                break
            candidate = original_nodes.get(candidate, {}).get("parent")
        parts.append((str(name), mapped, mesh))

    bounds = np.array([mesh.bounds for _, _, mesh in parts])
    low, high = bounds[:, 0].min(axis=0), bounds[:, 1].max(axis=0)
    offset = np.array([-(low[0] + high[0]) / 2, -low[1], -(low[2] + high[2]) / 2])
    grouped: dict[str, list[trimesh.Trimesh]] = {}
    unmapped = []
    for name, mapped, mesh in parts:
        mesh.apply_translation(offset)
        if mapped == "rail":
            mapped = "rail_left" if mesh.bounds.mean(axis=0)[0] < 0 else "rail_right"
        if mapped is None:
            unmapped.append(name)
        grouped.setdefault(mapped or "crane_misc", []).append(mesh)

    result = trimesh.Scene()
    result.graph.update(frame_to="crane", frame_from=result.graph.base_frame, matrix=np.eye(4))
    # 小车和吊钩使用局部原点，动画平移不会丢失装配初始位置。
    origins: dict[str, np.ndarray] = {"crane": np.zeros(3)}
    for node in ("trolley", "hoist_hook"):
        if node in grouped:
            node_bounds = np.array([mesh.bounds for mesh in grouped[node]])
            node_low, node_high = node_bounds[:, 0].min(axis=0), node_bounds[:, 1].max(axis=0)
            origins[node] = np.array([(node_low[0] + node_high[0]) / 2, node_low[1], (node_low[2] + node_high[2]) / 2])
    for node in sorted(grouped, key=lambda value: (value == "hoist_hook", value)):
        mesh = trimesh.util.concatenate(grouped[node])
        parent = "trolley" if node == "hoist_hook" and "trolley" in grouped else "crane"
        origin = origins.get(node, np.zeros(3))
        mesh.apply_translation(-origin)
        transform = np.eye(4)
        transform[:3, 3] = origin - origins[parent]
        result.add_geometry(mesh, node_name=node, geom_name=node, parent_node_name=parent, transform=transform)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    out_glb.write_bytes(result.export(file_type="glb"))
    return {
        "glb": str(out_glb), "bbox_m": dict(zip("xyz", map(float, result.extents))),
        "nodes": ["crane"] + sorted(node for node in grouped if node != "crane_misc"),
        "unmapped": unmapped, "unit": unit, "rotated": rotated,
    }
