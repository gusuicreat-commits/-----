"""出处、类比及逐句陈述审计；不调用模型或网络。"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
import unicodedata
from typing import Callable

from compute_analogy import REFS, UNIT_SCALE, compute, wording_valid
from claim_rules import TOKEN, RULES, fact_conflicts, normalized, visible_texts
from resolve_text import find_unsourced_numbers

NUMBER = r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?'
UNITS = {'米每分钟': 'm/min', '米每分': 'm/min', '米/分钟': 'm/min', '米/分': 'm/min',
         '毫米': 'mm', '厘米': 'cm', '千米': 'km', '千克': 'kg', '吨': 't', '米': 'm'}


def normalize_quantity(text: str) -> str:
    text = unicodedata.normalize('NFKC', text).casefold()
    text = re.sub(r'(?<=\d),(?=\d{3}(?:\D|$))', '', text)
    for alias, unit in UNITS.items():
        text = text.replace(alias, unit)
    return re.sub(r'\s+', '', text)


def quote_matches(fact: dict) -> bool:
    quote = normalize_quantity(str((fact.get('source') or {}).get('quote', '')))
    if fact.get('type') == 'qualitative' or isinstance(fact.get('value'), str):
        return bool(fact.get('value')) and normalize_quantity(str(fact['value'])) in quote
    try:
        value = Decimal(str(fact['value']))
        unit = normalize_quantity(str(fact.get('unit', '')))
        # 数字和单位必须相邻；不能把 1230 当作 12300 或 1230 mm 当作 m。
        pattern = rf'(?<![\d.+-])({NUMBER}){re.escape(unit)}(?![a-z/\d])'
        return value.is_finite() and any(Decimal(m[1]) == value for m in re.finditer(pattern, quote))
    except (InvalidOperation, KeyError, TypeError):
        return False


def specific_claim(text: str) -> bool:
    text = TOKEN.sub('', text)
    return bool(any(term in normalized(text) for term in RULES['specific_claim_terms'])
                or any(re.search(pattern, text, re.I) for pattern in RULES['specific_claim_patterns']))


def clauses(text: str) -> list[str]:
    """句号及分句独立计数，防止同句一个引用掩盖另一条陈述。"""
    return [p.strip() for p in re.split(r'[，,。！？!?；;\n]+', text) if p.strip()]


def claim_error(claim: dict, facts: dict, assets: dict, conflicts: set[str],
                analogies: dict | None = None) -> str | None:
    if not isinstance(claim, dict) or not isinstance(claim.get('text'), str) or not claim['text'].strip():
        return '陈述必须包含非空 text 和 support'
    support = claim.get('support')
    if not isinstance(support, str):
        return '陈述 support 必须为参数 ID、素材 ID 或 generic'
    if support == 'generic':
        if specific_claim(claim['text']) or TOKEN.search(claim['text']) or find_unsourced_numbers(claim['text']):
            return '通用陈述含具体实体、数字或引用，必须提供出处'
    elif support in facts:
        if facts[support].get('status') not in {'verified', 'confirmed'} or support in conflicts:
            return '陈述引用未确认、已否决或冲突事实'
        if not quote_matches(facts[support]):
            return '陈述引用值与原文摘录不一致或缺少摘录'
        for sentence in clauses(claim['text']):
            tokens = TOKEN.findall(sentence)
            if tokens:
                if not all(t == support or (analogies or {}).get(t, {}).get('fact') == support for t in tokens):
                    return '陈述占位与所列 support 不一致'
                if not statement_matches(sentence, facts, analogies or {}):
                    return '参数引用不能支撑附带的用途、结构或错误参数名称'
            elif normalized(sentence) not in normalized(str(facts[support].get('value', '')) + str(facts[support].get('source', {}).get('quote', ''))):
                return '文字陈述无法与所引用事实原文对齐，需人工核对'
    elif support not in assets:
        return f'陈述引用的参数或素材不存在：{support}'
    else:
        asset = assets[support]
        evidence = [str(asset.get('title', ''))] + list(asset.get('tags', []))
        if not all(any(normalized(sentence) in normalized(text) for text in evidence) for sentence in clauses(claim['text'])):
            return '文字陈述无法与素材标题或标签对齐，需人工核对'
    return None


def check_accuracy(facts_data: dict, shotlist: dict, assets_data: dict, rig: dict,
                   add: Callable[..., None]) -> None:
    facts = {f['id']: f for f in facts_data.get('facts', []) if isinstance(f, dict) and 'id' in f}
    assets = {a['id']: a for a in assets_data.get('assets', []) if isinstance(a, dict) and 'id' in a}
    analogies = {a['id']: a for a in shotlist.get('analogies', []) if isinstance(a, dict) and 'id' in a}
    conflicts = fact_conflicts(facts_data.get('facts', []))
    containers = [dict(id=None, title=shotlist.get('title', ''))] + shotlist.get('shots', [])
    for shot in containers:
        if not isinstance(shot, dict):
            continue
        sid, params = shot.get('id'), shot.get('params') or {}
        texts = visible_texts(shot)
        refs = set(shot.get('fact_refs', [])) | set(params.get('facts', []))
        aids = set(shot.get('analogy_refs', []))
        if params.get('fact'):
            refs.add(params['fact'])
        if params.get('analogy'):
            aids.add(params['analogy'])
        for field, text in texts:
            if field != 'narration':
                for token in set(TOKEN.findall(text)):
                    if token.startswith('F_') and token not in facts:
                        add('UNKNOWN_FACT', 'block', f'引用了不存在的参数：{token}', '改用参数表中已有的可引用参数', sid)
                for fragment in find_unsourced_numbers(TOKEN.sub('', text)):
                    add('UNSOURCED_NUMBER', 'block', f'{field} 出现无出处的数字「{fragment}」', '改用已核验事实占位或删除', sid)
            refs.update(t for t in TOKEN.findall(text) if t.startswith('F_'))
            aids.update(t for t in TOKEN.findall(text) if t.startswith('A_'))
        if shot.get('kind') == 'motion':
            axis = rig.get('axes', {}).get(params.get('axis'), {})
            if axis.get('speed_fact'):
                refs.add(axis['speed_fact'])
        claims = shot.get('claims')
        if sid is not None:
            if claims is None or claims == []:
                add('CLAIMS_MISSING', 'info', '镜头尚未列出逐句陈述', '为每句台词添加 text 与 support；技能交付按警告处理', sid)
            elif not isinstance(claims, list):
                add('UNSUPPORTED_CLAIM', 'block', 'claims 必须为陈述数组', '按 schema 填写 claims', sid)
            else:
                for claim in claims:
                    error = claim_error(claim, facts, assets, conflicts, analogies)
                    if error:
                        add('UNSUPPORTED_CLAIM', 'block', error, '提供已核验文字事实或有效素材；删除无依据的具体陈述', sid)
                    if isinstance(claim, dict) and isinstance(claim.get('support'), str) and claim['support'] in facts:
                        refs.add(claim['support'])
                for sentence in clauses(shot.get('narration', '')):
                    if not any(isinstance(c, dict) and sentence in clauses(c.get('text', '')) for c in claims):
                        add('UNSUPPORTED_CLAIM', 'block', f'台词陈述未登记：{sentence}', '为每句台词登记 claims，不能只登记部分内容', sid)
        for aid in sorted(aids):
            a = analogies.get(aid)
            if not a:
                continue
            refs.add(a.get('fact'))
            try:
                fact = facts[a['fact']]
                expected = compute(aid, fact, a['ref'], a['axis'])
                item = REFS[a['ref']]
                ratio = float(fact['value']) * UNIT_SCALE[fact['unit']][1] / UNIT_SCALE[item['unit']][1] / item['size']
                valid = (math.isclose(float(a['ratio']), expected['ratio'], rel_tol=0, abs_tol=1e-9)
                         and wording_valid(a.get('text', ''), ratio, a['ref']))
                valid = valid and all(a[k] == expected[k] for k in ('ref_size', 'ref_size_m', 'ref_unit') if k in a)
            except (KeyError, TypeError, ValueError, OverflowError):
                valid = False
            if not valid:
                add('ANALOGY_ROUNDING', 'block', f'类比数值、比较词或参照尺寸不符合真实比值：{aid}', '重新运行 compute_analogy，不手写 ratio/text 或比较词', sid)
        for fid in sorted(refs, key=str):
            fact = facts.get(fid)
            if not fact:
                continue
            if not (fact.get('source') or {}).get('quote', '').strip():
                add('QUOTE_ABSENT', 'warn', f'引用事实缺少原文摘录：{fid}', '补充 source.quote 并核对原文', sid)
            elif not quote_matches(fact):
                add('QUOTE_MISMATCH', 'block', f'引用值或单位未在原文摘录中找到：{fid}', '参数抽取可能抄错，交人工核对原文；不要改写摘录迎合参数', sid)


TOPICS = {
    'F_rated_load': ('额定起重量', '起重量', '额定载荷', '起重能力'),
    'F_total_mass': ('整机自重', '整机质量', '自重'),
    'F_span': ('跨度',), 'F_girder_length': ('主梁总长', '主梁长度', '主梁长'),
    'F_overall_height': ('整机高度', '整机高'), 'F_lift_height': ('起升高度',),
    'F_hoist_speed': ('起升速度',), 'F_trolley_speed': ('小车运行速度', '小车速度'),
    'F_gantry_speed': ('大车运行速度', '大车速度'),
    'F_weld_tolerance': ('主梁腹板对接焊缝错边量', '焊缝错边量', '焊缝错边', '错边量', '错边公差'),
}


def statement_matches(sentence: str, facts: dict, analogies: dict) -> bool:
    """占位只证明数值，不能自动证明同句中夹带的用途、结构或错误参数名。"""
    residual = TOKEN.sub('', sentence)
    for token in TOKEN.findall(sentence):
        fid = token if token in facts else analogies.get(token, {}).get('fact')
        fact = facts.get(fid, {})
        names = [str(fact.get('name', ''))] + list(TOPICS.get(fid, ()))
        for name in sorted(names, key=len, reverse=True):
            if name:
                residual = residual.replace(name, '')
    for term in ('最高可达', '资料列示', '资料显示', '资料中的', '额定', '最大', '不大于', '不超过',
                 '该设备', '本设备', '这台设备', '本机', '它的', '为', '是', '达', '的', '和', '与', '可'):
        residual = residual.replace(term, '')
    return not re.sub(r'[\s：:（）()、/]+', '', residual)


def generic_nonfactual(sentence: str) -> bool:
    """保守识别非设备断言；开放域常识与宣传语不自动获得事实支撑。"""
    if (specific_claim(sentence) or TOKEN.search(sentence) or find_unsourced_numbers(sentence)
            or re.search(r'已经|已交|已批|配有|配备|具备|能够|实现|投产|制造|节省|降低|提高|提升|交付|防摇|智能|精确|建成|拥有|获得', sentence)):
        return False
    return bool(re.search(r'怎样|如何|为什么|[？?]$|帮助理解|先看|看看|看明白|看资料|核对出处|观察|可以暂停|查看资料|读懂资料', sentence))


def traceability(facts_data: dict, shotlist: dict, assets_data: dict, issues: list[dict]) -> dict:
    """独立遍历所有台词分句，不以模型自报 claims 的数量作为分母。"""
    facts = {f['id']: f for f in facts_data.get('facts', [])}
    assets = {a['id']: a for a in assets_data.get('assets', [])}
    analogies = {a['id']: a for a in shotlist.get('analogies', [])}
    conflicts = fact_conflicts(facts_data.get('facts', []))
    rows = []
    for shot in shotlist.get('shots', []):
        for sentence in clauses(shot.get('narration', '')):
            tokens = TOKEN.findall(sentence)
            numeric = bool(tokens or find_unsourced_numbers(sentence))
            evidence = []
            for claim in shot.get('claims', []) or []:
                if not isinstance(claim, dict) or sentence not in clauses(claim.get('text', '')) or claim_error(claim, facts, assets, conflicts, analogies):
                    continue
                support = claim['support']
                if support == 'generic':
                    # generic 是作者分类，不是外部证据。只给提问、阅读引导和明确类比计分；
                    # 无法确定的无出处陈述保留在分母，不能自报为 generic 后当事实通过。
                    if generic_nonfactual(sentence):
                        evidence.append(support)
                elif support in facts:
                    fact = facts[support]
                    if not quote_matches(fact):
                        continue
                    # 数字占位可直接回溯；文字内容保守要求能在原文或文字事实中找到。
                    if support in tokens or any(analogies.get(t, {}).get('fact') == support for t in tokens):
                        remainder = TOKEN.sub('', sentence)
                        if not specific_claim(remainder) and statement_matches(sentence, facts, analogies):
                            evidence.append(support)
                    elif normalized(sentence) in normalized(str(fact.get('value', '')) + str(fact.get('source', {}).get('quote', ''))):
                        evidence.append(support)
                elif support in assets:
                    asset = assets[support]
                    if normalized(sentence) in normalized(str(asset.get('title', '')) + ' '.join(asset.get('tags', []))):
                        evidence.append(support)
            good_tokens = all((t in facts and facts[t].get('status') in {'verified', 'confirmed'} and t not in conflicts and quote_matches(facts[t]))
                              or (t in analogies and analogies[t].get('fact') in evidence) for t in tokens)
            blocked = any(i.get('shot') in (None, shot['id']) and (i['severity'] == 'block' or i['code'] in
                          {'UNVERIFIED_FACT', 'REFERENCE_ASSET_CLAIM', 'ABSOLUTE_CLAIM', 'QUOTE_ABSENT', 'CHECK_ERROR'}) for i in issues)
            supported = bool(evidence) and good_tokens and not find_unsourced_numbers(TOKEN.sub('', sentence)) and not blocked
            rows.append({'shot': shot['id'], 'text': sentence, 'kind': '数字陈述' if numeric else '文字陈述',
                         'support': evidence, 'supported': supported})
    count = sum(r['supported'] for r in rows)
    return {'supported': count, 'total': len(rows), 'rate': count / len(rows) if rows else None,
            'claims': rows, 'method': '逐分句保守规则审计；缺失、无法对齐原文或无支撑的陈述均不计通过，非语义真实性证明。'}
