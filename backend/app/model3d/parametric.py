"""由尺寸参数生成分材质、保留运动层级的门机。"""

from pathlib import Path
from typing import Any
import math

import numpy as np
import trimesh

from .glbinfo import read_glb_nodes, triangle_count
from .rig import _dimensions

COLORS = {"paint": "d9461c", "primer": "e4e6e5", "steel": "636d75",
          "glass": "54778b", "rubber": "24282b", "hazard": "e9af32"}
NODES = ["crane", "girder", "leg_left", "leg_right", "trolley", "hoist_hook",
         "rope", "rail_left", "rail_right", "cab"]
Point = tuple[float, float, float]


def _translation(position: Point) -> np.ndarray:
    matrix = np.eye(4)
    matrix[:3, 3] = position
    return matrix


def _box(size: Point, center: Point) -> trimesh.Trimesh:
    return trimesh.creation.box(extents=size, transform=_translation(center))


def _cylinder(radius: float, start: Point, end: Point) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(radius=radius, segment=[start, end], sections=16)


def _column(x: float, bottom: float, top: float, side: int, gh: float) -> trimesh.Trimesh:
    vertices = [[x + dx * 1.5, y, side * z + dz * width / 2]
                for y, z, width in ((bottom, gh*(3.2-.85)/2, gh*.85), (top, gh*(1.2-.38)/2, gh*.38))
                for dx, dz in ((-1, -1), (-1, 1), (1, 1), (1, -1))]
    mesh = trimesh.Trimesh(vertices=vertices, faces=[
        [0, 1, 2], [0, 2, 3], [4, 7, 6], [4, 6, 5], [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
    mesh.invert()
    return mesh


def build_parametric(facts: dict[str, float], out_glb: Path) -> dict[str, Any]:
    used = _dimensions(facts)
    length, height = used["F_girder_length"], used["F_overall_height"]
    span, gh = used["F_span"], used["F_girder_height"]
    top, bottom = height - 5.5, height - 5.5 - gh
    hook_height = .6 * height
    raw_count = float(facts.get("F_wheel_count", 32))
    if not math.isfinite(raw_count) or raw_count != int(raw_count) or not 4 <= raw_count <= 512:
        raise ValueError("车轮总数必须为 4 至 512 的整数")
    wheel_count = int(raw_count)
    if "F_wheel_count" in facts:
        used["F_wheel_count"] = wheel_count
    if span < 12 or span + 3.2 > length or bottom <= 5 or hook_height + 4.1 >= top:
        raise ValueError("参数无法容纳支腿、小车或吊钩，请检查跨度、主梁及整机高度")
    scene = trimesh.Scene()
    scene.graph.update(frame_to="crane", frame_from=scene.graph.base_frame, matrix=np.eye(4))
    for node in NODES[1:]:
        pos = (0, top, 0) if node == "trolley" else (0, hook_height-top, 0) if node == "hoist_hook" else (0, 0, 0)
        scene.graph.update(frame_to=node, frame_from="trolley" if node in ("rope", "hoist_hook") else "crane",
                           matrix=_translation(pos))
    materials = {name: trimesh.visual.material.PBRMaterial(
        name=name, baseColorFactor=list(bytes.fromhex(color))+[255],
        metallicFactor=.85 if name == "steel" else .15, roughnessFactor=.38)
        for name, color in COLORS.items()}
    batches: dict[tuple[str, str], list[trimesh.Trimesh]] = {}

    def add(node: str, mesh: trimesh.Trimesh, material: str = "paint") -> None:
        batches.setdefault((node, material), []).append(mesh)

    def box(node: str, size: Point, pos: Point, material: str = "paint") -> None:
        add(node, _box(size, pos), material)

    def rod(node: str, a: Point, b: Point, radius: float, material: str = "paint") -> None:
        add(node, _cylinder(radius, a, b), material)

    for node, x in (("rail_left", -span/2), ("rail_right", span/2)):
        for width, h, y in ((.6, .07, .035), (.12, .16, .15), (.3, .07, .265)):
            box(node, (width, h, 120), (x, y, 0), "steel")
    for sign in (-1, 1):
        z = sign * 3.2
        box("girder", (length, gh, 2.6), (0, top-gh/2, z))
        for face in (-1, 1):
            for x in np.arange(-length/2+.2, length/2-.1, 2.5):
                box("girder", (.16, gh-.18, .15), (x, top-gh/2, z+face*1.375))
        for y in (bottom+.08, top-.08):
            box("girder", (length, .16, 2.76), (0, y, z))
        box("girder", (length, .16, .85), (0, top+.08, sign*4.9))
        for y in (top+.58, top+1.13):
            box("girder", (length, .085, .085), (0, y, sign*5.25))
        for x in np.linspace(-length/2+.06, length/2-.06, math.ceil(length/2.5)+1):
            box("girder", (.085, 1.01, .085), (x, top+.665, sign*5.25))
        box("girder", (length, .12, .18), (0, top+.06, z), "steel")
        box("girder", (1.2, gh, 9), (sign*(length/2-.6), top-gh/2, 0))
    for x in np.arange(-length/2+4, length/2, 8):
        box("girder", (.7, 1.2, 6.4), (x, bottom+.6, 0))

    wheel_index = 0
    for leg_index, (node, x) in enumerate((("leg_left", -span/2), ("leg_right", span/2))):
        box(node, (2.4, 1.4, 22), (x, 2.6, 0))
        for side_index, side in enumerate((-1, 1)):
            if leg_index == 0:
                add(node, _column(x, 3.3, bottom, side, gh))
            else:
                rod(node, (x, 3.3, side*8.8), (x, bottom, side*3.2), .8)
                rod(node, (x-.95, bottom-.35, side*3.2), (x+.95, bottom-.35, side*3.2), .9)
                box(node, (1.8, .3, 2), (x, bottom-.1, side*3.2))
            corner = leg_index*2+side_index
            count = wheel_count//4 + (corner < wheel_count % 4)
            spacing = 8.4/count
            radius = min(.62, spacing*.43)
            box(node, (2.35, .5, 9), (x, 1.8, side*6.4))
            for i in range(count):
                z, y = side*6.4+(i-(count-1)/2)*spacing, .3+radius
                pieces = [_cylinder(radius, (x-.4, y, z), (x+.4, y, z))]
                for dx in (-.42, .42):
                    pieces.append(_cylinder(radius+.07, (x+dx-.055, y, z), (x+dx+.055, y, z)))
                # 命名空节点保存可核查轮数；实体仍按部件和材质合并。
                scene.graph.update(frame_to=f"wheel_{wheel_index:03d}", frame_from=node,
                                   matrix=_translation((x, y, z)))
                wheel_index += 1
                add(node, trimesh.util.concatenate(pieces), "steel")
                rod(node, (x-.6, y, z), (x+.6, y, z), radius*.32)
                box(node, (1.2, .85, .16), (x, y+.46, z), "steel")
            for z in (side*6.4-4.6, side*6.4+4.6):
                rod(node, (x, 1.45, z-.16), (x, 1.45, z+.16), .3, "rubber")
        if leg_index == 0:
            for f in (.28, .54, .8):
                box(node, (3, 1.1, gh*(3.2*(1-f)+1.2*f)), (x, 3.3+(bottom-3.3)*f, 0))
            for z in (-gh*.41, gh*.41):
                box("girder", (3, 5.5, gh*.38), (x, top+2.75, z))
            box("girder", (3, .5, gh*1.2), (x, height-.25, 0))
            for z in (-.42, .42):
                rod(node, (x+1.58, 3.4, z), (x+1.58, bottom, z), .045)
            for y in np.arange(3.4, bottom, .35):
                rod(node, (x+1.58, y, -.42), (x+1.58, y, .42), .035)

    for side in (-1, 1):
        box("trolley", (12, .8, 3.3), (0, .55, side*2.85))
        box("trolley", (4.6, .8, 2.4), (side*3.7, .55, 0))
        rod("trolley", (-3, 2, side*2.7), (3, 2, side*2.7), .9, "steel")
        for x in (-3.1, 3.1):
            rod("trolley", (x-.12, 2, side*2.7), (x+.12, 2, side*2.7), 1.08)
        for x in np.arange(-2.8, 2.9, .2):
            rod("trolley", (x-.025, 2, side*2.7), (x+.025, 2, side*2.7), .925, "steel")
    box("trolley", (7, 2.1, 2.6), (0, 4.45, 0), "primer")
    box("trolley", (7.2, .12, 2.8), (0, 5.44, 0), "primer")
    for x in (-2.2, 0, 2.2):
        for i in range(9):
            box("trolley", (1.5, .07, .09), (x, 3.8+i*.15, 1.34), "steel")
    for z in (-1.3, 1.3):
        box("hoist_hook", (3, 2.5, .3), (0, 2.85, z), "hazard")
        box("hoist_hook", (3, .55, .32), (0, 2, z))
    box("hoist_hook", (3, .18, 2.6), (0, 4.01, 0), "hazard")
    for x in (-.95, -.32, .32, .95):
        rod("hoist_hook", (x-.19, 2.9, 0), (x+.19, 2.9, 0), .95, "steel")
    rod("hoist_hook", (0, 1.3, 0), (0, 2, 0), .3, "steel")
    points = [(0, 1.5, 0), (0, 1.05, 0)] + [(-.15+.65*math.cos(a), .65+.65*math.sin(a), 0)
              for a in np.linspace(math.pi/2, math.pi*1.95, 20)]
    for a, b in zip(points, points[1:]):
        rod("hoist_hook", a, b, .22, "steel")
    cab_x, cab_y = -span/2+3, bottom*.7
    rod("cab", (cab_x, cab_y+1.5, 0), (cab_x, bottom, 0), .25)
    box("cab", (4, 1, 3), (cab_x, cab_y-.8, 0))
    for y in (cab_y-1.4, cab_y+1.4):
        box("cab", (4, .2, 3), (cab_x, y, 0))
    for z in (-1.46, 1.46):
        box("cab", (3.8, 1.5, .045), (cab_x, cab_y+.5, z), "glass")
        for dx in (-1.93, 0, 1.93):
            box("cab", (.12, 1.7, .12), (cab_x+dx, cab_y+.5, z))
    for dx in (-1.96, 1.96):
        box("cab", (.045, 1.5, 2.8), (cab_x+dx, cab_y+.5, 0), "glass")

    for (node, material), meshes in batches.items():
        mesh = trimesh.util.concatenate(meshes)
        mesh.visual = trimesh.visual.TextureVisuals(material=materials[material])
        scene.add_geometry(mesh, node_name=f"{node}_{material}", geom_name=f"{node}_{material}", parent_node_name=node)
    ropes = trimesh.util.concatenate([_cylinder(.035, (x+dx, -1, z), (x+dx, 0, z))
        for x in (-.95, -.32, .32, .95) for z in (-.85, .85) for dx in (-.028, .028)])
    ropes.visual = trimesh.visual.TextureVisuals(material=materials["steel"])
    scene.add_geometry(ropes, node_name="rope", geom_name="rope", parent_node_name="trolley",
                       transform=np.diag([1., top-(hook_height+4.1), 1., 1.]))
    out_glb = Path(out_glb)
    out_glb.parent.mkdir(parents=True, exist_ok=True)
    out_glb.write_bytes(scene.export(file_type="glb"))
    exported = {node["name"]: node for node in read_glb_nodes(out_glb)}
    for node in NODES:
        expected = None if node == "crane" else "trolley" if node in ("rope", "hoist_hook") else "crane"
        if node not in exported or exported[node]["parent"] != expected:
            raise ValueError(f"导出模型节点层级错误：{node}")
    if triangle_count(out_glb) > 300_000:
        raise ValueError("模型三角面数量超过限制")
    return {"glb": str(out_glb), "bbox_m": dict(zip("xyz", map(float, scene.extents))),
            "used": used, "assumed": [key for key in used if key not in facts], "nodes": NODES.copy(),
            "wheel_count": wheel_count, "detail_assumptions": ["附属结构为示意", *([] if "F_wheel_count" in facts else ["车轮默认 32 个"])]}
