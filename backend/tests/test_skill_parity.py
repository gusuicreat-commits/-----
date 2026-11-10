"""独立技能与项目规则的离线一致性；禁止调用真实模型。"""
from copy import deepcopy
import ast
import importlib.util
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest
from app import config, storage
from app.agent import analogy, planner, text, validator
from app.model3d.rig import motion_speedup
import test_validator as existing
from test_validator import scenario
from test_planner import setup_sample

SKILL = config.ROOT / 'skills/industrial-explainer-storyboard'
SCRIPTS = SKILL / 'scripts'


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    before = list(sys.path)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


skill_validator = load_module('skill_validator', SCRIPTS / 'validate_shotlist.py')
skill_analogy = load_module('skill_analogy', SCRIPTS / 'compute_analogy.py')
skill_text = load_module('skill_text', SCRIPTS / 'resolve_text.py')
skill_io = load_module('skill_io', SCRIPTS / 'skill_io.py')
skill_rules = load_module('skill_rules', SCRIPTS / '_rules.py')
evals = load_module('skill_evals', SKILL / 'evals/run_evals.py')


def assert_parity(pid: str) -> dict:
    independent = deepcopy(storage.read_json(pid, 'shotlist.json'))
    report = skill_validator.validate(storage.read_json(pid, 'facts.json'), independent,
        storage.read_json(pid, 'assets.json', {'assets': []}), storage.read_json(pid, 'project.json'),
        storage.read_json(pid, 'model/rig.json', {'axes': {}}))
    backend = validator.validate(pid, 'skill-parity')
    triples = lambda r: {(i['code'], i['severity'], i['shot']) for i in r['issues']}
    assert triples(report) == triples(backend)
    assert [{k: i[k] for k in ('code', 'severity', 'shot', 'message')} for i in report['issues']] == [
        {k: i[k] for k in ('code', 'severity', 'shot', 'message')} for i in backend['issues']]
    assert independent == storage.read_json(pid, 'shotlist.json')
    for issue in report['issues']:
        assert all(issue.get(k) for k in ('code', 'severity', 'field', 'message', 'fix'))
        if issue['shot']:
            assert issue['shot'] in issue['fix']
    return report


def parameters(test):
    return next(mark.args[1] for mark in test.pytestmark if mark.name == 'parametrize')


@pytest.mark.parametrize('updates,expected', parameters(existing.test_issue_codes))
def test_existing_issue_fixture_parity(scenario, updates, expected):
    existing.write_shot(scenario, existing.shot(**deepcopy(updates)))
    assert expected in {i['code'] for i in assert_parity(scenario)['issues']}


@pytest.mark.parametrize('narration,blocked', parameters(existing.test_duplicate_phrase))
def test_existing_text_fixture_parity(scenario, narration, blocked):
    existing.write_shot(scenario, existing.shot(narration=narration))
    assert_parity(scenario)
    assert skill_text.find_unsourced_numbers(narration) == text.find_unsourced_numbers(narration)
    assert skill_text.find_duplicate_phrases(narration) == text.find_duplicate_phrases(narration)


@pytest.mark.parametrize('status', ['verified', 'confirmed', 'needs_review', 'extracted', 'rejected', 'missing'])
def test_status_motion_and_indirect_fact_parity(scenario, status):
    facts = storage.read_json(scenario, 'facts.json')
    if status == 'missing':
        facts['facts'].pop()
    else:
        facts['facts'][1]['status'] = status
    facts['facts'][0]['status'] = status
    storage.write_json(scenario, 'facts.json', facts)
    a = analogy.compute('A_test', facts['facts'][0], 'football_field', 'length')
    existing.write_shot(scenario, existing.shot('motion', narration='{{A_test}}', fact_refs=[],
        params={'axis': 'trolley', 'from_m': -30, 'to_m': 30, 'speedup': 999}), [a])
    assert_parity(scenario)


@pytest.mark.parametrize('kind', list(planner.PARAM_DEFAULTS))
@pytest.mark.parametrize('has_model', [True, False])
def test_sources_defaults_and_modes(scenario, kind, has_model):
    project = storage.read_json(scenario, 'project.json')
    project['render_mode'] = 'photoreal'
    if not has_model:
        project['model'] = None
    storage.write_json(scenario, 'project.json', project)
    assert skill_rules.PARAM_DEFAULTS == planner.PARAM_DEFAULTS
    assert skill_rules.expected_source(kind, project['model']) == planner.expected_source(kind, project['model'])
    existing.write_shot(scenario, existing.shot(kind, params=deepcopy(planner.PARAM_DEFAULTS[kind])))
    assert_parity(scenario)


@pytest.mark.parametrize('field', ['prompt', 'caption'])
@pytest.mark.parametrize('word', ['起重机', '门机', '龙门吊', '吊车', '主梁', '支腿', '吊钩', '小车', 'CRANE', 'gantry', 'hook', 'girder'])
def test_all_equipment_words(scenario, field, word):
    existing.write_shot(scenario, existing.shot('ai_broll', source='ai', params={field: word}))
    assert_parity(scenario)


def test_model_metadata_bad_data_and_all_photoreal_codes(scenario):
    project = storage.read_json(scenario, 'project.json')
    project['model'].update(dims_check=[{'ok': False, 'message': '尺寸不符'}], assumed=['F_span'])
    project['render_mode'] = 'photoreal'
    storage.write_json(scenario, 'project.json', project)
    storage.write_json(scenario, 'shotlist.json', {'shots': [existing.shot('title', id='S1'),
        existing.shot('analogy', id='S2'), existing.shot('analogy', id='S3'),
        existing.shot('real_media', id='S4'), existing.shot(id='S5', params=None), None], 'analogies': []})
    report = assert_parity(scenario)
    assert {'PHOTOREAL_OPENING', 'PHOTOREAL_REAL_MEDIA_ORDER', 'PHOTOREAL_MISSING_EXPLODED',
        'PHOTOREAL_MISSING_MOTION', 'PHOTOREAL_MODEL_COUNT', 'PHOTOREAL_ANALOGY_COUNT',
        'MODEL_DIMS_MISMATCH', 'MODEL_ASSUMED', 'CHECK_ERROR'} <= {i['code'] for i in report['issues']}
    assert report['passed'] is False


@pytest.mark.parametrize('value', [0, .063, .07, .077, 1, 2.5, 3.5, 9.5, 10, 104, 1230])
@pytest.mark.parametrize('ref', list(analogy.REFS))
def test_analogy_values_and_resolve(value, ref):
    item = analogy.REFS[ref]
    fact = {'id': 'F_value', 'value': value, 'unit': item['unit'], 'status': 'confirmed'}
    a = skill_analogy.compute('A_test', fact, ref, item['axes'][0])
    assert a == analogy.compute('A_test', fact, ref, item['axes'][0])
    line = '{{F_value}}，{{A_test}}。{{F_missing}}'
    assert skill_text.resolve(line, {'F_value': fact}, {'A_test': a}) == text.resolve(line, {'F_value': fact}, {'A_test': a})


@pytest.mark.parametrize('value,unit,ref,axis', [(104000, 'mm', 'football_field', 'length'),
    (.0005, 'm', 'hair', 'thickness'), (94.5, 'm', 'football_field', 'length'),
    (115.5, 'm', 'football_field', 'length'), (-1, 'm', 'bus', 'length'),
    (float('inf'), 'mm', 'hair', 'thickness'), (30, 'm/min', 'bus', 'length'),
    (10, 'm', 'bus', 'height'), (10, 'm', 'unknown', 'length')])
def test_conversion_boundary_and_invalid_analogy(value, unit, ref, axis):
    fact = {'id': 'F_test', 'value': value, 'unit': unit}
    try:
        expected = analogy.compute('A_test', fact, ref, axis)
    except ValueError as exc:
        with pytest.raises(ValueError, match=re.escape(str(exc))):
            skill_analogy.compute('A_test', fact, ref, axis)
    else:
        assert skill_analogy.compute('A_test', fact, ref, axis) == expected


@pytest.mark.parametrize('start,end,duration,speed', [(0, 30, 6, 30), (-31, 10, 6, 30), (0, 1, 0, 1), (0, 1, 1, float('inf'))])
def test_motion_math_parity(start, end, duration, speed):
    rig = {'axes': {'trolley': {'range_m': [-30, 30]}}}
    assert skill_rules.motion_speedup(rig, 'trolley', start, end, duration, speed) == motion_speedup(rig, 'trolley', start, end, duration, speed)


def test_sample_replay_before_after_repair(project):
    pid = setup_sample(project)
    planner.plan(pid, 'r1')
    assert_parity(pid)
    # 原回放只接收后端问题字段，技能扩展字段不能改变录制输入。
    planner.repair(pid, 'r1', storage.read_json(pid, 'issues.json'))
    assert not assert_parity(pid)['counts']['block']


def sample_input(name='standard') -> tuple:
    folder = SKILL / 'evals/fixtures' / name
    return tuple(skill_io.read_json(folder / f'{stem}.json') for stem in ('facts', 'assets', 'project', 'rig'))


@pytest.mark.parametrize('filename', ['shotlist.json', 'shotlist-errors.json'])
def test_packaged_sample_and_six_errors(project, filename):
    facts, assets, meta, rig = sample_input()
    pid = project['id']
    shots = skill_io.read_json(SKILL / 'evals/fixtures/standard' / filename)
    for path, data in [('facts.json', facts), ('assets.json', assets), ('project.json', {**project, **meta}),
                      ('model/rig.json', rig), ('shotlist.json', shots)]:
        storage.write_json(pid, path, data)
    report = assert_parity(pid)
    assert report['counts'] == ({'block': 5, 'warn': 1, 'info': 1} if filename == 'shotlist-errors.json' else {'block': 0, 'warn': 0, 'info': 1})
    assert not skill_io.schema_errors(shots, skill_io.read_json(SCRIPTS / 'shotlist.schema.json'))


def test_cli_pipeline_from_unrelated_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(SCRIPTS))
    fixture = SKILL / 'evals/fixtures/standard'
    original = (fixture / 'shotlist.json').read_bytes()
    assert skill_analogy.main(['--facts', str(fixture / 'facts.json'), '--requests', str(fixture / 'requests.json'), '--out', str(tmp_path / 'analogies.json')]) == 0
    assert skill_text.main(['--facts', str(fixture / 'facts.json'), '--shotlist', str(fixture / 'shotlist.json'), '--analogies', str(tmp_path / 'analogies.json'), '--out', str(tmp_path / 'resolved.json'), '--shotlist-out', str(tmp_path / 'shotlist.json')]) == 0
    assert skill_validator.main(['--facts', str(fixture / 'facts.json'), '--shotlist', str(tmp_path / 'shotlist.json'), '--assets', str(fixture / 'assets.json'), '--project', str(fixture / 'project.json'), '--rig', str(fixture / 'rig.json'), '--out', str(tmp_path / 'report.json'), '--shotlist-out', str(tmp_path / 'shotlist.json')]) == 0
    assert (fixture / 'shotlist.json').read_bytes() == original
    report = skill_io.read_json(tmp_path / 'report.json')
    assert report['passed'] and report['skipped'] == []
    assert all(s['estimated_duration_s'] == round(s['characters'] / 4.5 + .8, 3) for s in skill_io.read_json(tmp_path / 'resolved.json')['shots'])


def test_partial_inputs_and_pending_facts():
    facts, assets, meta, rig = sample_input('unverified')
    shots = {'shots': [existing.shot('motion', params={'axis': 'trolley', 'from_m': -30, 'to_m': 30})], 'analogies': []}
    report = skill_validator.validate(facts, deepcopy(shots), assets)
    assert any('MOTION_OUT_OF_RANGE' in item['codes'] for item in report['skipped'])
    assert any('MODEL_DIMS_MISMATCH' in item['codes'] for item in report['skipped'])
    assert any(i['fact'] == 'F_overall_height' for i in report['manual_review'])
    assert 'MOTION_AXIS_UNAVAILABLE' in {i['code'] for i in skill_validator.validate(facts, deepcopy(shots), assets, meta, {'axes': {}})['issues']}
    with pytest.raises(ValueError, match='未确认'):
        skill_analogy.compute_requests(facts, {'requests': [{'fact': 'F_overall_height', 'ref': 'building_floor', 'axis': 'height'}]})


def test_all_bad_references_get_fixes():
    report = skill_validator.validate({'facts': []}, {'shots': [existing.shot(
        narration='{{F_a}}、{{F_b}}，30米和40米。', fact_refs=['F_a', 'F_b'], asset_refs=['IMG_a', 'IMG_b'])], 'analogies': []})
    for code in ('UNKNOWN_FACT', 'ASSET_MISSING', 'UNSOURCED_NUMBER'):
        assert sum(i['code'] == code for i in report['issues']) == 2
    assert all(i['field'] and i['fix'] for i in report['issues'])


def test_schema_cli_rejects_bad_structure(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    facts, assets, meta, rig = sample_input()
    shots = skill_io.read_json(SKILL / 'evals/fixtures/standard/shotlist.json')
    shots['shots'][0]['id'] = shots['shots'][1]['id']
    shots['shots'][0]['kind'] = 'unknown'
    shots['fps'] = 24
    skill_io.write_json(tmp_path / 'facts.json', facts)
    skill_io.write_json(tmp_path / 'shots.json', shots)
    assert skill_validator.main(['--facts', str(tmp_path / 'facts.json'), '--shotlist', str(tmp_path / 'shots.json'), '--out', str(tmp_path / 'report.json')]) == 1
    report = skill_io.read_json(tmp_path / 'report.json')
    assert not report['passed'] and len(report['input_errors']) >= 3
    assert skill_validator.main(['--facts', str(tmp_path / 'absent.json'), '--shotlist', str(tmp_path / 'shots.json'), '--out', str(tmp_path / 'report.json')]) == 2


def test_skill_metadata_references_and_independence():
    content = (SKILL / 'SKILL.md').read_text()
    assert len(content.splitlines()) <= 300
    frontmatter = content.split('---', 2)[1]
    assert 'name: industrial-explainer-storyboard' in frontmatter
    description = next(line.partition(':')[2].strip() for line in frontmatter.splitlines() if line.startswith('description:'))
    assert 0 < len(description) <= 1024
    for word in ('起重机', '门机', '桥机', '工业装备', '科普视频', '宣传片', '展会视频', '投标视频', '分镜', '脚本', '台词', '参数核对', '真实性校验', 'shotlist'):
        assert word in description
    for reference in (SKILL / 'references').glob('*.md'):
        assert f'(references/{reference.name})' in content
        if len(reference.read_text().splitlines()) > 100:
            assert '目录' in '\n'.join(reference.read_text().splitlines()[:12])
        assert not re.search(r'\]\([^)]*references/', reference.read_text())
    for script in SCRIPTS.glob('*.py'):
        for node in ast.walk(ast.parse(script.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split('.')[0] in sys.stdlib_module_names | {'_rules', 'skill_io', 'compute_analogy', 'resolve_text'}
            elif isinstance(node, ast.Import):
                assert all(a.name.split('.')[0] in sys.stdlib_module_names for a in node.names)


def test_eval_manifest_and_assertions(tmp_path):
    cases = skill_io.read_json(SKILL / 'evals/evals.json')['evals']
    assert len(cases) == 5 and len({case['id'] for case in cases}) == 5
    facts, assets, meta, rig = sample_input()
    shots = skill_io.read_json(SKILL / 'evals/fixtures/standard/shotlist.json')
    report = skill_validator.validate(facts, shots, assets, meta, rig)
    report['input_errors'] = []
    for case in cases:
        assert {'id', 'prompt', 'expected_output', 'files', 'assertions'} <= case.keys()
        assert all((SKILL / 'evals' / f).exists() for f in case['files'])
    assert all(evals.assertion_passes(a, shots, report, facts, assets, '') for a in cases[0]['assertions'])
    pending, _, _, _ = sample_input('unverified')
    altered = deepcopy(shots)
    altered['shots'][0]['narration'] = '{{F_overall_height}}'
    assert not evals.assertion_passes({'type': 'confirmed_only'}, altered, report, pending, assets, '')
    altered['analogies'][0]['ratio'] = 999
    assert not evals.assertion_passes({'type': 'computed_analogies'}, altered, report, facts, assets, '')
    assert not evals.assertion_passes({'type': 'human_review', 'fact': 'F_overall_height'}, shots, report, facts, assets, '')
    summary = evals.grade(cases[0], tmp_path, runner=lambda *a, **k: SimpleNamespace(returncode=2, stdout='', stderr='缺少输出文件'))
    assert summary['block'] is None and summary['assertion_rate'] == 0 and summary['status'] == '失败'


@pytest.mark.parametrize('group', ['with_skill', 'without_skill'])
def test_eval_runner_isolation_and_scoring(tmp_path, monkeypatch, group):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    case = skill_io.read_json(SKILL / 'evals/evals.json')['evals'][0]
    calls = []

    def fake_runner(command, **kwargs):
        calls.append(command)
        if command[0] == 'claude':
            sandbox = kwargs['cwd']
            assert not sandbox.is_relative_to(config.ROOT)
            assert not (sandbox / 'shotlist.json').exists()
            assert (sandbox / '.claude/skills/industrial-explainer-storyboard/SKILL.md').exists() == (group == 'with_skill')
            assert not (sandbox / '.claude/skills/industrial-explainer-storyboard/evals').exists()
            assert ('--disable-slash-commands' in command) == (group == 'without_skill')
            assert command[command.index('--model') + 1] == 'claude-opus-5-5'
            shots = skill_io.read_json(SKILL / 'evals/fixtures/standard/shotlist.json')
            skill_io.write_json(sandbox / 'shotlist.json', shots)
            (sandbox / 'delivery-report.md').write_text('示例分镜待人工复核。')
            # 模拟模型篡改输入；评分必须仍使用原始夹具。
            skill_io.write_json(sandbox / 'facts.json', {'facts': []})
            return SimpleNamespace(returncode=0, stdout='{"is_error":false}', stderr='')
        assert command[command.index('--facts') + 1] == str(SKILL / 'evals/fixtures/standard/facts.json')
        code = skill_validator.main(command[2:])
        return SimpleNamespace(returncode=code, stdout='离线校验完成', stderr='')

    result = evals.run_case(case, group, tmp_path / group, 60, runner=fake_runner)
    assert len(calls) == 2 and result['assertion_rate'] == 1
    assert result['block'] == result['warn'] == 0
    assert (tmp_path / group / 'grading.json').is_file()
    assert not list(tmp_path.glob('industrial-storyboard-eval-*'))


def test_rescoring_failed_model_does_not_turn_green(tmp_path):
    case = skill_io.read_json(SKILL / 'evals/evals.json')['evals'][0]
    facts, assets, project, rig = sample_input()
    shots = skill_io.read_json(SKILL / 'evals/fixtures/standard/shotlist.json')
    report = skill_validator.validate(facts, deepcopy(shots), assets, project, rig)
    report['input_errors'] = []
    skill_io.write_json(tmp_path / 'shotlist.json', shots)
    skill_io.write_json(tmp_path / 'validation-report.json', report)
    skill_io.write_json(tmp_path / 'run-status.json', {'returncode': 1, 'error': '模拟调用失败'})
    summary = evals.grade(case, tmp_path, runner=lambda *a, **k: SimpleNamespace(returncode=0, stdout='', stderr=''))
    assert summary['status'] == '模型运行失败' and summary['assertion_rate'] == 0


@pytest.mark.parametrize('broken', [{'shots': None}, {'shots': '无效'}, {'shots': [None]}, {'shots': [{'id': 'S1', 'params': None}]}])
def test_invalid_containers_still_write_report(tmp_path, monkeypatch, broken):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    skill_io.write_json(tmp_path / 'facts.json', {'facts': None})
    skill_io.write_json(tmp_path / 'shots.json', broken)
    result = skill_validator.main(['--facts', str(tmp_path / 'facts.json'), '--shotlist', str(tmp_path / 'shots.json'), '--out', str(tmp_path / 'report.json')])
    assert result == 1
    assert skill_io.read_json(tmp_path / 'report.json')['passed'] is False
