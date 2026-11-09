"""参数占位解析和无出处数字识别。"""
import re

UNITS = {"m": "米", "mm": "毫米", "t": "吨", "个": "个", "%": "%"}
PLACEHOLDER = re.compile(r"\{\{([FA]_[A-Za-z0-9_]+)\}\}")
MEASURES = ("个足球场", "吨位", "公里", "千米", "毫米", "厘米", "分钟", "小时",
            "米", "吨", "秒", "层", "倍", "辆", "根", "头", "年", "天", "%", "成")
CLASSIFIERS = ("台", "个", "座", "条", "根", "辆", "块", "种", "次", "起", "下", "样", "边", "点")
IDIOMS = ("第一", "之一", "一起", "一直", "一定", "统一", "唯一", "万一")
CN_NUMBER = r"[零〇一二两三四五六七八九十百千万亿]+(?:点[零一二三四五六七八九]+)?"
NUMBER_RULES = (
    re.compile(r"\d+(?:\.\d+)?"),
    re.compile(rf"(?P<number>{CN_NUMBER})(?P<unit>{'|'.join(MEASURES)})"),
)


def format_value(value: float, unit: str) -> str:
    number = str(int(value)) if float(value).is_integer() else str(value)
    return f"每分钟{number}米" if unit == "m/min" else number + UNITS.get(unit, unit)


def resolve(narration: str, facts_by_id: dict[str, dict], analogies_by_id: dict[str, dict]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match[1]
        if key.startswith("F_") and key in facts_by_id:
            fact = facts_by_id[key]
            return format_value(fact["value"], fact["unit"])
        if key.startswith("A_") and key in analogies_by_id:
            return analogies_by_id[key]["text"]
        return match[0]
    return PLACEHOLDER.sub(replace, narration)


def find_unsourced_numbers(text_without_placeholders: str) -> list[str]:
    text = text_without_placeholders
    # 掩去固定词语，保持原文偏移；计量表达「第一百米」不能被豁免。
    for idiom in IDIOMS:
        text = re.sub(re.escape(idiom) + rf"(?![零〇一二两三四五六七八九十百千万亿]|{'|'.join(MEASURES)})",
                      lambda m: " " * len(m[0]), text)
    found: list[tuple[int, str]] = []
    for index, rule in enumerate(NUMBER_RULES):
        for match in rule.finditer(text):
            if index == 1 and match["number"] in {"一", "两"} and match["unit"] in CLASSIFIERS:
                tail = text[match.end():]
                if not tail.startswith(MEASURES):
                    continue
            found.append((match.start(), match[0]))
    return [value for _, value in sorted(found)]
