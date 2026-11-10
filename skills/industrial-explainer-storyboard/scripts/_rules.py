"""镜头默认值、来源及运动规则；与后端保持一致。"""
import math

PARAM_DEFAULTS = {
    "title": {"title": "", "subtitle": ""},
    "outro": {"title": "", "subtitle": ""},
    "model_orbit": {"from_deg": -30, "to_deg": 30, "elevation_deg": 15, "distance": 1.6, "highlight": ["girder"]},
    "analogy": {"analogy": ""},
    "motion": {"axis": "trolley", "from_m": -30, "to_m": 30},
    "exploded": {"parts": ["girder", "leg_left", "leg_right", "trolley"], "spread_m": 12},
    "data_card": {"facts": ["F_rated_load", "F_span"]},
    "real_media": {"asset": "IMG_01", "effect": "kenburns", "caption": ""},
    "ai_broll": {"recipe": "sunrise_port", "palette": "warm", "prompt": ""},
    "weld_macro": {"fact": "F_weld_tolerance", "analogy": ""},
}

def expected_source(kind: str, model: dict | None) -> str:
    if kind == "ai_broll":
        return "ai"
    if kind == "real_media":
        return "real"
    if kind in {"title", "outro", "data_card"} and not model:
        return "graphic"
    return "model"

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
