from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app import config, llm, main, storage
from app.agent import planner, scale_film, timeline, orchestrator, validator, qa
from app.media import scale_film as media, tts


def make_project(project, length=104, unit='m', doc='工厂参数.pdf'):
    pid = project['id']
    storage.write_json(pid, 'project.json', {**project, 'render_mode': 'scale_film', 'target_s': 15, 'director_recipe': 'scale'})
    facts = [{'id': fid, 'name': name, 'value': value, 'unit': unit, 'status': 'confirmed',
              'source': {'doc': doc, 'page': 3, 'quote': f'{name} {value} {unit}'}}
             for fid, name, value in [('F_girder_length', '主梁总长', length), ('F_overall_height', '整机高度', 51000 if unit == 'mm' else 51)]]
    storage.write_json(pid, 'facts.json', {'facts': facts})
    return pid


def mock_model(monkeypatch):
    seen = []
    def build(values, out):
        seen.append(deepcopy(values))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(json.dumps(values).encode())
        dims = scale_film.rig._dimensions(values)
        return {'bbox_m': {'x': dims['F_girder_length'], 'y': dims['F_overall_height'], 'z': 20},
                'nodes': ['crane', 'girder'], 'assumed': [k for k in dims if k not in values]}
    monkeypatch.setattr(scale_film.parametric, 'build_parametric', build)
    return seen


@pytest.mark.parametrize('length,unit,doc,expected', [(104, 'm', '原厂参数.pdf', 104), (84000, 'mm', '另一份确认资料.pdf', 84)])
def test_compile_normalizes_rebuilds_and_keeps_original_source(project, monkeypatch, length, unit, doc, expected):
    pid = make_project(project, length, unit, doc)
    seen = mock_model(monkeypatch)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **k: pytest.fail('模板不能调用LLM'))
    result = planner.plan(pid, 'r1')
    assert [s['duration_s'] for s in result['shots']] == [4, 5, 6]
    assert result['analogies'][0]['ratio'] == round(expected / 105, 3)
    assert seen[-1]['F_girder_length'] == expected
    normalized = storage.read_json(pid, 'model/scale-film-facts.json')['facts'][0]
    assert normalized['value'] == expected and normalized['unit'] == 'm'
    assert normalized['source']['doc'] == doc and normalized['original_value'] == length
    assert storage.read_json(pid, 'facts.json')['facts'][0]['unit'] == unit
    model = storage.read_json(pid, 'project.json')['model']
    assert 'F_span' in model['assumed'] and 'F_girder_length' not in model['assumed']
    assert all(s['claims'] for s in result['shots'])
    assert not [i for i in validator.validate(pid, 'r1')['issues'] if i['severity'] == 'block']
    facts = storage.read_json(pid, 'facts.json')
    facts['facts'][0]['value'] = length * .9
    storage.write_json(pid, 'facts.json', facts)
    with pytest.raises(ValueError, match='变化'):
        scale_film.assert_current(pid)
    planner.plan(pid, 'r2')
    assert seen[-1]['F_girder_length'] == pytest.approx(expected * .9)


@pytest.mark.parametrize('bad', ['missing', 'conflict', 'source', 'step', 'span', 'height', 'unit'])
def test_missing_or_incompatible_evidence_stops_before_model_or_llm(project, monkeypatch, bad):
    pid = make_project(project)
    facts = storage.read_json(pid, 'facts.json')
    if bad == 'missing':
        facts['facts'][0]['status'] = 'needs_review'
    elif bad == 'conflict':
        facts['facts'].append({**facts['facts'][0], 'value': 120})
    elif bad == 'source':
        facts['facts'][0]['source'] = {}
    elif bad == 'step':
        storage.write_json(pid, 'project.json', {**storage.read_json(pid, 'project.json'), 'model': {'kind': 'step'}})
    elif bad == 'span':
        facts['facts'].append({**facts['facts'][0], 'id': 'F_span', 'name': '跨度', 'value': 120})
    elif bad == 'height':
        facts['facts'][1]['status'] = 'needs_review'
    else:
        facts['facts'][0]['unit'] = 't'
    storage.write_json(pid, 'facts.json', facts)
    monkeypatch.setattr(scale_film.parametric, 'build_parametric', lambda *a: pytest.fail('缺证据不重建'))
    with pytest.raises(ValueError):
        planner.plan(pid, 'r1')
    assert not (storage.project_dir(pid) / 'shotlist.json').exists()


def test_human_protection_keeps_fields_or_stops_without_overwrite(project, monkeypatch):
    pid = make_project(project)
    mock_model(monkeypatch)
    result = planner.plan(pid, 'r1')
    result['shots'][1]['review'] = {'status': 'approved', 'note': '已确认'}
    result['shots'][1]['custom'] = ['保留']
    storage.write_json(pid, 'shotlist.json', result)
    assert planner.plan(pid, 'r2')['shots'][1] == result['shots'][1]
    result['shots'][1]['narration'] = '人工另写台词'
    result['shots'][1]['human_edited'] = True
    storage.write_json(pid, 'shotlist.json', result)
    with pytest.raises(ValueError, match='人工镜头'):
        planner.plan(pid, 'r3')
    assert storage.read_json(pid, 'shotlist.json') == result


def built_timeline(pid):
    plan = storage.read_json(pid, 'shotlist.json')
    facts = {f['id']: f for f in storage.read_json(pid, 'facts.json')['facts']}
    shots = []
    position = 0
    for s in plan['shots']:
        shots.append({**s, 'start': position, 'end': position + s['duration_s'], 'badge': '三维模型渲染 · 参数化重建'})
        position += s['duration_s']
    return {'shots': shots, 'facts': facts, 'analogies': {a['id']: a for a in plan['analogies']},
            'duration_s': position, 'fps': 30, 'width': 1920, 'height': 1080, 'model': {}, 'assets': {}, 'music': None}


def mock_render(monkeypatch, length):
    calls = []
    monkeypatch.setattr(media.blender, 'blender_executable', lambda: '/test/blender')
    monkeypatch.setattr(media.tts, 'probe_duration', lambda _: 15)
    def render(args, timeout, progress):
        calls.append(args)
        out = Path(args[args.index('--out') + 1])
        cfg = json.loads(Path(args[args.index('--config') + 1]).read_text())
        assert [s['role'] for s in cfg['shots']] == ['detail', 'hero', 'compare']
        (out / 'noaudio.mp4').write_bytes(b'fake-render-output')
        (out / 'manifest.json').write_text('{}')
        projection = {'field': {'left': .2, 'right': .8, 'top': .2, 'bottom': .5},
                      'girder': {'left': .2, 'right': .2 + .6 * length / 105, 'top': .6, 'bottom': .7},
                      'length_m': length, 'reference_length_m': 105, 'reference_width_m': 68}
        (out / 'projection.json').write_text(json.dumps(projection))
    monkeypatch.setattr(media.blender, '_render', render)
    return calls


def test_render_cache_hash_and_artifact_integrity_and_dynamic_titles(project, monkeypatch, tmp_path):
    pid = make_project(project, 84, doc='当前厂方确认.pdf')
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    built = built_timeline(pid)
    # Use isolated script tree; cache must change if renderer dependencies change.
    root = tmp_path / 'root'
    (root / 'blender').mkdir(parents=True)
    (root / 'blender/scale_film.py').write_text('# renderer version one')
    (root / 'backend/app/model3d').mkdir(parents=True)
    (root / 'backend/app/model3d/rig.py').write_text('# dimensions')
    # director still reads real skill profile while media computes script hashes in test tree.
    monkeypatch.setattr(media, 'config', type('Config', (), {'ROOT': root}))
    calls = mock_render(monkeypatch, 84)
    first = media.render(pid, 'r1', built)
    media.render(pid, 'r2', built)
    assert len(calls) == 1
    (first / 'noaudio.mp4').write_bytes(b'corrupt')
    media.render(pid, 'r3', built)
    assert len(calls) == 2
    (root / 'blender/scale_film.py').write_text('# renderer version two')
    second = media.render(pid, 'r4', built)
    assert first != second and len(calls) == 3
    projection = json.loads((second / 'projection.json').read_text())
    ass = media.titles(pid, built, projection)
    assert '当前厂方确认.pdf' in ass and '84' in ass and '104 m' not in ass and '示例参数' not in ass
    assert built['analogies'][next(iter(built['analogies']))]['text'] in ass
    changed = deepcopy(built)
    changed['facts']['F_girder_length']['source']['doc'] = '新来源.pdf'
    assert media.cache_key(pid, changed) != media.cache_key(pid, built)
    old_key = media.cache_key(pid, built)
    normalized = storage.read_json(pid, 'model/scale-film-facts.json')
    normalized['facts'][0]['value'] = 83
    storage.write_json(pid, 'model/scale-film-facts.json', normalized)
    assert media.cache_key(pid, built) != old_key


def test_render_failure_does_not_publish_or_report_success(project, monkeypatch, tmp_path):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    monkeypatch.setattr(media.blender, 'blender_executable', lambda: '/test/blender')
    monkeypatch.setattr(media, 'cache_key', lambda *a: 'failure-cache')
    def fail(*args):
        raise RuntimeError('renderer stopped')
    monkeypatch.setattr(media.blender, '_render', fail)
    with pytest.raises(RuntimeError, match='renderer stopped'):
        media.render(pid, 'r1', built_timeline(pid))
    assert not (storage.project_dir(pid) / 'renders/video_noaudio.mp4').exists()
    assert not (storage.project_dir(pid) / 'renders/scale-film/failure-cache/done.json').exists()


def test_scale_timeline_refuses_to_extend_for_long_tts(project, monkeypatch):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    storage.write_json(pid, 'tts/S1.words.json', {'duration_s': 5, 'words': [], 'engine': 'test'})
    with pytest.raises(ValueError, match='配音超出'):
        timeline.build_timeline(pid)


def test_crossfield_settings_atomic_and_compatible(project, monkeypatch):
    monkeypatch.setattr(main, 'blender_executable', lambda: None)
    client = TestClient(main.app)
    url = f"/api/projects/{project['id']}/settings"
    for bad in [{'render_mode': 'scale_film'}, {'render_mode': 'scale_film', 'director_recipe': 'motion', 'target_s': 15},
                {'render_mode': 'scale_film', 'director_recipe': 'scale', 'target_s': 31}]:
        assert client.patch(url, json=bad).status_code == 422
        assert storage.read_json(project['id'], 'project.json').get('render_mode') != 'scale_film'
    assert client.patch(url, json={'render_mode': 'scale_film', 'director_recipe': 'scale', 'target_s': 15}).status_code == 200
    assert client.patch(url, json={'target_s': 14}).status_code == 422
    assert client.patch(url, json={'director_recipe': 'off'}).status_code == 422
    assert client.patch(url, json={'render_mode': 'standard', 'target_s': 45, 'director_recipe': 'off'}).status_code == 200


def test_full_run_existing_old_plan_still_compiles_scale_template(project, monkeypatch):
    pid = make_project(project)
    storage.write_json(pid, 'shotlist.json', {'shots': [{'id': 'old'}]})
    called = []
    def plan(*a):
        called.append('plan')
        raise RuntimeError('stop after plan proves routing')
    monkeypatch.setattr(planner, 'plan', plan)
    state = {'run': 'test', 'stage_durations_s': {}, 'state': 'running'}
    orchestrator._execute(pid, state, from_stage=None, force=False, base_url='http://unused')
    assert called == ['plan'] and state['state'] == 'error'


def test_scale_qa_extracts_actual_final_video_and_reports_missing_provider(project, monkeypatch):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    built = built_timeline(pid)
    storage.write_json(pid, 'timeline.json', built)
    video = storage.project_dir(pid) / 'renders/final.mp4'
    video.write_bytes(b'test')
    calls = []
    def run(args, **kw):
        calls.append(args)
        Path(args[-1]).write_bytes(b'png')
    monkeypatch.setattr(qa.subprocess, 'run', run)
    monkeypatch.setattr(llm, 'complete_json', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('no provider')))
    result = qa.visual_qa(pid, 'r1', base_url='http://unused')
    assert 'error' in result
    assert len(calls) == 3 and all(str(video) in a and 'node' not in a for a in calls)
    assert any(i['severity'] == 'warn' for i in storage.read_json(pid, 'issues.json')['issues'])


@pytest.mark.parametrize('brief', ['小车到底怎么运动？', '整机究竟多高？'])
def test_auto_must_select_supported_length_subject(project, monkeypatch, brief):
    pid = make_project(project)
    mock_model(monkeypatch)
    p = storage.read_json(pid, 'project.json')
    storage.write_json(pid, 'project.json', {**p, 'director_recipe': 'auto', 'brief': brief})
    if '多高' in brief:
        facts = storage.read_json(pid, 'facts.json')
        facts['facts'].reverse()  # shared auto selector actually selects height.
        storage.write_json(pid, 'facts.json', facts)
    with pytest.raises(ValueError, match='auto未选择'):
        planner.plan(pid, 'r1')
    assert not (storage.project_dir(pid) / 'shotlist.json').exists()
    assert not (storage.project_dir(pid) / 'model/scale-film-build.glb').exists()


@pytest.mark.parametrize('bad', ['height_semantics', 'alias_conflict'])
def test_geometry_semantic_conflicts_rejected(project, monkeypatch, bad):
    pid = make_project(project)
    facts = storage.read_json(pid, 'facts.json')
    if bad == 'height_semantics':
        facts['facts'][1]['name'] = '主梁高度'
    else:
        facts['facts'].append({**facts['facts'][0], 'id': 'F_beam', 'name': '主梁长度', 'value': 88})
    storage.write_json(pid, 'facts.json', facts)
    with pytest.raises(ValueError, match='冲突'):
        planner.plan(pid, 'r1')


def test_real_parametric_model_uses_current_normalized_length(project):
    pid = make_project(project, 84000, 'mm')
    planner.plan(pid, 'r1')
    model = storage.read_json(pid, 'project.json')['model']
    assert next(c['model_value'] for c in model['dims_check'] if c['fact'] == 'F_girder_length') == pytest.approx(84)
    assert (storage.project_dir(pid) / 'model/crane.glb').stat().st_size > 0


@pytest.mark.parametrize('mutation', ['facts', 'settings', 'narration', 'params', 'model', 'running'])
def test_final_readiness_rejects_stale_inputs_or_unfinished_run(project, monkeypatch, mutation):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    storage.write_json(pid, 'run.json', {'state': 'done', 'run': 'r1'})
    import hashlib
    storage.write_json(pid, 'timeline.json', {'rendered_source_hash': scale_film.source_hash(pid), 'rendered_run': 'r1', 'rendered_video_hash': hashlib.sha256(b'completed').hexdigest()})
    (storage.project_dir(pid) / 'renders/final.mp4').write_bytes(b'completed')
    assert scale_film.ready(pid)
    if mutation == 'facts':
        facts = storage.read_json(pid, 'facts.json')
        facts['facts'][0]['value'] = 88
        storage.write_json(pid, 'facts.json', facts)
    elif mutation == 'settings':
        p = storage.read_json(pid, 'project.json')
        p['target_s'] = 20
        storage.write_json(pid, 'project.json', p)
    elif mutation in {'narration', 'params'}:
        plan = storage.read_json(pid, 'shotlist.json')
        if mutation == 'narration':
            plan['shots'][0]['narration'] = '新台词'
        else:
            plan['shots'][0]['params']['distance'] = 2
        storage.write_json(pid, 'shotlist.json', plan)
    elif mutation == 'model':
        (storage.project_dir(pid) / 'model/crane.glb').write_bytes(b'new model')
    else:
        storage.write_json(pid, 'run.json', {'state': 'running', 'run': 'r2'})
    assert not scale_film.ready(pid)
    monkeypatch.setattr(main, 'blender_executable', lambda: None)
    assert TestClient(main.app).get(f'/api/projects/{pid}').json()['scale_film_ready'] is False


def test_manual_pending_edit_marks_human_and_blocks_template_overwrite(project, monkeypatch):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    client = TestClient(main.app)
    response = client.patch(f'/api/projects/{pid}/shots/S1', json={'narration': '人工台词'})
    assert response.status_code == 200
    assert response.json()['human_edited'] is True
    assert response.json()['review']['status'] == 'pending'
    with pytest.raises(ValueError, match='人工镜头'):
        planner.plan(pid, 'r2')
    assert storage.read_json(pid, 'shotlist.json')['shots'][0]['narration'] == '人工台词'


@pytest.mark.parametrize('from_stage', ['qa', 'report'])
def test_late_stage_cannot_make_old_or_failed_scale_film_done(project, monkeypatch, from_stage):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'old')
    (storage.project_dir(pid) / 'renders/final.mp4').write_bytes(b'old failed output')
    storage.write_json(pid, 'timeline.json', {'rendered_run': 'old', 'rendered_source_hash': 'stale'})
    state = {'run': 'new', 'stage_durations_s': {}, 'state': 'running'}
    monkeypatch.setattr(qa, 'visual_qa', lambda *a, **kw: pytest.fail('stale output cannot reach QA'))
    orchestrator._execute(pid, state, from_stage=from_stage, force=True, base_url='http://unused')
    assert state['state'] == 'error' and not scale_film.ready(pid)


def test_timeline_rejects_old_voice_even_when_its_duration_fits(project, monkeypatch):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    storage.write_json(pid, 'tts/S1.words.json', {'duration_s': 1, 'words': [], 'engine': 'test', 'spoken_text': 'old text'})
    with pytest.raises(ValueError, match='配音与当前台词不匹配'):
        timeline.build_timeline(pid)



def test_scale_mux_records_current_source_and_publishes_final(project, monkeypatch):
    pid = make_project(project, doc='实际确认来源.pdf')
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    built = built_timeline(pid)
    storage.write_json(pid, 'timeline.json', built)
    directory = storage.project_dir(pid)
    (directory / 'renders/video_noaudio.mp4').write_bytes(b'raw')
    (directory / 'renders/narration.wav').write_bytes(b'audio')
    monkeypatch.setattr(media, 'cache_key', lambda *a: 'current')
    storage.write_json(pid, 'renders/scale-film-render.json', {'key': 'current', 'projection': {
        'length_m': 104, 'field': {'left': .2, 'right': .8, 'top': .1, 'bottom': .5},
        'girder': {'left': .2, 'right': .8, 'top': .6, 'bottom': .7}}})
    monkeypatch.setattr(media, 'sound_bed', lambda path, *a: path.write_bytes(b'bed'))
    monkeypatch.setattr(media.tts, 'probe_duration', lambda *a: 15)
    commands = []
    def ffmpeg(args, **kw):
        commands.append(args)
        Path(args[-1]).write_bytes(b'finished-current-video')
    monkeypatch.setattr(media.subprocess, 'run', ffmpeg)
    media.mux(pid, 'r1')
    assert commands and 'ass=scale-film.ass' in commands[0]
    final_timeline = storage.read_json(pid, 'timeline.json')
    assert final_timeline['style'] == 'scale_film'
    assert final_timeline['rendered_source_hash'] == scale_film.source_hash(pid)
    storage.write_json(pid, 'run.json', {'state': 'done', 'run': 'r1'})
    assert scale_film.ready(pid)
    (directory / 'renders/final.mp4').write_bytes(b'corrupted-or-old-video')
    assert not scale_film.ready(pid)



@pytest.mark.parametrize('target', [20, 17, 15.1])
def test_frame_grid_plan_timeline_and_renderer_config_are_compatible(project, monkeypatch, target):
    import importlib.util
    from app.agent.text import resolve
    spec = importlib.util.spec_from_file_location('scale_film_frame_contract', config.ROOT / 'blender/scale_film_scene.py')
    scene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scene)
    pid = make_project(project)
    p = storage.read_json(pid, 'project.json')
    storage.write_json(pid, 'project.json', {**p, 'target_s': target})
    mock_model(monkeypatch)
    plan = planner.plan(pid, 'r1')
    facts = {f['id']: f for f in storage.read_json(pid, 'facts.json')['facts']}
    analogies = {a['id']: a for a in plan['analogies']}
    for shot in plan['shots']:
        storage.write_json(pid, f"tts/{shot['id']}.words.json", {
            'duration_s': 1, 'words': [], 'engine': 'test',
            'spoken_text': resolve(shot['narration'], facts, analogies)})
    monkeypatch.setattr(timeline.compose, 'select_music', lambda pid: None)
    monkeypatch.setattr(timeline.subprocess, 'run', lambda *a, **k: None)
    built = timeline.build_timeline(pid)
    calls = mock_render(monkeypatch, 104)
    monkeypatch.setattr(media, 'cache_key', lambda *a: 'frame-grid')
    monkeypatch.setattr(media.tts, 'probe_duration', lambda _: target)
    original_render = media.blender._render
    def render(args, timeout, progress):
        cfg = json.loads(Path(args[args.index('--config') + 1]).read_text())
        scene.validate_config(cfg)  # Run the real renderer validator without Blender/GPU.
        assert cfg['shots'][-1]['end'] == pytest.approx(target)
        assert sum(round((s['end'] - s['start']) * 30) for s in cfg['shots']) == round(target * 30)
        original_render(args, timeout, progress)
    monkeypatch.setattr(media.blender, '_render', render)
    media.render(pid, 'r1', built)
    assert len(calls) == 1
    assert built['duration_s'] == pytest.approx(target)
    assert all(abs(s['duration_s'] * 30 - round(s['duration_s'] * 30)) < 1e-6 for s in plan['shots'])


def test_settings_rejects_subframe_target_without_mutating_project(project, monkeypatch):
    monkeypatch.setattr(main, 'blender_executable', lambda: None)
    pid = project['id']
    response = TestClient(main.app).patch(f'/api/projects/{pid}/settings', json={
        'render_mode': 'scale_film', 'director_recipe': 'scale', 'target_s': 15.01})
    assert response.status_code == 422
    assert storage.read_json(pid, 'project.json').get('render_mode') != 'scale_film'


@pytest.mark.parametrize('relative', ['backend/app/media/scale_film.py', 'backend/app/model3d/rig.py',
                                    'backend/app/agent/timeline.py', 'backend/app/media/tts.py'])
def test_source_hash_invalidates_when_generation_algorithm_changes(project, monkeypatch, tmp_path, relative):
    pid = make_project(project)
    mock_model(monkeypatch)
    planner.plan(pid, 'r1')
    actual_root = config.ROOT
    root = tmp_path / 'isolated-source-tree'
    dependencies = ['backend/app/media/scale_film.py', 'backend/app/model3d/rig.py',
                    'backend/app/agent/timeline.py', 'backend/app/media/tts.py',
                    'skills/industrial-explainer-storyboard/references/director-recipes.json']
    for name in dependencies:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((actual_root / name).read_bytes())
    monkeypatch.setattr(scale_film, 'config', type('Config', (), {'ROOT': root}))
    before = scale_film.source_hash(pid)
    with (root / relative).open('ab') as out:
        out.write(b'\n# algorithm changed in isolated test\n')
    assert scale_film.source_hash(pid) != before
