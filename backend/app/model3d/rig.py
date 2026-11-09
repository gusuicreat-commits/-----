"""生成运动范围和尺寸核验结果。"""

import math
from typing import Any, Literal


def _dimensions(facts: dict[str, float]) -> dict[str, float]:
    length = float(facts.get("F_girder_length", 104))
    height = float(facts.get("F_overall_height", 51))
    used = {
        "F_girder_length": length,
        "F_overall_height": height,
        "F_span": float(facts.get("F_span", 0.85 * length)),
        "F_lift_height": float(facts.get("F_lift_height", 0.88 * height)),
        "F_girder_height": float(facts.get("F_girder_height", 6.5)),
    }
    if any(not math.isfinite(value) or value <= 0 for value in used.values()):
        raise ValueError("模型尺寸必须是有限正数")
    return used


def build_rig(
    facts: dict[str, float], bbox_m: dict, kind: Literal["parametric", "step"], nodes: list[str]
) -> dict[str, Any]:
    if kind not in ("parametric", "step"):
        raise ValueError("模型类型必须为 parametric 或 step")
    dims = _dimensions(facts)
    axes = {
        "gantry": {"node": "crane", "axis": "z", "range_m": [-40, 40], "speed_fact": "F_gantry_speed"}
    }
    consumed = {"F_gantry_speed"}
    if "trolley" in nodes:
        limit = dims["F_span"] / 2 - 6
        if limit < 0:
            raise ValueError("跨度不足以容纳小车")
        axes["trolley"] = {
            "node": "trolley", "axis": "x", "range_m": [-limit, limit],
            "speed_fact": "F_trolley_speed",
        }
        consumed.update(("F_span", "F_trolley_speed"))
        if "F_span" not in facts:
            consumed.add("F_girder_length")
    if "hoist_hook" in nodes:
        ceiling = dims["F_overall_height"] - 5.5 - dims["F_girder_height"] - 3
        upper = min(dims["F_lift_height"], ceiling)
        if upper < 2:
            raise ValueError("主梁高度不足以提供有效起升行程")
        axes["hoist"] = {
            "node": "hoist_hook", "axis": "y", "range_m": [2, upper],
            "speed_fact": "F_hoist_speed",
        }
        consumed.update(("F_overall_height", "F_girder_height", "F_lift_height", "F_hoist_speed"))
    return {
        "axes": axes, "bbox_m": bbox_m, "kind": kind,
        "derived_from": [key for key in facts if key in consumed],
    }


def motion_speedup(
    rig: dict, axis: str, from_m: float, to_m: float, duration_s: float, speed_m_min: float
) -> dict:
    if axis not in rig["axes"]:
        return {"error": f"未配置运动轴：{axis}"}
    lower, upper = rig["axes"][axis]["range_m"]
    if not all(math.isfinite(v) for v in (from_m, to_m, duration_s, speed_m_min)):
        return {"error": "运动参数必须是有限数值"}
    if not (lower <= from_m <= upper and lower <= to_m <= upper):
        return {"error": f"超出行程范围 [{lower:g}, {upper:g}]"}
    if duration_s <= 0 or speed_m_min <= 0:
        return {"error": "时长和速度必须大于零"}
    real_s = abs(to_m - from_m) / (speed_m_min / 60)
    return {"real_s": real_s, "speedup": max(1, math.ceil(real_s / duration_s))}


def dims_check(bbox_m: dict, facts: dict[str, float]) -> list[dict]:
    results = []
    for axis, fact, title, description in (
        ("x", "F_girder_length", "长度", "主梁总长"),
        ("y", "F_overall_height", "高度", "整机高度"),
    ):
        if fact not in facts:
            continue
        model, doc = float(bbox_m[axis]), float(facts[fact])
        valid = math.isfinite(model) and math.isfinite(doc) and model > 0 and doc > 0
        error = abs(model - doc) / doc if valid else math.inf
        ok = valid and (error <= 0.03 or math.isclose(error, 0.03, abs_tol=1e-12))
        item = {"fact": fact, "model_value": model, "doc_value": doc, "ok": ok}
        if not ok:
            item["message"] = (
                f"模型{title} {model:g} m 与文档{description} {doc:g} m 相差 {error:.1%}"
                if valid else f"模型{title}或文档{description}不是有效正数"
            )
        results.append(item)
    return results
