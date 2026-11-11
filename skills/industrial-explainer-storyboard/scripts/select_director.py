#!/usr/bin/env python3
"""Evidence-gated recipe selection; standard library only, also loaded by the app."""
from copy import deepcopy
import argparse
import json
import math
from pathlib import Path

RECIPES = Path(__file__).resolve().parents[1] / 'references/director-recipes.json'


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def confirmed_facts(facts):
    eligible = [f for f in facts if f.get('status') in {'confirmed', 'verified'}]
    conflicts = set()
    for i, fact in enumerate(eligible):
        for other in eligible[i + 1:]:
            same = fact.get('id') == other.get('id') or (fact.get('key') and fact.get('key') == other.get('key')) or (fact.get('name') and fact.get('name') == other.get('name'))
            if same and (fact.get('value'), fact.get('unit')) != (other.get('value'), other.get('unit')):
                conflicts.update((fact.get('id'), other.get('id')))
    return [f for f in eligible if f.get('id') not in conflicts and all(f.get('source', {}).get(k) not in (None, '') for k in ('doc', 'page', 'quote'))]



def scale_axis(fact):
    """Match the actual analogy geometry: girder X length or crane Y height only."""
    labels = [str(fact.get(k, '')).strip().lower() for k in ('id', 'key', 'name')]
    # An apparently canonical ID cannot override a contradictory name/key.
    unsupported = ('span', 'lift_height', 'hoist', 'boom', 'arm_', 'arm length',
                   'girder_height', 'girder height', 'leg_', 'leg length', 'trolley', 'rail',
                   'thickness', 'tolerance', 'mass', 'speed', 'load',
                   '跨度', '起升', '吊臂', '臂长', '支腿', '小车', '轨道', '副梁', '主梁高度', '主梁高',
                   '厚', '精度', '焊缝', '错边', '速度', '重量', '载荷', '额定起重')
    if any(word in label for label in labels for word in unsupported):
        return None
    length_names = {'girder_length', 'f_girder_length', 'girder length', 'girder total length',
                    '主梁总长', '主梁总长度', '主梁长度'}
    height_names = {'overall_height', 'f_overall_height', 'overall height', 'crane overall height',
                    '整机高度', '整机总高度', '整机总高'}
    axes = set()
    for label in labels:
        if label in length_names:
            axes.add('length')
        if label in height_names:
            axes.add('height')
    return next(iter(axes)) if len(axes) == 1 else None


def bindings_for(kind, facts, model, duration):
    nodes = set((model or {}).get('nodes', []))
    if not model:
        return None, '缺模型及节点，不能安排设备模型画面'
    if kind == 'scale':
        if 'girder' not in nodes:
            return None, '缺 girder 模型节点'
        for f in facts:
            if f.get('type') == 'qualitative' or not positive(f.get('value')) or f.get('unit') not in {'m', 'mm'}:
                continue
            axis = scale_axis(f)
            if axis is None:
                continue
            ref = 'building_floor' if axis == 'height' else 'football_field'
            return {'fact_id': f['id'], 'axis': axis, 'ref': ref, 'analogy_id': f"A_{f['id'].removeprefix('F_')}_{ref}"}, None
        return None, '当前尺度镜头只支持主梁总长(girder_length)或整机高度(overall_height)；缺对应确认事实，或名称/key/ID语义冲突；跨度、起升高度与部件尺寸不适用'
    if kind == 'motion':
        by_id = {f['id']: f for f in facts}
        for axis, rig in (model.get('rig') or {}).get('axes', {}).items():
            if axis not in {'trolley', 'hoist', 'gantry'} or rig.get('node') not in nodes:
                continue
            span = rig.get('range_m', [])
            speed = by_id.get(rig.get('speed_fact'), {})
            if len(span) != 2 or not all(isinstance(x, (float, int)) and not isinstance(x, bool) and math.isfinite(x) for x in span) or span[0] >= span[1]:
                continue
            if speed.get('unit') != 'm/min' or not positive(speed.get('value')):
                continue
            # Use a central segment playable at physical speed in the allocated shot.
            distance = min((span[1] - span[0]) * .6, speed['value'] / 60 * duration * 8 / 15)
            middle = sum(span) / 2
            return {'axis': axis, 'node': rig['node'], 'from_m': middle - distance / 2, 'to_m': middle + distance / 2, 'fact_id': speed['id']}, None
        return None, '缺匹配模型节点的有效 rig 轴/行程或确认速度(m/min)'
    if not {'girder', 'leg_left', 'leg_right'} <= nodes:
        return None, '缺 girder/leg_left/leg_right 模型节点'
    for f in facts:
        text = str(f.get('value', '')).lower()
        if f.get('type') == 'qualitative' and ('主梁' in text or 'girder' in text) and ('支腿' in text or 'leg' in text):
            return {'fact_id': f['id']}, None
    return None, '缺明确说明主梁与支腿组成的确认 qualitative 事实（不能从模型推断）'


def select_recipe(context, requested='auto', target_s=45):
    if requested not in {'auto', 'scale', 'motion', 'structure'}:
        raise ValueError('director_recipe 必须是 auto/scale/motion/structure')
    if not positive(target_s):
        raise ValueError('target_s 必须是有限正数')
    book = json.loads(RECIPES.read_text())
    facts = confirmed_facts(context.get('facts', []))
    brief = context.get('brief', '').lower()
    order = list(book['recipes'])
    if requested != 'auto':
        order = [requested]
    else:
        scores = {key: sum(w in brief for w in book['recipes'][key]['intent_words']) for key in order}
        order.sort(key=lambda key: -scores[key])
        # A stated subject is a requirement, not permission to silently change the topic.
        if scores[order[0]]:
            order = [order[0]]
    missing = {}
    for key in order:
        bindings, reason = bindings_for(key, facts, context.get('model'), target_s)
        if reason:
            missing[key] = reason
            continue
        recipe = deepcopy(book['recipes'][key])
        shots = recipe['sequence']
        consumed = 0
        for index, shot in enumerate(shots):
            shot['duration_s'] = round(target_s * shot.pop('weight') / 15, 3) if index < len(shots) - 1 else round(target_s - consumed, 3)
            consumed += shot['duration_s']
            shot['params'] = {k: [bindings.get(x[1:], x) if isinstance(x, str) and x.startswith('$') else x for x in v] if isinstance(v, list) else bindings.get(v[1:], v) if isinstance(v, str) and v.startswith('$') else v for k, v in shot['params'].items()}
            shot['fact_refs'] = [bindings['fact_id']]
            shot['analogy_requests'] = [{'fact': bindings['fact_id'], 'ref': bindings['ref'], 'axis': bindings['axis']}] if shot['kind'] == 'analogy' else []
        return {'status': 'selected', 'recipe': key, 'version': book['version'], 'target_s': target_s,
                'shot_budget': [3, 4] if target_s <= 20 else [3, 9],
                'question': recipe['question'], 'sequence': shots,
                'forbidden': recipe['forbidden'], 'observe_and_rework': recipe['observe_and_rework'],
                'manual_review': ['需人工观看成片检查可读性、比例和遮挡；选择器不执行审美返工', '输入资料与模型/rig 未经本选择器重新核验'],
                'unavailable': missing}
    return {'status': 'needs_evidence', 'recipe': requested, 'target_s': target_s, 'sequence': [],
            'unavailable': missing, 'manual_review': ['补齐所需证据后再规划；不能以无证据镜头代替必讲内容']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', required=True, help='JSON with brief, facts array and model:{nodes,rig}')
    parser.add_argument('--recipe', default='auto')
    parser.add_argument('--target-s', type=float, default=45)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = select_recipe(json.loads(Path(args.context).read_text()), args.recipe, args.target_s)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    raise SystemExit(0 if result['status'] == 'selected' else 1)
