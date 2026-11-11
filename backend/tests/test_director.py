"""Behavior checks for the shared skill entrypoint and application integration."""
from copy import deepcopy
import json

from fastapi.testclient import TestClient
import pytest

from app import llm, main, storage
from app.agent import planner
from app.agent.director import select_recipe
from test_planner import raw_shot, setup_sample


def fact(fid='F_length', value=104, unit='m', **extra):
    return {'id': fid, 'name': '主梁长度', 'value': value, 'unit': unit, 'status': 'confirmed',
            'source': {'doc': '参数表', 'page': 2, 'quote': '输入事实'}, **extra}


def context():
    return {'brief': '究竟有多大', 'facts': [fact()],
            'model': {'nodes': ['girder', 'leg_left', 'leg_right', 'trolley'], 'rig': {'axes': {}}}}


def test_scale_selects_one_recipe_and_real_parameter():
    result = select_recipe(context(), 'auto', 15)
    assert result['recipe'] == 'scale'
    assert [s['kind'] for s in result['sequence']] == ['model_orbit', 'analogy', 'data_card']
    assert sum(s['duration_s'] for s in result['sequence']) == 15
    assert result['sequence'][1]['analogy_requests'] == [{'fact': 'F_length', 'ref': 'football_field', 'axis': 'length'}]
    assert all('ratio' not in shot['params'] for shot in result['sequence'])


@pytest.mark.parametrize('change', ['unconfirmed', 'missing_source', 'conflict', 'missing_nodes', 'wrong_dimension'])
def test_scale_refuses_insufficient_evidence(change):
    ctx = context()
    if change == 'unconfirmed':
        ctx['facts'][0]['status'] = 'needs_review'
    elif change == 'missing_source':
        ctx['facts'][0].pop('source')
    elif change == 'conflict':
        ctx['facts'].append(fact('F_other', 108))
    elif change == 'missing_nodes':
        ctx['model']['nodes'] = []
    else:
        ctx['facts'][0]['unit'] = 't'
    result = select_recipe(ctx, 'scale', 15)
    assert result['status'] == 'needs_evidence' and result['sequence'] == []


def test_motion_requires_rig_node_and_verified_speed_and_stays_in_range():
    ctx = context()
    ctx['brief'] = '想看小车怎么运动'
    ctx['facts'].append(fact('F_speed', 30, 'm/min', name='小车速度'))
    assert select_recipe(ctx, 'motion', 15)['status'] == 'needs_evidence'
    ctx['model']['rig']['axes']['trolley'] = {'node': 'trolley', 'range_m': [-10, 10], 'speed_fact': 'F_speed'}
    result = select_recipe(ctx, 'auto', 15)
    assert result['recipe'] == 'motion'
    motion = result['sequence'][1]
    assert -10 <= motion['params']['from_m'] < motion['params']['to_m'] <= 10
    assert motion['params']['to_m'] - motion['params']['from_m'] <= 30 / 60 * motion['duration_s']
    ctx['model']['nodes'].remove('trolley')
    assert select_recipe(ctx, 'motion', 15)['status'] == 'needs_evidence'
    # A motion subject in auto mode remains a requirement even if scale evidence exists.
    assert select_recipe(ctx, 'auto', 15)['status'] == 'needs_evidence'


def test_structure_needs_text_not_just_geometry():
    ctx = context()
    assert select_recipe(ctx, 'structure', 15)['status'] == 'needs_evidence'
    ctx['facts'].append(fact('F_structure', '由主梁与支腿组成', '', type='qualitative', name='结构组成'))
    selected = select_recipe(ctx, 'structure', 15)
    assert selected['recipe'] == 'structure'
    parts = selected['sequence'][1]
    assert set(parts['params']['parts']) <= set(ctx['model']['nodes'])
    assert parts['fact_refs'] == ['F_structure']


def test_application_uses_selected_recipe_and_project_duration(project, monkeypatch):
    pid = setup_sample(project)
    saved = storage.read_json(pid, 'project.json')
    storage.write_json(pid, 'project.json', {**saved, 'director_recipe': 'scale', 'target_s': 15})
    seen = []
    def complete(task, system, user, schema, **kwargs):
        seen.append(json.loads(user)['director'])
        assert '3–4' in system and '6–9' not in system and '2–4' not in system
        assert '台词里禁止直接写任何数字' in system
        return {'title': '单一问题', 'shots': [raw_shot(s['kind'], duration_s=s['duration_s'], params=s['params'], fact_refs=s['fact_refs'], analogy_requests=s['analogy_requests']) for s in seen[-1]['sequence']]}
    monkeypatch.setattr(llm, 'complete_json', complete)
    result = planner.plan(pid, 'r1')
    assert len(result['shots']) == 3 and seen[0]['recipe'] == 'scale'
    assert len(result['analogies']) == 1 and result['analogies'][0]['ratio'] > 0
    assert seen[0] == select_recipe(planner._context(pid, 15), 'scale', 15)


def test_missing_evidence_stops_before_llm(project, monkeypatch):
    storage.write_json(project['id'], 'project.json', {**project, 'director_recipe': 'motion'})
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: pytest.fail('不能以模型调用代替缺失的证据'))
    with pytest.raises(ValueError, match='讲解配方缺证据'):
        planner.plan(project['id'], 'r1')


@pytest.mark.parametrize('durations', [[5] * 8, [9] * 3])
def test_short_plan_rejects_long_film_or_duration_overflow(project, monkeypatch, durations):
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: {'title': '错误预算', 'shots': [raw_shot(duration_s=d) for d in durations]})
    with pytest.raises(llm.LLMError):
        planner.plan(project['id'], 'r1', target_s=15)
    assert not (storage.project_dir(project['id']) / 'shotlist.json').exists()


def test_auto_repair_preserves_all_approved_and_human_fields(project, monkeypatch):
    pid = setup_sample(project)
    planner.plan(pid, 'r1')
    before = storage.read_json(pid, 'shotlist.json')
    before['shots'][0]['review'] = {'status': 'approved', 'note': '保留台词和时间'}
    before['shots'][0]['custom'] = {'do_not_touch': True}
    before['shots'][1]['human_edited'] = True
    storage.write_json(pid, 'shotlist.json', before)
    def complete(task, system, user, schema, **kwargs):
        assert [s['id'] for s in json.loads(user)['shots']] == ['S3']
        return {'shots': [raw_shot('model_orbit', id='S3')]}
    monkeypatch.setattr(llm, 'complete_json', complete)
    result = planner.repair(pid, 'r2', [{'severity': 'block', 'shot': sid} for sid in ['S1', 'S2', 'S3']])
    assert result['shots'][:2] == before['shots'][:2]
    assert result['shots'][3:] == before['shots'][3:]


def test_settings_partial_update_and_validation(project, monkeypatch):
    monkeypatch.setattr(main, 'blender_executable', lambda: None)
    client = TestClient(main.app)
    url = f"/api/projects/{project['id']}/settings"
    assert client.patch(url, json={'render_mode': 'photoreal'}).status_code == 200
    response = client.patch(url, json={'director_recipe': 'scale', 'target_s': 15})
    assert response.status_code == 200 and response.json()['render_mode'] == 'photoreal'
    assert response.json()['target_s'] == 15
    assert client.patch(url, json={'render_mode': 'standard'}).json()['director_recipe'] == 'scale'
    assert client.patch(url, json={'director_recipe': 'off'}).status_code == 200
    for payload in [{'director_recipe': 'unknown'}, {'target_s': 0}, {'target_s': 121}, {'target_s': 'NaN'}, {'surprise': 1}]:
        assert client.patch(url, json=payload).status_code == 422


def test_full_replan_reserves_budget_and_preserves_manual_fields(project, monkeypatch):
    pid = project['id']
    locked = {'id': 'H_custom', 'kind': 'title', 'source': 'graphic', 'duration_s': 3,
              'narration': '原台词逐字保留', 'params': {'title': '原始标题'}, 'review': {'status': 'approved', 'note': '已审核'},
              'fact_refs': [], 'asset_refs': [], 'analogy_refs': [], 'human_edited': True, 'custom': ['原始自定义字段']}
    original = {'version': 1, 'title': '原片', 'shots': [locked], 'analogies': []}
    storage.write_json(pid, 'shotlist.json', original)
    def complete(task, system, user, schema, **kwargs):
        ctx = json.loads(user)
        assert ctx['remaining_duration_s'] == 12
        assert ctx['preserved_shots'] == [locked]
        return {'title': '新片', 'shots': [raw_shot(id='H_custom', duration_s=10), raw_shot(id='S2', duration_s=7), raw_shot(id='S3', duration_s=5)]}
    monkeypatch.setattr(llm, 'complete_json', complete)
    result = planner.plan(pid, 'r2', target_s=15)
    assert result['shots'][0] == locked
    assert sum(s['duration_s'] for s in result['shots']) == 15
    # An infeasible shorter target cannot erase the existing approved shotlist.
    before = storage.read_json(pid, 'shotlist.json')
    with pytest.raises(ValueError, match='人工确认镜头'):
        planner.plan(pid, 'r3', target_s=3)
    assert storage.read_json(pid, 'shotlist.json') == before


def test_replan_omitting_manual_shot_does_not_write(project, monkeypatch):
    pid = project['id']
    original = {'title': '原片', 'shots': [{**raw_shot(id='H1', duration_s=3), 'review': {'status': 'approved'}}]}
    storage.write_json(pid, 'shotlist.json', original)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: {'title': '遗漏', 'shots': [raw_shot(id='S1', duration_s=5), raw_shot(id='S2', duration_s=5), raw_shot(id='S3', duration_s=5)]})
    with pytest.raises(llm.LLMError, match='全部人工确认'):
        planner.plan(pid, 'r2', target_s=15)
    assert storage.read_json(pid, 'shotlist.json') == original


@pytest.mark.parametrize('item', [
    fact('F_span', 88, name='跨度'),
    fact('F_lift_height', 40, name='起升高度'),
    fact('F_boom_length', 80, name='吊臂长度'),
    fact('F_leg_length', 40, name='支腿长度'),
    fact('F_girder_length', 104, name='起升高度'),
    fact('F_girder_length', 104, name='主梁总长（跨度）'),
    fact('F_girder_length', 104, name='整机高度'),
    fact('F_overall_height', 51, name='主梁高度'),
    fact('F_overall_height', 51, name='整机高度', key='lift_height'),
    fact('F_unknown', 51, name='高度'),
])
def test_scale_rejects_geometry_semantic_mismatch(item):
    ctx = context()
    ctx['facts'] = [item]
    result = select_recipe(ctx, 'scale', 15)
    assert result['status'] == 'needs_evidence' and result['sequence'] == []
    assert '当前尺度镜头只支持' in result['unavailable']['scale']


@pytest.mark.parametrize('item,axis', [
    (fact('F_girder_length', 104, name='长度'), 'length'),
    (fact('F_any', 104000, 'mm', name='主梁总长'), 'length'),
    (fact('F_any', 104, name='长度', key='girder_length'), 'length'),
    (fact('F_overall_height', 51, name='高度'), 'height'),
    (fact('F_any', 51000, 'mm', name='整机高度'), 'height'),
    (fact('F_any', 51, name='高度', key='overall_height'), 'height'),
])
def test_scale_accepts_canonical_id_key_or_name_and_keeps_unit_conversion(item, axis):
    from app.agent.analogy import compute
    ctx = context()
    ctx['facts'] = [item]
    result = select_recipe(ctx, 'scale', 15)
    assert result['status'] == 'selected'
    request = result['sequence'][1]['analogy_requests'][0]
    assert request['axis'] == axis
    ratio = compute('A_test', item, request['ref'], axis)['ratio']
    assert ratio == (round(104 / 105, 3) if axis == 'length' else 17)


def test_auto_missing_motion_evidence_never_switches_to_available_scale():
    ctx = context()
    ctx['brief'] = '必须讲解小车运动'
    result = select_recipe(ctx, 'auto', 15)
    assert result['status'] == 'needs_evidence'
    assert 'motion' in result['unavailable']
    assert result['sequence'] == []
    ctx['brief'] = '做一段展会宣传片'
    assert select_recipe(ctx, 'auto', 15)['recipe'] == 'scale'


@pytest.mark.parametrize('brief', ['主梁，到底多长？', '主梁究竟有多长？', '这台设备到底有多大？', '整机究竟多高？', '这个结构到底多长？'])
def test_auto_routes_natural_scale_question_before_component_keywords(brief):
    ctx = context()
    ctx['brief'] = brief
    selected = select_recipe(ctx, 'auto', 15)
    assert selected['status'] == 'selected' and selected['recipe'] == 'scale'
    ctx['model']['nodes'] = []
    missing = select_recipe(ctx, 'auto', 15)
    assert missing['status'] == 'needs_evidence'
    assert set(missing['unavailable']) == {'scale'}


def test_workflow_long_plan_expands_theme_without_changing_legacy_recipe(project, monkeypatch):
    pid = setup_sample(project)
    saved = storage.read_json(pid, 'project.json')
    saved.update(production_engine='blender', director_recipe='scale', target_s=40, render_mode='standard')
    storage.write_json(pid, 'project.json', saved)
    ctx = planner._context(pid)
    assert ctx['director']['planning_mode'] == 'expanded_theme'
    assert ctx['director']['shot_budget'] == [6, 9]
    assert 'sequence' not in ctx['director']
    assert ctx['director']['theme_evidence']
    assert 'copywriting' in ctx and ctx['copywriting']
    assert '轴线' in ctx['cinematography']
    assert 'T26 本次独立' not in ctx['cinematography']
    assert ctx['render_capabilities']['supported_analogy_refs'] == ['building_floor', 'football_field']
    assert 'weld_macro' not in ctx['render_capabilities']['shot_kinds']
    system = planner.planner_system(pid, 40)
    assert '6–9' in system and '不是固定三镜模板' in system and '设备运动或结构拆解' in system
    def generate(task, system, prompt, schema, **kwargs):
        return {'title': '多角度观察', 'shots': [raw_shot('model_orbit', duration_s=5, narration='观察模型的空间关系。',
                   params={'from_deg': -30 + i * 10, 'to_deg': -20 + i * 10, 'elevation_deg': 10 + i * 2}) for i in range(8)]}
    monkeypatch.setattr(llm, 'complete_json', generate)
    planned = planner.plan(pid, 'long')
    assert len(planned['shots']) == 8 and sum(s['duration_s'] for s in planned['shots']) == 40
    assert all(s['kind'] == 'model_orbit' for s in planned['shots'])
    # The same old and short recipe stays a three-shot selector output.
    saved.pop('production_engine')
    storage.write_json(pid, 'project.json', saved)
    assert len(planner._context(pid)['director']['sequence']) == 3
    saved['production_engine'] = 'blender'
    saved['target_s'] = 15
    storage.write_json(pid, 'project.json', saved)
    assert len(planner._context(pid)['director']['sequence']) == 3
