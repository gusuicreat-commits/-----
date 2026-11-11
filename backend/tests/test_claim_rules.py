"""新增规则的真实输入边界，以及独立脚本与后端一致性。"""
from copy import deepcopy
import pytest
from app import storage
from app.agent import planner
from test_skill_parity import assert_parity
from test_validator import scenario, shot, write_shot


def fact(fid='F_height', name='整机高度', value=51, unit='m', **extra):
    return {'id': fid, 'name': name, 'value': value, 'unit': unit, 'status': 'verified',
            'source': {'doc': '技术参数.pdf', 'page': 2, 'quote': f'{name} {value} {unit}'}, **extra}


def codes(pid: str) -> set[str]:
    return {i['code'] for i in assert_parity(pid)['issues']}


@pytest.mark.parametrize('text,blocked', [
    ('国内最大的门机', True), ('世界第一，全球领先', True), ('行业之最，最先进', True),
    ('最重、最快、最高', True), ('國內首臺，頂級', True), ('全 球 领 先', True),
    ('额定起重量{{F_length}}', False), ('沿着主梁看过去', False),
])
@pytest.mark.parametrize('field', ['narration', 'caption', 'title', 'subtitle', 'global_title'])
def test_exaggeration_fields_and_variants(scenario, text, blocked, field):
    item = shot(narration='观察结构。', fact_refs=[])
    if field == 'narration':
        item['narration'] = text
    elif field != 'global_title':
        item['params'][field] = text
    write_shot(scenario, item)
    if field == 'global_title':
        data = storage.read_json(scenario, 'shotlist.json'); data['title'] = text
        storage.write_json(scenario, 'shotlist.json', data)
    assert ('EXAGGERATION' in codes(scenario)) is blocked


@pytest.mark.parametrize('text,status,claim_type,quote,blocked', [
    ('国内首台，认证序位{{F_rank}}。', 'verified', 'ranking', '国内首台，认证序位1', False),
    ('{{F_rank}}为认证序位，国内首台。', 'verified', 'ranking', '国内首台，认证序位1', False),
    ('国内首台。认证序位{{F_rank}}。', 'verified', 'ranking', '国内首台，认证序位1', True),
    ('国内首台。', 'verified', 'ranking', '国内首台，认证序位1', True),
    ('国内首台，认证序位{{F_rank}}。', 'confirmed', 'ranking', '国内首台，认证序位1', True),
    ('国内首台，认证序位{{F_rank}}。', 'verified', None, '国内首台，认证序位1', True),
    ('国内首台，认证序位{{F_rank}}。', 'verified', 'ranking', '起重量 1 t', True),
    ('全球最大，认证序位{{F_rank}}。', 'verified', 'ranking', '国内最大，认证序位1', True),
])
def test_ranking_requires_same_sentence_verified_evidence(scenario, text, status, claim_type, quote, blocked):
    ranking = fact('F_rank', '认证序位', 1, '', claim_type=claim_type, status=status)
    ranking['source']['quote'] = quote
    storage.write_json(scenario, 'facts.json', {'facts': [ranking]})
    write_shot(scenario, shot(narration=text, fact_refs=['F_rank']))
    assert ('EXAGGERATION' in codes(scenario)) is blocked


def test_other_field_cannot_authorize_title(scenario):
    ranking = fact('F_rank', '认证序位', 1, '', claim_type='ranking')
    ranking['source']['quote'] = '国内首台，认证序位1'
    storage.write_json(scenario, 'facts.json', {'facts': [ranking]})
    write_shot(scenario, shot(narration='认证序位{{F_rank}}。', fact_refs=['F_rank'], params={'title': '国内首台'}))
    assert 'EXAGGERATION' in codes(scenario)


@pytest.mark.parametrize('text,warned', [
    ('零误差', True), ('绝对安全，永不出错', True), ('完美，毫无偏差', True),
    ('零誤差，絕對安全', True), ('错边公差{{F_length}}', False), ('请核对适用条件', False),
])
def test_absolute_promises(scenario, text, warned):
    write_shot(scenario, shot(narration=text))
    assert ('ABSOLUTE_CLAIM' in codes(scenario)) is warned


@pytest.mark.parametrize('mode,blocked', [('name', True), ('id', True), ('key', True),
    ('equal', False), ('equivalent_unit', False), ('unverified', False), ('unused', False)])
def test_conflicts_preserve_rows_and_do_not_choose(scenario, mode, blocked):
    a, b = fact(), fact('F_height_alt', value=53)
    if mode == 'id':
        b.update(id=a['id'], name='设备总高')
    if mode == 'key':
        a['key'] = b['key'] = 'overall_height'; b['name'] = '设备总高'
    if mode == 'equal': b['value'] = 51.0
    if mode == 'equivalent_unit': b.update(value=51000, unit='mm')
    if mode == 'unverified': b['status'] = 'needs_review'
    facts = {'facts': [a, b]}
    storage.write_json(scenario, 'facts.json', facts)
    write_shot(scenario, shot(narration='观察主梁。' if mode == 'unused' else '{{F_height}}', fact_refs=[]))
    assert ('FACT_CONFLICT' in codes(scenario)) is blocked
    assert storage.read_json(scenario, 'facts.json') == facts


@pytest.mark.parametrize('via', ['second', 'caption', 'data_card', 'analogy'])
def test_conflict_indirect_references(scenario, via):
    storage.write_json(scenario, 'facts.json', {'facts': [fact(), fact('F_height_alt', value=53)]})
    item = shot(narration='观察结构。', fact_refs=[])
    analogies = []
    if via == 'second': item['narration'] = '{{F_height_alt}}'
    if via == 'caption': item['params']['caption'] = '{{F_height_alt}}'
    if via == 'data_card': item['params']['facts'] = ['F_height_alt']
    if via == 'analogy':
        item['narration'] = '{{A_height}}'; analogies = [{'id': 'A_height', 'fact': 'F_height_alt', 'text': '观察高度'}]
    write_shot(scenario, item, analogies)
    assert 'FACT_CONFLICT' in codes(scenario)


@pytest.mark.parametrize('name,unit,warned', [('额定起重量', 'm', True), ('跨度', 't', True),
    ('起升速度', 'kg', True), ('Rated lifting capacity', 'm', True), ('Span', 't', True),
    ('额定起重量', 't', False), ('跨度', 'm', False), ('起升速度', 'm/min', False), ('焊缝精度', 'mm', False)])
def test_unit_dimensions(scenario, name, unit, warned):
    storage.write_json(scenario, 'facts.json', {'facts': [fact('F_parameter', name, 3, unit)]})
    write_shot(scenario, shot(narration='核对参数。', fact_refs=[]))
    assert ('UNIT_SUSPECT' in codes(scenario)) is warned


def test_planner_keeps_ranking_and_conflict_evidence(project):
    data = [fact(), fact('F_height_alt', value=53), fact('F_rank', '认证序位', 1, '', claim_type='ranking')]
    storage.write_json(project['id'], 'facts.json', {'facts': data})
    context = planner._context(project['id'])
    assert len(context['facts']) == 3
    assert context['facts'][-1]['claim_type'] == 'ranking'
    assert all(f['status'] == 'verified' and f['source']['page'] == 2 for f in context['facts'])
