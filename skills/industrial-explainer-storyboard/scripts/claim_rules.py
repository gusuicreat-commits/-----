"""宣称与参数检查；词表和量纲表统一由参考资料提供。"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata
from typing import Callable

RULES_PATH = Path(__file__).resolve().parents[1] / 'references/claim-rules.json'
RULES = json.loads(RULES_PATH.read_text(encoding='utf-8'))
TOKEN = re.compile(r'\{\{([FA]_[A-Za-z0-9_]+)\}\}')


def normalized(text: str) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).casefold()


def visible_texts(shot: dict) -> list[tuple[str, str]]:
    result = [(key, shot[key]) for key in ('narration', 'caption', 'title', 'subtitle') if isinstance(shot.get(key), str)]
    params = shot.get('params') or {}
    result.extend((f'params.{key}', params[key]) for key in ('caption', 'title', 'subtitle') if isinstance(params.get(key), str))
    return result


def fact_conflicts(rows: list[dict]) -> set[str]:
    """保留原始行，不能先按 id 去重；等值单位换算不算冲突。"""
    groups: dict[tuple[str, str], list[dict]] = {}
    for fact in rows:
        if not isinstance(fact, dict) or fact.get('status') not in {'verified', 'confirmed'}:
            continue
        for key in ('id', 'key', 'name'):
            value = fact.get(key)
            if isinstance(value, str) and value.strip():
                groups.setdefault((key, normalized(value)), []).append(fact)
    conflicts: set[str] = set()
    for group in groups.values():
        values = set()
        for fact in group:
            unit = str(fact.get('unit', '')).strip()
            dimension, scale = RULES['unit_scales'].get(unit, (unit, 1))
            value = fact.get('value')
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = round(float(value) * scale, 9)
            values.add((dimension, str(value)))
        if len(values) > 1:
            conflicts.update(f['id'] for f in group)
    return conflicts


def check_claims(facts_data: dict, shotlist: dict, add: Callable[..., None]) -> None:
    rows = facts_data.get('facts', [])
    facts = {f['id']: f for f in rows if isinstance(f, dict) and 'id' in f}
    conflicts = fact_conflicts(rows)
    analogies = {a['id']: a for a in shotlist.get('analogies', []) if isinstance(a, dict) and 'id' in a}
    containers = [(None, {'title': shotlist.get('title', '')})]
    containers.extend((s.get('id', f'S{i}'), s) for i, s in enumerate(shotlist.get('shots', []), 1) if isinstance(s, dict))
    for sid, shot in containers:
        texts = visible_texts(shot)
        params = shot.get('params') or {}
        refs = list(shot.get('fact_refs', [])) + list(params.get('facts', []))
        if params.get('fact'):
            refs.append(params['fact'])
        aids = list(shot.get('analogy_refs', []))
        if params.get('analogy'):
            aids.append(params['analogy'])
        for _, text in texts:
            tokens = TOKEN.findall(text)
            refs.extend(t for t in tokens if t.startswith('F_'))
            aids.extend(t for t in tokens if t.startswith('A_'))
        refs.extend(analogies[a]['fact'] for a in aids if a in analogies)
        for fid in dict.fromkeys(refs):
            if fid in conflicts:
                add('FACT_CONFLICT', 'block', f'已核验参数存在冲突：{fid}',
                    '交人工核对各文档页并确认采用哪条；不得自行选择或修改事实状态', sid)
        for field, text in texts:
            # 先分句再展开，保证别句、别字段或仅 fact_refs 的证据不能放行。
            for sentence in re.split(r'[。！？!?；;\n]+', text):
                tokens = TOKEN.findall(sentence)
                ranking = [facts[t] for t in tokens if t in facts and t not in conflicts
                           and facts[t].get('claim_type') == 'ranking' and facts[t].get('status') == 'verified'
                           and all(facts[t].get('source', {}).get(k) for k in ('doc', 'page', 'quote'))]
                expanded = TOKEN.sub(lambda m: str(facts[m[1]].get('value', '')) if m[1] in facts
                                    else str(analogies.get(m[1], {}).get('text', m[0])), sentence)
                ranking_text = normalized(expanded)
                ranking_text = re.sub(r'唯一(?:要做的|需要做的|的步骤)', '', ranking_text)
                if (re.search(r'最高可达\s*\{\{F_[A-Za-z0-9_]+\}\}', sentence)
                        and not re.search(r'(国内|全国|全球|世界|行业).*最高可达', sentence) and any(
                    facts[t].get('status') in {'verified', 'confirmed'} and facts[t].get('source', {}).get('quote')
                    for t in tokens if t in facts)):
                    ranking_text = ranking_text.replace('最高可达', '')
                for term in dict.fromkeys(normalized(t) for t in RULES['exaggeration']):
                    claims = re.findall(r'(?:国内|全国|全球|世界|国际|行业|國內|全國|國際|行業)?' + re.escape(term), ranking_text)
                    if claims and not all(any(claim in normalized(f['source']['quote']) for f in ranking) for claim in claims):
                        add('EXAGGERATION', 'block', f'{field} 出现无同句排名证据的宣称「{term}」',
                            '例如将「国内最大」改为「起重量 {{F_rated_load}}」；保留适用范围，或同句引用 verified 的 ranking 事实', sid)
                for term in RULES['absolute']:
                    if normalized(term) in normalized(expanded):
                        add('ABSOLUTE_CLAIM', 'warn', f'{field} 出现绝对承诺「{term}」',
                            '删除绝对承诺，改用已核验的精度参数和适用条件，例如「错边公差 {{F_weld_tolerance}}」', sid)
    for fact in rows:
        if not isinstance(fact, dict) or fact.get('type') == 'qualitative':
            continue
        name = str(fact.get('name', '')).casefold()
        for rule in RULES['dimensions']:
            if fact.get('id') in rule['ids'] or any(word in name for word in rule['names']):
                if str(fact.get('unit', '')).strip() not in rule['units']:
                    add('UNIT_SUSPECT', 'warn', f'参数单位与名称量纲不符：{fact.get("id")}（{fact.get("name")} / {fact.get("unit")}）',
                        '核对原文单位后交人工修正，不能只改单位而保留数值；可用单位：' + '、'.join(rule['units']), None)
                break
