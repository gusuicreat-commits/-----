"""生成尺寸与节点层级固定的门机测试夹具。"""
from pathlib import Path
import shutil
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent

def build() -> None:
    sample = ROOT / 'samples' / '示例参数化模型.glb'
    if sample.exists():
        shutil.copy2(sample, OUT / 'crane.glb')
        return
    scene = trimesh.Scene(base_frame='world')
    def group(name: str, parent: str = 'crane', pos: tuple[float, float, float] = (0, 0, 0)) -> None:
        transform = np.eye(4)
        transform[:3, 3] = pos
        scene.graph.update(frame_to=name, frame_from=parent, matrix=transform)
    def box(name: str, size: tuple[float, float, float], pos: tuple[float, float, float], color: str, parent: str = 'crane') -> None:
        geometry = trimesh.creation.box(size)
        geometry.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(baseColorFactor=trimesh.visual.color.hex_to_rgba(color), metallicFactor=.35, roughnessFactor=.4))
        matrix = np.eye(4)
        matrix[:3, 3] = pos
        scene.add_geometry(geometry, node_name=name, geom_name=name, parent_node_name=parent, transform=matrix)
    group('crane', 'world')
    group('girder')
    for side in [-1, 1]:
        box(f'beam_{side}', (104, 6.5, 3), (0, 47.75, side*5), '#d99036', 'girder')
        box(f'walkway_{side}', (104, .25, 1.5), (0, 45, side*7.3), '#c1cad1', 'girder')
        for x in range(-50, 51, 4):
            box(f'post_{side}_{x}', (.12, 1.2, .12), (x, 45.7, side*7.9), '#deded8', 'girder')
        box(f'handrail_{side}', (104, .12, .12), (0, 46.3, side*7.9), '#deded8', 'girder')
    for label, x in [('left', -44), ('right', 44)]:
        group(f'leg_{label}')
        for z in [-6, 6]:
            box(f'column_{label}_{z}', (3.3, 43, 3), (x, 23, z), '#d99036', f'leg_{label}')
        box(f'base_{label}', (5, 2, 20), (x, 2, 0), '#3c5264', f'leg_{label}')
        for z in [-8, -5, -2, 2, 5, 8]:
            box(f'wheel_{label}_{z}', (4, 1, .9), (x, .5, z), '#253341', f'leg_{label}')
        box(f'rail_{label}', (.35, .2, 160), (x, 0, 0), '#74858d', 'world')
    group('trolley', pos=(0, 48, 0))
    box('trolley_body', (12, 3, 12), (0, 1.5, 0), '#dce3e5', 'trolley')
    box('hoist_hook', (3, 3, 2), (0, -25, 0), '#f29a27', 'trolley')
    box('rope', (.13, 25, .13), (0, -12.5, 0), '#a4b4bc', 'trolley')
    box('cab', (4, 4, 4), (-36, 42, 7), '#4e90a9')
    (OUT / 'crane.glb').write_bytes(scene.export(file_type='glb'))

if __name__ == '__main__':
    build()
