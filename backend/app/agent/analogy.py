"""用固定参照尺寸计算类比，不接受生成的比例。"""
import math
import re
import unicodedata

REFS = {
    "football_field": {"name": "标准足球场", "size": 105, "unit": "m", "axes": ["length"], "basis": "国际足联推荐比赛场地长105米"},
    "building_floor": {"name": "层住宅楼", "size": 3.0, "unit": "m", "axes": ["height"], "basis": "住宅层高约3米"},
    "boeing747": {"name": "个波音747的翼展", "size": 64.4, "unit": "m", "axes": ["length"], "basis": "波音747-400翼展约64.4米"},
    "bus": {"name": "辆12米长的公交车", "size": 12, "unit": "m", "axes": ["length"], "basis": "城市公交车长约12米"},
    "person": {"name": "个成年人", "size": 1.75, "unit": "m", "axes": ["height"], "basis": "成年人身高约1.75米"},
    "car": {"name": "辆小轿车", "size": 1.5, "unit": "t", "axes": ["mass"], "basis": "家用轿车约1.5吨"},
    "elephant": {"name": "头成年非洲象", "size": 6, "unit": "t", "axes": ["mass"], "basis": "成年非洲象约6吨"},
    "hair": {"name": "根头发丝", "size": 0.07, "unit": "mm", "axes": ["thickness"], "basis": "头发丝直径约0.07毫米"},
}
UNIT_SCALE = {"m": ("length", 1.0), "mm": ("length", .001), "t": ("mass", 1.0)}


def comparison_valid(word: str, number: float, ratio: float) -> bool:
    if not all(math.isfinite(v) and v >= 0 for v in (number, ratio)):
        return False
    error = abs(number - ratio) / ratio if ratio else (0 if number == 0 else math.inf)
    if word in {'约', '大约', '大约只有'}:
        return error <= .10 + 1e-12
    if word in {'接近', '相当于', '差不多'}:
        return error <= .05 + 1e-12
    if word == '超过':
        return ratio > number
    if word == '几乎':
        return number > ratio and error <= .05 + 1e-12
    if word == '还不到':
        return ratio < number
    return False


def wording_valid(text: str, ratio: float, ref: str) -> bool:
    text = unicodedata.normalize('NFKC', text)
    if text in {'差不多就是一个标准足球场那么长', '差不多和波音747的翼展一样宽'}:
        expected_ref = 'football_field' if '足球场' in text else 'boeing747'
        return ref == expected_ref and comparison_valid('差不多', 1, ratio)
    if text == '还不到一根头发丝粗':
        return ref == 'hair' and ratio < 1
    match = re.fullmatch(r'(大约只有|相当于|接近|超过|几乎|大约|约)([0-9]+(?:\.[0-9]+)?(?:e[-+]?\d+)?)(.+)', text)
    if not match:
        return False
    suffixes = {REFS[ref]['name']}
    if ref == 'building_floor':
        suffixes.add('层楼那么高')
    if ref in {'car', 'elephant'}:
        suffixes.add(REFS[ref]['name'] + '的重量')
    if ref == 'hair':
        suffixes.add('根头发丝并排那么宽')
    return match[3] in suffixes and comparison_valid(match[1], float(match[2]), ratio)


def safe_number(ratio: float, word: str, integer: bool = False) -> str:
    candidate = str(round(ratio)) if integer or ratio >= 10 else f'{ratio:.1f}'
    if comparison_valid(word, float(candidate), ratio):
        return candidate
    return format(ratio, '.12g')


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
    if comparison_valid("差不多", 1, ratio) and ref in {"football_field", "boeing747"}:
        text = "差不多就是一个标准足球场那么长" if ref == "football_field" else "差不多和波音747的翼展一样宽"
    elif ref == "building_floor":
        text = f'相当于{safe_number(ratio, "相当于", True)}层楼那么高'
    elif ref in {"car", "elephant"}:
        text = f'相当于{safe_number(ratio, "相当于", True)}{item["name"]}的重量'
    elif ref == "hair":
        text = "还不到一根头发丝粗" if ratio < 1 else f'大约只有{safe_number(ratio, "大约", True)}根头发丝并排那么宽'
    else:
        number = safe_number(ratio, "相当于")
        text = f"相当于{number}{item['name']}"
    return {"id": analogy_id, "fact": fact["id"], "ref": ref, "axis": axis,
            "ratio": round(ratio, 3), "text": text,
            "ref_size_m": item["size"] * UNIT_SCALE[item["unit"]][1] if item["unit"] != "t" else None,
            "ref_size": item["size"], "ref_unit": item["unit"],
            "basis": item["basis"], "formula": f"{value:g} ÷ {item['size']:g} ≈ {ratio:.2f}"}


def preview(fact: dict, ref: str, axis: str) -> str:
    return compute("", fact, ref, axis)["text"]
