"""准确度门槛、容差边界、误报及两端规则一致性；全部离线。"""
from copy import deepcopy
from pathlib import Path
import sys

import pytest
from app import storage
from app.agent import accuracy_rules, analogy, planner, validator
from app.ingest.facts import ExtractedFact, extract_facts, update_fact
from test_skill_parity import SKILL, load_module, skill_io, skill_validator, assert_parity

mutation_dir = SKILL / 'evals/mutation'
sys.path.insert(0, str(mutation_dir))
mutate = load_module('accuracy_mutate', mutation_dir / 'mutate.py')
scorer = load_module('accuracy_score', mutation_dir / 'score_mutation.py')
BASES = mutate.build_baselines()
MUTATIONS = mutate.mutations(BASES)


def install(pid: str, item: dict) -> None:
    for path, key in [('facts.json', 'facts'), ('assets.json', 'assets'), ('project.json', 'project'),
                      ('model/rig.json', 'rig'), ('shotlist.json', 'shotlist')]:
        storage.write_json(pid, path, item[key])


@pytest.mark.parametrize('item', MUTATIONS, ids=lambda i: i['id'])
def test_mutations_detect_expected_fault_with_backend_skill_parity(project, item):
    install(project['id'], item)
    result = assert_parity(project['id'])
    assert set(item['expected']) & {i['code'] for i in result['issues'] if i['severity'] in {'block', 'warn'}}
    assert 'CHECK_ERROR' not in {i['code'] for i in result['issues']}


@pytest.mark.parametrize('item', BASES + mutate.positives(BASES), ids=lambda i: i.get('id', i['name']))
def test_correct_and_adversarial_positives(project, item):
    install(project['id'], item)
    result = assert_parity(project['id'])
    assert not [i for i in result['issues'] if i['severity'] != 'info']
    assert not skill_io.schema_errors(item['shotlist'], skill_io.read_json(SKILL / 'scripts/shotlist.schema.json'))
    audit = accuracy_rules.traceability(item['facts'], item['shotlist'], item['assets'], result['issues'])
    # 正确样本的零误报与可溯源率是不同指标；未取证的 generic 常识保留未支撑。
    assert audit['rate'] == (5 / 6 if item.get('id') in {'correct-05', 'correct-07', 'correct-08', 'correct-12', 'correct-13', 'correct-16'} else 1)


def test_mutation_gate_and_report_are_reproducible(tmp_path):
    result = scorer.score()
    assert result['total'] >= 150 and len(result['rows']) == 15
    assert all(r['total'] >= 10 and r['recall'] >= .95 for r in result['rows'])
    assert result['recall'] >= .99 and result['false_positive_rate'] == 0 and result['passed']
    path = tmp_path / 'report.md'
    scorer.write_report(result, path)
    assert path.read_text() == (mutation_dir / 'report.md').read_text()


@pytest.mark.parametrize('value,unit,quote,match', [
    (1230, 't', '起重量１２３０．０ 吨', True), (1230, '吨', '起重量 1,230 t', True),
    (1234567, 't', '1,234,567 t', True), (1230, 't', '起重量 12300 t', False),
    (.5, 'mm', '公差０．５毫米', True), (.5, 'mm', '公差0.05 mm', False),
    (104, 'm', '长度104米', True), (104, 'm', '长度104毫米', False),
    (8, 'm/min', '速度0～8 米每分', True), (8, '米每分', '速度8 m/min', True),
    (8, 'm/min', '速度8米每分钟', True), (8, 'm/min', '速度8 m/s', False),
    (104, 'm', '1040m，另有104吨', False), (0, 'mm', '0.5 mm', False),
    (51, 'm', 'Height 51 m', True), (.5, 'mm', '公差 .5 mm', True),
    (1.5, 't', '1,5 t', False), (1230, 't', '1230 kg', False),
])
def test_quote_normalization_and_token_boundaries(value, unit, quote, match, project):
    item = deepcopy(BASES[0])
    fact = item['facts']['facts'][0]
    fact.update(value=value, unit=unit, source={'doc': '原文.pdf', 'page': 1, 'quote': quote})
    item['shotlist']['shots'] = [mutate.shot('S1', '{{F_rated_load}}', claims=[{'text': '{{F_rated_load}}', 'support': 'F_rated_load'}])]
    assert accuracy_rules.quote_matches(fact) is match
    install(project['id'], item)
    result = assert_parity(project['id'])
    assert ('QUOTE_MISMATCH' in {i['code'] for i in result['issues']}) is (not match)


@pytest.mark.parametrize('word,number,ratio,valid', [
    ('约', 11, 10, True), ('约', 11.01, 10, False),
    ('相当于', 21, 20, True), ('接近', 21.01, 20, False),
    ('超过', 10, 10, False), ('超过', 10, 10.001, True),
    ('几乎', 10, 10, False), ('几乎', 9, 10, False),
    ('几乎', 21, 20, True), ('几乎', 21.01, 20, False),
    ('相当于', 0, 0, True), ('约', 1, 0, False),
])
def test_comparison_tolerance(word, number, ratio, valid):
    assert analogy.comparison_valid(word, number, ratio) is valid


@pytest.mark.parametrize('ref', list(analogy.REFS))
@pytest.mark.parametrize('ratio', [0, .00001, .01, .094, .1, .4, .9, .95, 1, 1.05, 1.1, 1.5, 2.5, 9.5, 20.5, 820])
def test_generated_analogy_always_obeys_exact_ratio(ref, ratio):
    reference = analogy.REFS[ref]
    result = analogy.compute('A_x', {'id': 'F_x', 'value': ratio * reference['size'], 'unit': reference['unit']}, ref, reference['axes'][0])
    assert analogy.wording_valid(result['text'], ratio, ref)


def test_quote_absent_claims_missing_and_skill_delivery_warn(project):
    item = deepcopy(BASES[0])
    item['facts']['facts'][0]['source'].pop('quote')
    item['shotlist']['shots'][0].pop('claims')
    install(project['id'], item)
    result = assert_parity(project['id'])
    assert any(i['code'] == 'QUOTE_ABSENT' and i['severity'] == 'warn' for i in result['issues'])
    assert any(i['code'] == 'CLAIMS_MISSING' and i['severity'] == 'info' for i in result['issues'])
    assert result['delivery_warnings'][0]['severity'] == 'warn'


@pytest.mark.parametrize('text', ['采用箱形主梁', '承担船体分段吊装', '型号QD-450', '客户是华星集团',
                                  '用于临港工程', '位于开封', '于2025年建成', '通过认证', '排名第一'])
def test_generic_specific_claims_block(project, text):
    item = deepcopy(BASES[0])
    mutate.set_line(item['shotlist']['shots'][0], text)
    install(project['id'], item)
    assert 'UNSUPPORTED_CLAIM' in {i['code'] for i in assert_parity(project['id'])['issues']}


@pytest.mark.parametrize('support', ['F_absent', 'IMG_absent', 'F_structure', 'IMG_test'])
def test_support_existence_and_qualitative_quote(project, support):
    item = deepcopy(BASES[0])
    mutate.set_line(item['shotlist']['shots'][0], '采用箱形主梁', support)
    install(project['id'], item)
    codes = {i['code'] for i in assert_parity(project['id'])['issues']}
    assert ('UNSUPPORTED_CLAIM' in codes) is (support != 'F_structure')


@pytest.mark.parametrize('attack', ['missing', 'partial', 'unrelated', 'bare', 'append', 'generic_number'])
def test_traceability_does_not_trust_candidate_denominator(attack):
    item = deepcopy(BASES[0])
    original = accuracy_rules.traceability(item['facts'], item['shotlist'], item['assets'], [])
    shot = item['shotlist']['shots'][1]
    if attack == 'missing':
        shot.pop('claims')
    elif attack == 'partial':
        shot['claims'].pop()
    elif attack == 'unrelated':
        shot['claims'][0]['support'] = 'F_structure'
    elif attack == 'bare':
        shot['narration'] = '起重量1230吨。跨度28米。'
    elif attack == 'append':
        shot['narration'] += '已交付华星集团。'
    else:
        shot['claims'][0]['support'] = 'generic'
    result = accuracy_rules.traceability(item['facts'], item['shotlist'], item['assets'], [])
    assert result['rate'] < 1
    assert result['total'] >= original['total']


def test_qualitative_extract_patch_resolve_and_schema(project, monkeypatch, tmp_path):
    from app import llm
    from app.ingest import pdf
    text = '采用箱形主梁'
    candidate = {'id': 'F_structure', 'name': '结构形式', 'value': text, 'type': 'qualitative', 'unit': '', 'page': 1, 'quote': text}
    monkeypatch.setattr(pdf, 'extract_pages', lambda _: [{'page': 1, 'text': text}])
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: {'facts': [candidate]})
    facts = extract_facts(project['id'], 'r1', tmp_path / '说明.pdf')
    assert facts['facts'][0]['status'] == 'verified'
    assert not skill_io.schema_errors(facts, skill_io.read_json(SKILL / 'scripts/facts.schema.json'))
    assert planner._context(project['id'])['facts'][0]['type'] == 'qualitative'
    assert '类比展开预览' in planner._prompt(planner._context(project['id']))
    assert update_fact(project['id'], 'F_structure', {'value': '采用双箱主梁'})['value'] == '采用双箱主梁'
    for bad in [dict(candidate, value=1), dict(candidate, unit='m'), dict(candidate, type='quantitative')]:
        with pytest.raises(ValueError):
            ExtractedFact.model_validate(bad)


@pytest.mark.parametrize('sentence', ['起重量{{F_span}}', '采用双箱主梁且跨度{{F_span}}', '跨度{{F_span}}并能吊装船体'])
def test_traceability_rejects_wrong_label_and_grafted_assertion(sentence):
    item = deepcopy(BASES[0])
    mutate.set_line(item['shotlist']['shots'][1], sentence, 'F_span')
    result = accuracy_rules.traceability(item['facts'], item['shotlist'], item['assets'], [])
    assert result['rate'] < 1


def test_saved_baselines_and_rule_sources_match():
    for item in BASES:
        assert skill_io.read_json(mutation_dir / 'baselines' / (item['name'] + '.json')) == item
    backend = Path(accuracy_rules.__file__).read_text()
    expected = backend.replace('from .analogy import', 'from compute_analogy import').replace(
        'from .claim_rules import', 'from claim_rules import').replace('from .text import', 'from resolve_text import')
    assert (SKILL / 'scripts/accuracy_rules.py').read_text() == expected


def test_quote_sign_and_qualitative_format():
    from app.agent.text import format_value
    assert not accuracy_rules.quote_matches({'value': 8, 'unit': 'm', 'source': {'quote': '-8 m'}})
    assert accuracy_rules.quote_matches({'value': -8, 'unit': 'm', 'source': {'quote': '-8 m'}})
    assert format_value('采用箱形主梁', '') == '采用箱形主梁'


def test_highest_limit_does_not_authorize_domestic_rank(project):
    item = deepcopy(BASES[0])
    mutate.set_line(item['shotlist']['shots'][0], '国内最高可达{{F_rated_load}}', 'F_rated_load')
    install(project['id'], item)
    assert 'EXAGGERATION' in {i['code'] for i in assert_parity(project['id'])['issues']}


@pytest.mark.parametrize('text,support', [('采用箱形主梁', 'F_rated_load'), ('这台设备配有智能防摇', 'generic'), ('星海牌门机已批量投产', 'generic'), ('星海牌门机已批量投产快来看看', 'generic')])
def test_unrelated_support_and_generic_self_report_do_not_prove_truth(project, text, support):
    item = deepcopy(BASES[0])
    mutate.set_line(item['shotlist']['shots'][0], text, support)
    install(project['id'], item)
    result = assert_parity(project['id'])
    audit = accuracy_rules.traceability(item['facts'], item['shotlist'], item['assets'], result['issues'])
    assert audit['rate'] < 1
    if support != 'generic':
        assert 'UNSUPPORTED_CLAIM' in {i['code'] for i in result['issues']}


@pytest.mark.parametrize('field,text,code', [('caption', '跨度900米', 'UNSOURCED_NUMBER'), ('title', '{{F_missing}}', 'UNKNOWN_FACT')])
def test_visible_text_cannot_bypass_fact_rules(project, field, text, code):
    item = deepcopy(BASES[0])
    item['shotlist']['shots'][0]['params'][field] = text
    install(project['id'], item)
    assert code in {i['code'] for i in assert_parity(project['id'])['issues']}
