"""用固定参照尺寸计算类比，不接受生成的比例。"""
import math

REFS = {
    "football_field": {"name": "标准足球场", "size": 105, "unit": "m", "axes": ["length"], "basis": "国际足联推荐比赛场地长105米"},
    "building_floor": {"name": "层住宅楼", "size": 3.0, "unit": "m", "axes": ["height"], "basis": "住宅层高约3米"},
    "boeing747": {"name": "波音747的翼展", "size": 64.4, "unit": "m", "axes": ["length"], "basis": "波音747-400翼展约64.4米"},
    "bus": {"name": "辆12米长的公交车", "size": 12, "unit": "m", "axes": ["length"], "basis": "城市公交车长约12米"},
    "person": {"name": "个成年人", "size": 1.75, "unit": "m", "axes": ["height"], "basis": "成年人身高约1.75米"},
    "car": {"name": "辆小轿车", "size": 1.5, "unit": "t", "axes": ["mass"], "basis": "家用轿车约1.5吨"},
    "elephant": {"name": "头成年非洲象", "size": 6, "unit": "t", "axes": ["mass"], "basis": "成年非洲象约6吨"},
    "hair": {"name": "根头发丝", "size": 0.07, "unit": "mm", "axes": ["thickness"], "basis": "头发丝直径约0.07毫米"},
}
UNIT_SCALE = {"m": ("length", 1.0), "mm": ("length", .001), "t": ("mass", 1.0)}


def compute(analogy_id: str, fact: dict, ref: str, axis: str) -> dict:
    if ref not in REFS:
        raise ValueError("未知的类比参照物")
    item = REFS[ref]
    if axis not in item["axes"]:
        raise ValueError(f"参照物不支持该类比方向：{axis}")
    unit = fact["unit"]
    if unit not in UNIT_SCALE or UNIT_SCALE[unit][0] != UNIT_SCALE[item["unit"]][0]:
        raise ValueError("参数与参照物的单位无法换算")
    value = float(fact["value"]) * UNIT_SCALE[unit][1] / UNIT_SCALE[item["unit"]][1]
    if not math.isfinite(value) or value < 0:
        raise ValueError("类比参数必须为有限非负数")
    ratio = value / item["size"]
    if .9 <= ratio <= 1.1 and ref in {"football_field", "boeing747"}:
        text = "差不多就是一个标准足球场那么长" if ref == "football_field" else "差不多和波音747的翼展一样宽"
    elif ref == "building_floor":
        text = f"相当于{round(ratio)}层楼那么高"
    elif ref in {"car", "elephant"}:
        text = f"相当于{round(ratio)}{item['name']}的重量"
    elif ref == "hair":
        text = "还不到一根头发丝粗" if ratio < 1 else f"大约只有{round(ratio)}根头发丝并排那么宽"
    else:
        number = f"{ratio:.1f}" if ratio < 10 else str(round(ratio))
        text = f"相当于{number}{item['name']}"
    return {"id": analogy_id, "fact": fact["id"], "ref": ref, "axis": axis,
            "ratio": round(ratio, 3), "text": text,
            "ref_size_m": item["size"] * UNIT_SCALE[item["unit"]][1] if axis in {"length", "height"} else item["size"],
            "basis": item["basis"], "formula": f"{value:g} ÷ {item['size']:g} ≈ {ratio:.2f}"}
