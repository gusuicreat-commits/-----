"""确定性的单故障注入；所有样本仅用于离线规则测量。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILL / 'scripts'))
from compute_analogy import compute
from skill_io import read_json, write_json

CATEGORIES = {
    'bare_number': ('裸数字', {'UNSOURCED_NUMBER'}),
    'changed_value': ('数值改一位', {'QUOTE_MISMATCH'}),
    'wrong_unit': ('替换单位', {'QUOTE_MISMATCH'}),
    'invalid_fact': ('未确认、驳回或不存在参数', {'UNVERIFIED_FACT', 'REJECTED_FACT', 'UNKNOWN_FACT'}),
    'conflicting_fact': ('冲突参数', {'FACT_CONFLICT'}),
    'reference_claim': ('参考实拍冒认本机', {'REFERENCE_ASSET_CLAIM'}),
    'ai_equipment': ('创意画面出现设备', {'AI_SHOWS_EQUIPMENT'}),
    'superlative': ('无证据最高级', {'EXAGGERATION'}),
    'absolute': ('绝对承诺', {'ABSOLUTE_CLAIM'}),
    'analogy_word': ('类比比较词错误', {'ANALOGY_ROUNDING'}),
    'analogy_parameter': ('类比参数错误', {'ANALOGY_ROUNDING'}),
    'missing_asset': ('不存在素材', {'ASSET_MISSING'}),
    'missing_axis': ('不存在运动轴', {'MOTION_AXIS_UNAVAILABLE'}),
    'overspeed': ('超速但标成真实速度', {'MOTION_SPEEDUP_MISMATCH'}),
    'unsupported_claim': ('具体陈述无支撑', {'UNSUPPORTED_CLAIM'}),
}


def shot(sid: str, narration: str, kind: str = 'title', params: dict | None = None,
         claims: list[dict] | None = None) -> dict:
    return {'id': sid, 'kind': kind, 'source': 'model', 'duration_s': 9,
            'narration': narration, 'fact_refs': [], 'analogy_refs': [], 'asset_refs': [],
            'params': params if params is not None else {'title': '', 'subtitle': ''}, 'review': {'status': 'pending', 'note': ''},
            'claims': claims if claims is not None else [{'text': narration, 'support': 'generic'}]}


def build_baselines() -> list[dict]:
    """四套资料，各自起草合格分镜；运动行程是测试专用合成配置。"""
    result = []
    for name, hook in [('standard', '大块头怎样稳稳托起重物？'), ('bridge_crane', '车间上方的搬运怎样完成？'),
                       ('english_facts', '读懂资料里的起重量。'), ('reference_only', '参考实拍帮助理解吊装场景。')]:
        fixture = SKILL / 'evals/fixtures' / name
        facts = read_json(fixture / 'facts.json')
        data = {f['id']: f for f in facts['facts']}
        analogy = compute('A_load', data['F_rated_load'], 'car', 'mass')
        shots = [shot('S1', hook),
                 shot('S2', '额定起重量{{F_rated_load}}。跨度{{F_span}}。', 'data_card',
                      {'facts': ['F_rated_load', 'F_span']},
                      [{'text': '额定起重量{{F_rated_load}}', 'support': 'F_rated_load'},
                       {'text': '跨度{{F_span}}', 'support': 'F_span'}]),
                 shot('S3', '{{A_load}}。', 'analogy', {'analogy': 'A_load'},
                      [{'text': '{{A_load}}', 'support': 'F_rated_load'}]),
                 shot('S4', '起升速度{{F_hoist_speed}}。', 'motion', {'axis': 'hoist', 'from_m': 2, 'to_m': 2.5},
                      [{'text': '起升速度{{F_hoist_speed}}', 'support': 'F_hoist_speed'}]),
                 shot('S5', '把资料看明白。', 'outro')]
        shots[1]['fact_refs'] = ['F_rated_load', 'F_span']
        shots[2]['analogy_refs'] = ['A_load']
        shots[3]['fact_refs'] = ['F_hoist_speed']
        # 素材内容、文字事实都明确标为测试输入，不宣称真实验收。
        facts['facts'].append({'id': 'F_structure', 'name': '结构形式', 'type': 'qualitative',
                               'value': '采用箱形主梁', 'unit': '', 'status': 'verified',
                               'source': {'doc': '合成测试说明.txt', 'page': 1, 'quote': '结构形式：采用箱形主梁'}})
        result.append({'name': name, 'facts': facts,
                       'assets': {'assets': [{'id': 'IMG_test', 'kind': 'image', 'file': 'assets/test.jpg',
                                             'provenance': 'reference', 'title': '船体分段吊装', 'tags': [], 'credit': '合成测试素材'}]},
                       'project': {'model': {'kind': 'parametric', 'glb': 'model/crane.glb'}},
                       'rig': {'axes': {'hoist': {'node': 'hoist_hook', 'axis': 'y', 'range_m': [2, 40],
                                                  'speed_fact': 'F_hoist_speed'}}},
                       'shotlist': {'version': 1, 'title': '资料约束的设备解说', 'fps': 30, 'width': 1920, 'height': 1080,
                                    'shots': shots, 'analogies': [analogy]}})
    return result


def set_line(shot: dict, text: str, support: str = 'generic') -> None:
    shot['narration'] = text
    shot['claims'] = [{'text': text, 'support': support}]


def mutations(baselines: list[dict]) -> list[dict]:
    result = []
    for category, (label, expected) in CATEGORIES.items():
        for index in range(12):
            item = deepcopy(baselines[index % len(baselines)])
            variant = index // len(baselines)
            shots = item['shotlist']['shots']
            facts = {f['id']: f for f in item['facts']['facts']}
            analogy = item['shotlist']['analogies'][0]
            if category == 'bare_number':
                set_line(shots[0], f'跨度{31 + index}米。')
            elif category == 'changed_value':
                fact = facts[['F_rated_load', 'F_span', 'F_hoist_speed'][variant]]
                digits = str(fact['value'])
                fact['value'] = float(digits) + (index + 1) * 10 ** (-variant)
            elif category == 'wrong_unit':
                facts[['F_rated_load', 'F_span', 'F_hoist_speed'][variant]]['unit'] = ['s', 'A', 'K', 'V'][index % 4]
            elif category == 'invalid_fact':
                target = ['F_rated_load', 'F_span', 'F_hoist_speed', 'F_structure'][index // 3]
                if index % 3 < 2:
                    facts[target]['status'] = ['needs_review', 'rejected'][index % 3]
                else:
                    item['facts']['facts'].remove(facts[target])
                if target == 'F_structure':
                    set_line(shots[0], '{{F_structure}}', target)
            elif category == 'conflicting_fact':
                conflicting = deepcopy(facts[['F_rated_load', 'F_span', 'F_hoist_speed'][variant]])
                conflicting['id'] += '_conflict'
                conflicting['value'] += index + 1
                item['facts']['facts'].append(conflicting)
            elif category == 'reference_claim':
                shots[0].update(kind='real_media', source='real', asset_refs=['IMG_test'], params={'asset': 'IMG_test'})
                set_line(shots[0], ['这台设备正在作业。', '本机正在作业。', '我们的设备正在作业。', '这台门机正在吊装。', '本机正在吊装。', '我们的门机正在吊装。', '这台吊车正在移动。', '本机正在移动。', '我们的吊车正在移动。', '这台设备正在定位。', '本机正在定位。', '我们的设备正在定位。'][index], 'IMG_test')
            elif category == 'ai_equipment':
                shots[0].update(kind='ai_broll', source='ai', params={'recipe': 'sunrise_port', 'prompt': ['起重机全景', '主梁特写', '吊钩移动', '门机仰拍', '龙门吊远景', '吊车环绕', '支腿近景', '小车运行', 'crane panorama', 'gantry closeup', 'hook detail', 'girder structure'][index]})
            elif category == 'superlative':
                set_line(shots[0], [t + '的设备。' for t in ['世界第一', '国内最大', '全球领先', '国际领先', '最先进', '顶级', '行业第一', '世界首位', '全球第一', '全国第一', '首创', '独一无二']][index])
            elif category == 'absolute':
                set_line(shots[0], [t + '。' for t in ['绝对安全', '零误差', '永不出错', '零偏差', '绝无风险', '百分之百安全', '完美', '毫无偏差', '绝不出错', '万无一失', '100%安全', '永不故障']][index])
            elif category == 'analogy_word':
                n = analogy['ratio']
                analogy['text'] = [('超过', n + index + 1), ('几乎', n - index - 1), ('接近', n * (1.2 + index / 100))][variant][0] + str([n + index + 1, n - index - 1, n * (1.2 + index / 100)][variant]) + '辆小轿车的重量'
            elif category == 'analogy_parameter':
                if variant == 0:
                    analogy['ratio'] += index + 2
                elif variant == 1:
                    analogy['ref'] = 'absent_' + str(index)
                else:
                    analogy['ref_size'] = 2 + index
            elif category == 'missing_asset':
                shots[0].update(kind='real_media', source='real', asset_refs=[f'IMG_absent_{index}'], params={'asset': f'IMG_absent_{index}'})
            elif category == 'missing_axis':
                shots[3]['params']['axis'] = f'missing_axis_{index}'
            elif category == 'overspeed':
                shots[3]['params'].update(to_m=20 + index, speedup=1)
            elif category == 'unsupported_claim':
                set_line(shots[0], f'本机型号为 QD{450 + index}。')
            item.update(id=f'{category}-{index:02d}', category=category, label=label, expected=sorted(expected),
                        baseline=baselines[index % len(baselines)]['name'])
            result.append(item)
    return result


# 人工编写，刻意覆盖量词、序数、比喻、合法上限及有依据的文字陈述。
HARD_VALID = [
    ('一根头发丝也能帮助理解尺度。', 'generic'), ('第一步先看资料。', 'generic'),
    ('唯一要做的就是核对出处。', 'generic'), ('最高可达{{F_rated_load}}。', 'F_rated_load'),
    ('一台设备怎样搬运？', 'generic'), ('两个部件相互配合。', 'generic'),
    ('一起看看运动过程。', 'generic'), ('其中之一是吊钩。', 'generic'),
    ('一直沿着轨道移动。', 'generic'), ('统一查看资料。', 'generic'),
    ('万一看不清可以暂停。', 'generic'), ('一种方式是先看整体。', 'generic'),
    ('一条线连接上下。', 'generic'), ('一块板形成轮廓。', 'generic'),
    ('一边观察一边理解。', 'generic'), ('一座桥帮助理解形状。', 'generic'),
    ('一次移动完成定位。', 'generic'), ('两个视角帮助理解。', 'generic'),
    ('采用箱形主梁。', 'F_structure'), ('{{F_structure}}。', 'F_structure'),
]


def positives(baselines: list[dict]) -> list[dict]:
    result = []
    for index, (text, support) in enumerate(HARD_VALID):
        item = deepcopy(baselines[index % len(baselines)])
        item['id'] = f'correct-{index:02d}'
        set_line(item['shotlist']['shots'][0], text, support)
        result.append(item)
    return result


def main() -> int:
    bases = build_baselines()
    destination = Path(__file__).resolve().parent / 'corpus.json'
    write_json(destination, {'baselines': bases, 'mutations': mutations(bases), 'hard_valid': positives(bases),
                            'note': '合成故障注入样本，不代表设备真实参数或真实模型生成效果。'})
    print('已生成四份合格分镜、180 份故障样本和20份易误报正确样本。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
