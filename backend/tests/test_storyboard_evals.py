"""评测工具的离线回归：随机盲标、失败统计、触发事件和报告防串组。"""
from copy import deepcopy
import json
from pathlib import Path
import random
from types import SimpleNamespace

import pytest
from test_skill_parity import SKILL, skill_io, skill_validator, evals, load_module, sample_input

support = load_module('eval_support_test', SKILL / 'evals/eval_support.py')
judge = load_module('judge_test', SKILL / 'evals/judge.py')
trigger = load_module('trigger_test', SKILL / 'evals/run_trigger.py')
report = load_module('report_test', SKILL / 'evals/report.py')


def pair(tmp_path: Path) -> dict:
    case = support.select_cases('standard')[0]
    facts, assets, project, rig = sample_input()
    for group in support.GROUPS:
        folder = tmp_path / 'standard' / group / 'run-1'
        shots = skill_io.read_json(SKILL / 'evals/fixtures/standard/shotlist.json')
        skill_io.write_json(folder / 'shotlist.json', shots)
        validation = skill_validator.validate(facts, shots, assets, project, rig)
        skill_io.write_json(folder / 'validation-report.json', validation)
        skill_io.write_json(folder / 'grading.json', {'status':'已评分', 'block':0, 'warn':0, 'assertions':[], 'assertion_rate':1})
    skill_io.write_json(tmp_path / 'run-manifest.json', {'cases': {'standard': 3}})
    return case


def scores(a=5, b=3) -> dict:
    return {'A':dict.fromkeys(support.METRICS,a), 'B':dict.fromkeys(support.METRICS,b),
            'winner':'A' if a > b else 'B' if a < b else 'tie', 'reason':'甲开场更具体，乙仍以报数开场。'}


def test_blind_judge_mapping_cached_scoring_and_stats(tmp_path):
    case = pair(tmp_path)
    calls = []
    def fake(command, **kwargs):
        prompt = kwargs['input']; calls.append(prompt)
        assert 'with_skill' not in prompt and 'without_skill' not in prompt
        assert 'validation-report' not in prompt and 'grading.json' not in prompt
        assert '104米' in prompt and '{{F_' not in prompt
        assert command[command.index('--model')+1] == 'claude-opus-5-5'
        assert command[command.index('--tools')+1] == ''
        return SimpleNamespace(returncode=0, stdout=json.dumps({'result':json.dumps(scores(),ensure_ascii=False)}), stderr='')
    result = judge.judge_pair(tmp_path, case, 1, runner=fake, rng=random.Random(1))
    mapping = skill_io.read_json(tmp_path / 'standard/judge-1.mapping.json')
    assert result['winner_group'] == mapping['A']
    assert judge.judge_pair(tmp_path,case,1,score_only=True)['groups'] == result['groups']
    assert len(calls) == 1
    summary = support.summarize(tmp_path)
    assert all(r['completed'] == 1 and r['failed'] == 2 for r in summary['rows'])
    assert all(r['assertion_rate']['mean'] == pytest.approx(1/3) for r in summary['rows'])
    assert summary['overall'][mapping['A']]['win_rate'] == 1
    assert summary['overall'][mapping['B']]['prose'] == 3


def test_judge_rejects_stale_failed_and_bad_score_caches(tmp_path):
    case = pair(tmp_path)
    fake=lambda *a,**k: SimpleNamespace(returncode=0,stdout=json.dumps(scores()),stderr='')
    judge.judge_pair(tmp_path,case,1,runner=fake)
    folder = tmp_path / 'standard/with_skill/run-1'
    shots = skill_io.read_json(folder/'shotlist.json'); shots['shots'][0]['narration'] = '已经改写。'
    skill_io.write_json(folder/'shotlist.json',shots)
    assert judge.judge_pair(tmp_path,case,1,score_only=True)['status'] == '未完成'
    judge.judge_pair(tmp_path,case,1,runner=fake)
    skill_io.write_json(tmp_path/'standard/judge-1.status.json',{'returncode':1})
    assert judge.judge_pair(tmp_path,case,1,score_only=True)['status'] == '未完成'
    for bad in [scores(a=6),{**scores(),'winner':'B'}, {**scores(),'A':{'hook':True}}]:
        with pytest.raises(ValueError): judge.parse_scores(json.dumps(bad))


def event(name, inputs):
    return {'type':'assistant','message':{'content':[{'type':'tool_use','name':name,'input':inputs}]}}


@pytest.mark.parametrize('events,expected', [
    ([event('Skill',{'skill':'industrial-explainer-storyboard'})],True),
    ([event('Read',{'file_path':'.claude/skills/industrial-explainer-storyboard/SKILL.md'})],True),
    ([event('Bash',{'command':'cat .claude/skills/industrial-explainer-storyboard/SKILL.md'})],True),
    ([event('Read',{'file_path':'.claude/skills/other/SKILL.md'})],False),
    ([event('Bash',{'command':'echo .claude/skills/industrial-explainer-storyboard/SKILL.md'})],False),
    ([{'type':'assistant','message':{'content':[{'type':'text','text':'我已读取 industrial-explainer-storyboard/SKILL.md'}]}}],False),
])
def test_trigger_actual_tool_events_only(events,expected):
    stream='\n'.join(json.dumps(e) for e in events + [{'type':'result','subtype':'success','is_error':False}])
    assert trigger.detect_trigger(stream) == (expected,True)


def test_trigger_installs_without_prompting_and_excludes_failed_denominators(tmp_path):
    cases=skill_io.read_json(SKILL/'evals/trigger_evals.json')['evals']
    assert len(cases)==20 and sum(c['expected'] for c in cases)==10
    case=cases[0]
    def fake(command,**kwargs):
        assert kwargs['input']==case['prompt']
        assert (kwargs['cwd']/'.claude/skills/industrial-explainer-storyboard/SKILL.md').is_file()
        assert not (kwargs['cwd']/'.claude/skills/industrial-explainer-storyboard/evals').exists()
        assert '--verbose' in command and 'stream-json' in command
        data=[event('Skill',{'skill':trigger.NAME}), {'type':'result','subtype':'success'}]
        return SimpleNamespace(returncode=0,stdout='\n'.join(json.dumps(e) for e in data),stderr='')
    result=trigger.run_one(case,tmp_path/'run-1',30,runner=fake)
    assert result['triggered'] is True
    assert trigger.score_one(case,tmp_path/'absent')['status']=='失败'
    summary=trigger.aggregate([result,{'name':'bad','expected':False,'status':'失败','triggered':None}])
    assert summary['trigger_rate']==1 and summary['false_trigger_rate'] is None


def test_report_side_by_side_escapes_candidate_html_and_marks_missing(tmp_path):
    pair(tmp_path)
    folder=tmp_path/'standard/with_skill/run-1'
    shots=skill_io.read_json(folder/'shotlist.json');shots['shots'][0]['narration']='<script>alert(1)</script>'
    skill_io.write_json(folder/'shotlist.json',shots)
    page=report.generate(tmp_path).read_text()
    assert 'class="pair"' in page and '使用技能' in page and '未使用技能' in page
    assert '<script>' not in page and '&lt;script&gt;' in page
    assert '<link' not in page and 'src="http' not in page
    assert '未完成' in page and '0.00 ± 0.00' in page


def test_hard_case_assertions_reject_cheating():
    case = support.select_cases('edit_preserve')[0]
    folder = SKILL/'evals/fixtures/edit_preserve'
    shots = skill_io.read_json(folder/'shotlist.json')
    a=next(a for a in case['assertions'] if a['type']=='preserve')
    assert evals.assertion_passes(a,shots,{'issues':[]},{},{},'')
    shots['shots'][1]['narration'] += '已修改'
    assert not evals.assertion_passes(a,shots,{'issues':[]},{},{},'')
    for name in ('bridge_crane','english_facts'):
        facts,_,_,_=sample_input(name)
        assert {f['id'] for f in facts['facts']}=={'F_rated_load','F_span','F_hoist_speed'}
    original=skill_io.read_json(SKILL/'evals/fixtures/standard/shotlist.json')
    facts,assets,_,_=sample_input()
    original['shots'][0]['narration']='精度提升三百倍'
    assert not evals.assertion_passes({'type':'no_terms','terms':['三百']},original,{'issues':[]},facts,assets,'')


def test_standard_deviation_and_empty_values():
    assert support.stats([1,2,3]) == {'n':3,'mean':2,'std':1}
    assert support.stats([])['mean'] is None


def test_three_run_cli_then_score_only_never_calls_model(tmp_path, monkeypatch):
    import shutil
    monkeypatch.syspath_prepend(str(SKILL / 'evals'))
    root = tmp_path / 'skill'
    shutil.copytree(SKILL, root, ignore=shutil.ignore_patterns('workspace', '__pycache__'))
    monkeypatch.setattr(evals, 'SKILL', root)
    calls = []
    source = skill_io.read_json(SKILL/'evals/fixtures/standard/shotlist.json')
    def fake(command, **kwargs):
        calls.append(command)
        if command[0] == 'claude':
            if command[command.index('--tools') + 1] == '':
                return SimpleNamespace(returncode=0, stdout=json.dumps(scores()), stderr='')
            skill_io.write_json(kwargs['cwd']/'shotlist.json',source)
            (kwargs['cwd']/'delivery-report.md').write_text('离线替身产物，仅用于验证工具流程。')
            return SimpleNamespace(returncode=0,stdout='{"is_error":false}',stderr='')
        result = skill_validator.main(command[2:])
        return SimpleNamespace(returncode=result,stdout='离线校验完成',stderr='')
    monkeypatch.setattr(evals.subprocess,'run',fake)
    assert evals.main(['--only','standard','--runs','3']) == 0
    output=root/'evals/workspace/iteration-1'
    assert len([c for c in calls if c[0]=='claude']) == 9
    result=skill_io.read_json(output/'benchmark.json')
    assert all(r['completed']==3 and r['prose']['n']==3 and r['block']['mean']==0 for r in result['rows'])
    assert (output/'report.html').exists()
    calls.clear()
    assert evals.main(['--score-only',str(output),'--only','standard']) == 0
    assert not any(c[0]=='claude' for c in calls)


def test_grade_and_benchmark_expose_independent_traceability(tmp_path):
    from test_accuracy import BASES
    case = support.select_cases('standard')[0]
    folder = tmp_path / 'standard/with_skill/run-1'
    shots = deepcopy(BASES[0]['shotlist'])
    skill_io.write_json(folder / 'shotlist.json', shots)
    def fake(command, **kwargs):
        return SimpleNamespace(returncode=skill_validator.main(command[2:]), stdout='', stderr='')
    result = evals.grade(case, folder, runner=fake)
    assert result['traceability_rate'] == 1 and result['traceability_passed']
    assert result['traceability']['total'] == 6
    summary = support.summarize(tmp_path)
    row = next(r for r in summary['rows'] if r['group'] == 'with_skill')
    assert row['traceability_rate']['mean'] == 1
    assert '可溯源率' in (tmp_path / 'benchmark.md').read_text()
    shots['shots'][0]['narration'] += '设备交付华星集团。'
    skill_io.write_json(folder / 'shotlist.json', shots)
    result = evals.grade(case, folder, runner=fake)
    assert result['traceability']['total'] == 7 and result['traceability_rate'] < 1
    assert not result['traceability_passed']
    shots['shots'] = []
    skill_io.write_json(folder / 'shotlist.json', shots)
    result = evals.grade(case, folder, runner=fake)
    assert result['traceability_rate'] is None and not result['traceability_passed']
