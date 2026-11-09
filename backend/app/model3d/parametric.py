"""根据已核验的尺寸构建双梁门式起重机。"""

from pathlib import Path
from typing import Any

import numpy as np
import trimesh

from .glbinfo import read_glb_nodes, triangle_count
from .rig import _dimensions


COLORS = {
    "steel": "dfe3e8", "red": "c0392b", "trolley": "e3a92b",
    "hook": "f2c230", "rail": "4a4f55", "railings": "f0f0f0", "window": "1d2a38",
}
NODES = [
    "crane", "girder", "leg_left", "leg_right", "trolley", "hoist_hook",
    "rope", "rail_left", "rail_right", "cab",
]


def _translation(position: tuple[float, float, float]) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 3] = position
    return matrix


def _box(size: tuple[float, float, float], center: tuple[float, float, float]) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=size, transform=_translation(center))


def _bar(start: tuple, end: tuple, width: float, depth: float) -> trimesh.Trimesh:
    direction = np.subtract(end, start)
    mesh = trimesh.creation.box(extents=(width, depth, np.linalg.norm(direction)))
    matrix = trimesh.geometry.align_vectors([0, 0, 1], direction)
    matrix[:3, 3] = np.add(start, end) / 2
    mesh.apply_transform(matrix)
    return mesh


def _column(x: float, bottom: float, top: float, z: float) -> trimesh.Trimesh:
    vertices = [
        [x + dx * width / 2, y, center_z + dz * width / 2]
        for y, center_z, width in ((bottom, z * 9, 2.4), (top, z * 3.2, 2.0))
        for dx, dz in ((-1, -1), (-1, 1), (1, 1), (1, -1))
    ]
    faces = [
        [0, 1, 2], [0, 2, 3], [4, 7, 6], [4, 6, 5],
        [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0],
    ]
    return trimesh.Trimesh(vertices=vertices, faces=np.asarray(faces)[:, ::-1])


def _cylinder(radius: float, start: tuple, end: tuple) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(radius=radius, segment=[start, end], sections=16)


def build_parametric(facts: dict[str, float], out_glb: Path) -> dict[str, Any]:
    used = _dimensions(facts)
    length, height = used["F_girder_length"], used["F_overall_height"]
    span, gh = used["F_span"], used["F_girder_height"]
    girder_top = height - 5.5
    girder_bottom = girder_top - gh
    hook_height = 0.6 * height
    hook_top = hook_height + 4.1
    if span < 12 or span + 2.4 > length or girder_bottom <= 5 or hook_top >= girder_top:
        raise ValueError("参数无法容纳支腿、小车或吊钩，请检查跨度、主梁及整机高度")

    scene = trimesh.Scene()
    scene.graph.update(frame_to="crane", frame_from=scene.graph.base_frame, matrix=np.eye(4))
    for node in NODES[1:]:
        parent = "trolley" if node in ("hoist_hook", "rope") else "crane"
        position = (0, 0, 0)
        if node == "trolley":
            position = (0, girder_top, 0)
        elif node == "hoist_hook":
            position = (0, hook_height - girder_top, 0)
        scene.graph.update(frame_to=node, frame_from=parent, matrix=_translation(position))
    counters: dict[str, int] = {}

    def add(node: str, mesh: trimesh.Trimesh, color: str = "steel") -> None:
        rgb = bytes.fromhex(COLORS[color])
        material = trimesh.visual.material.PBRMaterial(
            baseColorFactor=list(rgb) + [255], metallicFactor=0.65, roughnessFactor=0.38,
        )
        mesh.visual = trimesh.visual.TextureVisuals(material=material)
        counters[node] = counters.get(node, 0) + 1
        name = f"{node}_part_{counters[node]:03d}"
        scene.add_geometry(mesh, node_name=name, geom_name=name, parent_node_name=node)

    for node, x in (("rail_left", -span / 2), ("rail_right", span / 2)):
        add(node, _box((0.6, 0.3, 120), (x, 0.15, 0)), "rail")

    for node, x in (("leg_left", -span / 2), ("leg_right", span / 2)):
        add(node, _box((2.5, 2, 22), (x, 2.3, 0)), "red")
        for side in (-1, 1):
            add(node, _column(x, 3.3, girder_bottom, side))
            for z in (6.4, 7.8, 9.2, 10.6):
                add(node, _box((2.2, 1, 1.1), (x, 0.8, side * z)), "rail")
        mid_y = (3.3 + girder_bottom) / 2
        add(node, _box((1.3, 1.3, 12.2), (x, mid_y, 0)))
        if node == "leg_left":
            add(node, _bar((x, 3.3, 0), (x + 5, girder_bottom, 0), 1.4, 1.4))

    for z in (-3.2, 3.2):
        add("girder", _box((length, gh, 2.6), (0, girder_top - gh / 2, z)))
        add("girder", _box((length, 0.18, 0.8), (0, girder_top + 0.09, z + np.sign(z) * 1.7)))
        for rise in (0.55, 1.1):
            add("girder", _box((length, 0.09, 0.09), (0, girder_top + rise, z + np.sign(z) * 2.05)), "railings")
        for x in np.arange(-length / 2 + 0.1, length / 2, 4):
            add("girder", _box((0.09, 1.1, 0.09), (x, girder_top + 0.55, z + np.sign(z) * 2.05)), "railings")
    for x in np.arange(-length / 2 + 4, length / 2, 8):
        add("girder", _box((0.7, 1.2, 6.4), (x, girder_top - 1.2, 0)))
    for x in (-length / 2 + 0.6, length / 2 - 0.6):
        add("girder", _box((1.2, gh, 9), (x, girder_top - gh / 2, 0)), "red")

    cab_y = girder_bottom * 0.7
    add("cab", _box((4, 3, 3), (-span / 2 + 3, cab_y, 0)))
    add("cab", _box((4.04, 1.25, 3.04), (-span / 2 + 3, cab_y + 0.35, 0)), "window")
    add("cab", _bar((-span / 2 + 3, cab_y + 1.5, 0), (-span / 2 + 3, girder_bottom, 0), 0.5, 0.5))

    add("trolley", _box((12, 4.5, 9), (0, 2.25, 0)), "trolley")
    add("trolley", _box((7, 1, 5), (0, 5, 0)), "trolley")
    for z in (-3.5, 3.5):
        add("trolley", _cylinder(0.65, (-3, 4.7, z), (3, 4.7, z)), "rail")

    add("hoist_hook", _box((3, 2.5, 3), (0, 2.85, 0)), "hook")
    ring = trimesh.creation.torus(major_radius=0.8, minor_radius=0.2, major_sections=24, minor_sections=10)
    ring.apply_translation((0, 1, 0))
    add("hoist_hook", ring, "hook")
    add("hoist_hook", _cylinder(0.28, (0, 1.5, 0), (0, 2, 0)), "hook")

    ropes = trimesh.util.concatenate([
        _cylinder(0.08, (x, -1, z), (x, 0, z))
        for x in (-1, 1) for z in (-1, 1)
    ])
    ropes.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[74, 79, 85, 255], metallicFactor=0.8, roughnessFactor=0.4,
    ))
    rope_matrix = np.diag([1.0, girder_top - hook_top, 1.0, 1.0])
    scene.add_geometry(ropes, node_name="rope", geom_name="rope", parent_node_name="trolley", transform=rope_matrix)

    out_glb = Path(out_glb)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    out_glb.write_bytes(scene.export(file_type="glb"))
    exported = {node["name"]: node for node in read_glb_nodes(out_glb)}
    for node in NODES:
        expected = None if node == "crane" else "trolley" if node in ("rope", "hoist_hook") else "crane"
        if node not in exported or exported[node]["parent"] != expected:
            raise ValueError(f"导出模型节点层级错误：{node}")
    if triangle_count(out_glb) >= 60_000:
        raise ValueError("模型三角面数量超过限制")
    return {
        "glb": str(out_glb), "bbox_m": dict(zip("xyz", map(float, scene.extents))),
        "used": used, "assumed": [key for key in used if key not in facts], "nodes": NODES.copy(),
    }
