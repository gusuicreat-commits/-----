"""读取模型节点和三角面统计，不加载网格库。"""

import json
import struct
from pathlib import Path
from typing import Any


def _read_document(path: Path) -> dict[str, Any]:
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError("模型文件头不完整")
    magic, version, size = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or size != len(data):
        raise ValueError("模型文件格式或长度无效")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A or length > len(data) - 20:
        raise ValueError("模型缺少有效的 JSON 数据块")
    try:
        return json.loads(data[20 : 20 + length])
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("模型 JSON 数据无效") from exc


def read_glb_nodes(path: Path) -> list[dict[str, Any]]:
    document = _read_document(path)
    nodes = document.get("nodes", [])
    parents = {
        child: node.get("name", "")
        for node in nodes
        for child in node.get("children", [])
    }
    return [
        {"name": node.get("name", ""), "parent": parents.get(i), "mesh": "mesh" in node}
        for i, node in enumerate(nodes)
    ]


def triangle_count(path: Path) -> int:
    document = _read_document(path)
    total = 0
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            accessor = primitive.get("indices", primitive["attributes"]["POSITION"])
            count = document["accessors"][accessor]["count"]
            mode = primitive.get("mode", 4)
            if mode == 4:
                total += count // 3
            elif mode in (5, 6):
                total += max(0, count - 2)
    return total
