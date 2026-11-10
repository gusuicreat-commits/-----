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


def find_duplicate_phrases(text: str) -> list[str]:
    found = []
    # 前瞻保留重叠匹配；单字叠词和纯标点不构成重复短语。
    for match in re.finditer(r"(?=(.{2,6})\1)", text):
        phrase = match[1]
        if not any(char.isalnum() for char in phrase):
            continue
        if len(phrase) == 2 and phrase[0] == phrase[1]:
            continue
        found.append(phrase * 2)
    for match in re.finditer(
        r"那么高那么|那么宽粗细|那么宽那么|相当于相当于|差不多相当于差不多"
        r"|(相当于|差不多|大约)[^，。！？；、\n]{0,8}?\1", text
    ):
        found.append(match[0])
    return list(dict.fromkeys(found))


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


def resolve_shots(facts_data: dict, shotlist: dict, analogies_data: dict | None = None) -> dict:
    facts = {f['id']: f for f in facts_data['facts']}
    analogies = {a['id']: a for a in (analogies_data or shotlist).get('analogies', [])}
    rows = []
    for shot in shotlist['shots']:
        text = resolve(shot['narration'], facts, analogies)
        rows.append({'id': shot['id'], 'narration_resolved': text, 'characters': len(text),
                     'estimated_duration_s': round(len(text) / 4.5 + .8, 3),
                     'duration_s': shot['duration_s'], 'unresolved': PLACEHOLDER.findall(text),
                     'duplicate_phrases': find_duplicate_phrases(text)})
    return {'shots': rows, 'estimated_duration_s': round(sum(s['estimated_duration_s'] for s in rows), 3)}


def main(argv: list[str] | None = None) -> int:
    from pathlib import Path
    from skill_io import Parser, fail, read_json, write_json
    parser = Parser(description='展开每镜头台词，统计字数及含 0.8 秒余量的估算时长。')
    parser.add_argument('--facts', type=Path, required=True, help='参数表 JSON')
    parser.add_argument('--shotlist', type=Path, required=True, help='分镜 JSON')
    parser.add_argument('--analogies', type=Path, help='计算后的类比表；省略时使用分镜内 analogies')
    parser.add_argument('--out', type=Path, required=True, help='展开台词报告路径')
    parser.add_argument('--shotlist-out', type=Path, help='另存合并类比和展开文本后的分镜，保留人工台词')
    args = parser.parse_args(argv)
    try:
        facts, shotlist = read_json(args.facts), read_json(args.shotlist)
        analogies = read_json(args.analogies) if args.analogies else None
        result = resolve_shots(facts, shotlist, analogies)
        write_json(args.out, result)
        if args.shotlist_out:
            if analogies is not None:
                shotlist['analogies'] = analogies['analogies']
            for shot, row in zip(shotlist['shots'], result['shots']):
                shot['narration_resolved'] = row['narration_resolved']
            write_json(args.shotlist_out, shotlist)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return fail(exc)
    return 1 if any(s['unresolved'] for s in result['shots']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
