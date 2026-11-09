"""三维模型生成、导入及核验的纯文件接口。"""

from .glbinfo import read_glb_nodes, triangle_count
from .parametric import build_parametric
from .rig import build_rig, dims_check, motion_speedup
from .step import import_step

__all__ = [
    "build_parametric", "build_rig", "dims_check", "import_step",
    "motion_speedup", "read_glb_nodes", "triangle_count",
]
