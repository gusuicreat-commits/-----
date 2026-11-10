"""离线验证背景渲染、缓存、进度和失败回退。"""
import io
import subprocess
import threading
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, events, main, storage
from app.media import blender


@pytest.fixture
def photoreal(project, monkeypatch):
    pid = project['id']
    storage.write_json(pid, 'project.json', {**project, 'render_mode': 'photoreal'})
    storage.write_json(pid, 'facts.json', {'facts': []})
    monkeypatch.setattr(blender, 'blender_executable', lambda: '/模拟工具/blender')
    for key in ('KEPU_BLENDER_PREVIEW', 'KEPU_BLENDER_ENGINE', 'KEPU_BLENDER_TIMEOUT_S'):
        monkeypatch.delenv(key, raising=False)
    return pid


def timeline():
    return {'fps': 30, 'shots': [
        {'id': 'S1', 'kind': 'title', 'params': {}, 'start': 0, 'end': 2},
        {'id': 'S2', 'kind': 'motion', 'params': {'axis': 'trolley', 'from_m': -3, 'to_m': 3}, 'start': 2, 'end': 4},
        {'id': 'S3', 'kind': 'model_orbit', 'params': {'highlight': ['girder']}, 'start': 4, 'end': 6},
        {'id': 'S4', 'kind': 'exploded', 'params': {}, 'start': 6, 'end': 7}]}


class Process:
    def __init__(self, args, *, fail=False, incomplete=False, **kwargs):
        assert isinstance(args, list) and 'shell' not in kwargs
        assert kwargs['stderr'] == subprocess.STDOUT
        self.args, self.returncode = args, 1 if fail else 0
        self.stdout = io.StringIO('启动中\n已完成第 10/60 帧\n已完成第 30/60 帧\n已完成第 60/60 帧\n')
        if not fail:
            out = Path(args[args.index('--out') + 1])
            count = int(float(args[args.index('--duration') + 1]) * int(args[args.index('--fps') + 1]))
            for i in range(1, count + 1):
                (out / f'frame_{i:05d}.jpg').write_bytes(b'frame')
            if not incomplete:
                (out / 'anchors.json').write_text('{}')
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.stdout.close()
    def wait(self, **kwargs):
        return self.returncode
    def poll(self):
        return self.returncode
    def kill(self):
        self.returncode = -9


@pytest.fixture
def processes(monkeypatch):
    calls = []
    def start(args, **kwargs):
        process = Process(args, **kwargs)
        calls.append(process)
        return process
    monkeypatch.setattr(blender.subprocess, 'Popen', start)
    return calls


def test_render_cache_and_progress(photoreal, processes):
    pid = photoreal
    data = timeline()
    before = deepcopy(data)
    backgrounds = blender.render_model_shots(pid, 'r1', data)
    assert set(backgrounds) == {'S1', 'S2', 'S3', 'S4'}
    assert data == before
    assert len(processes) == 4
    for sid, bg in backgrounds.items():
        assert (bg['count'], bg['fps'], bg['engine'], bg['width'], bg['height']) == (30 if sid == 'S4' else 60, 30, 'eevee', 1920, 1080)
        assert bg['frames'].endswith('/frame_%05d.jpg')
    log = events.read_events(pid)
    assert len([e for e in log if e['status'] == 'ok']) == 4
    assert [e['detail']['frame'] for e in log if 'frame' in e['detail']] == [30, 60] * 4
    assert blender.render_model_shots(pid, 'r2', data) == backgrounds
    assert len(processes) == 4
    assert len(list(storage.project_dir(pid).glob('renders/blender/*/done.json'))) == 4


@pytest.mark.parametrize('failure', ['exit', 'timeout', 'incomplete'])
def test_failure_warn_and_other_shots_continue(photoreal, monkeypatch, failure):
    calls = []
    def start(args, **kwargs):
        calls.append(args)
        if len(calls) == 1 and failure == 'timeout':
            raise subprocess.TimeoutExpired(args, 1)
        return Process(args, fail=len(calls) == 1 and failure == 'exit',
                       incomplete=len(calls) == 1 and failure == 'incomplete', **kwargs)
    monkeypatch.setattr(blender.subprocess, 'Popen', start)
    data = timeline()
    result = blender.render_model_shots(photoreal, 'r1', data)
    assert set(result) == {'S2', 'S3', 'S4'}
    assert all('bg' not in shot for shot in data['shots'])
    assert len(list(storage.project_dir(photoreal).glob('renders/blender/*/done.json'))) == 3
    log = events.read_events(photoreal)
    assert [e['summary'] for e in log if e['status'] == 'warn'] == ['镜头 S1 写实渲染失败，已回退网页三维']
    assert not any(e['status'] == 'error' for e in log)


def test_missing_executable_and_standard_never_spawn(photoreal, monkeypatch, processes):
    monkeypatch.setattr(blender, 'blender_executable', lambda: None)
    assert blender.render_model_shots(photoreal, 'r1', timeline()) == {}
    assert [e['status'] for e in events.read_events(photoreal)] == ['warn']
    project = storage.read_json(photoreal, 'project.json')
    project['render_mode'] = 'standard'
    storage.write_json(photoreal, 'project.json', project)
    assert blender.render_model_shots(photoreal, 'r2', timeline()) == {}
    assert len(events.read_events(photoreal)) == 1
    assert processes == []


def test_cache_key_tracks_inputs_and_scripts(tmp_path, monkeypatch):
    (tmp_path / 'blender').mkdir()
    script = tmp_path / 'blender/common.py'
    script.write_text('a')
    rig = tmp_path / 'backend/app/model3d/rig.py'
    rig.parent.mkdir(parents=True)
    rig.write_text('dimensions')
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    shot = timeline()['shots'][0]
    facts = {'facts': [{'id': 'F_span', 'value': 88, 'status': 'verified'}]}
    args = [shot, facts, 'eevee', 1920, 1080, 30]
    original = blender.cache_key(*args)
    for i, replacement in [(0, {**shot, 'params': {'title': '新标题'}}), (0, {**shot, 'kind': 'motion'}),
                           (0, {**shot, 'end': 3}), (0, {**shot, 'text_overlays': [{'text': '数字卡'}]}), (2, 'cycles'), (3, 960), (4, 540), (5, 24),
                           (1, {'facts': [{'id': 'F_span', 'value': 90, 'status': 'confirmed'}]}),
                           (1, {'facts': [{'id': 'F_span', 'value': 88, 'status': 'rejected'}]})]:
        changed = args.copy()
        changed[i] = replacement
        assert blender.cache_key(*changed) != original
    script.write_text('b')
    assert blender.cache_key(*args) != original


def test_preview_engine_duration_and_fps(photoreal, processes, monkeypatch):
    monkeypatch.setenv('KEPU_BLENDER_PREVIEW', '1')
    monkeypatch.setenv('KEPU_BLENDER_ENGINE', 'cycles')
    data = timeline()
    data['fps'] = 24
    data['shots'] = [{**data['shots'][0], 'end': 3.25}]
    bg = blender.render_model_shots(photoreal, 'r1', data)['S1']
    assert (bg['width'], bg['height'], bg['count'], bg['fps'], bg['engine']) == (960, 540, 78, 24, 'cycles')
    command = processes[0].args
    assert '--preview' in command and '--skip-video' in command
    assert command[command.index('--duration')+1] == '3.25'
    assert command[command.index('--facts')+1] == str(storage.project_dir(photoreal) / 'facts.json')


def test_settings_api(project, monkeypatch):
    client = TestClient(main.app)
    pid = project['id']
    monkeypatch.setattr(main, 'blender_executable', lambda: None)
    assert client.get(f'/api/projects/{pid}').json()['render_mode'] == 'standard'
    assert client.get(f'/api/projects/{pid}').json()['blender_available'] is False
    monkeypatch.setattr(main, 'blender_executable', lambda: '/blender')
    response = client.patch(f'/api/projects/{pid}/settings', json={'render_mode': 'photoreal'})
    assert response.status_code == 200
    assert response.json()['blender_available'] is True
    assert storage.read_json(pid, 'project.json')['render_mode'] == 'photoreal'
    assert storage.read_json(pid, 'project.json')['name'] == project['name']
    assert client.patch(f'/api/projects/{pid}/settings', json={'render_mode': 'unknown'}).status_code == 422
    assert client.patch(f'/api/projects/{pid}/settings', json={'render_mode': 'standard', 'name': '修改'}).status_code == 422
    assert client.patch(f'/api/projects/{pid}/settings', json={'render_mode': 'standard'}).json()['render_mode'] == 'standard'


@pytest.mark.parametrize('line,expected', [('已完成第 30/90 帧，单帧耗时 1 秒', (30, 90)),
    ('已完成第 0/0 帧', None), ('已完成第 90/30 帧', None), ('渲染中', None)])
def test_parse_progress(line, expected):
    assert blender.parse_progress(line) == expected


def test_timeout_kills_silent_process(monkeypatch):
    stopped = threading.Event()
    class Silent:
        def __iter__(self):
            stopped.wait(1)
            return iter(())
    class Running(Process):
        def __init__(self, *args, **kwargs):
            self.stdout, self.returncode = Silent(), None
        def kill(self):
            self.returncode = -9
            stopped.set()
        def __exit__(self, *args):
            pass
    child = Running()
    monkeypatch.setattr(blender.subprocess, 'Popen', lambda *args, **kwargs: child)
    with pytest.raises(TimeoutError):
        blender._render(['blender'], .02, lambda _: None)
    assert stopped.is_set() and child.returncode == -9


def test_executable_precedence(tmp_path, monkeypatch):
    custom = tmp_path / 'render'
    custom.write_text('')
    custom.chmod(0o755)
    monkeypatch.setenv('KEPU_BLENDER', str(custom))
    monkeypatch.setattr(blender.shutil, 'which', lambda name: '/path/blender' if name == 'blender' else None)
    assert blender.blender_executable() == str(custom)
    monkeypatch.setenv('KEPU_BLENDER', 'missing')
    assert blender.blender_executable() is None
    monkeypatch.delenv('KEPU_BLENDER')
    monkeypatch.setattr(Path, 'is_file', lambda self: False)
    assert blender.blender_executable() == '/path/blender'


@pytest.mark.parametrize('kind,overlays,expected', [
    ('title', [], (.45,.05,.95,.86)), ('title', [{'text':'数字卡'}], (.45,.05,.74,.86)),
    ('model_orbit', [], (.05,.20,.95,.86)), ('model_orbit', [{'text':'数字卡'}], (.05,.20,.74,.86)),
    ('motion', [], (.05,.20,.74,.86)), ('exploded', [], (.05,.20,.95,.86)),
    ('exploded', [{'text':'数字卡'}], (.05,.20,.74,.86)),
    ('data_card', [{'text':'数字卡'}], (.46,.05,.95,.86)),
    ('outro', [], (.40,.30,.95,.80)),
])
def test_safe_rect_and_command(photoreal, processes, kind, overlays, expected):
    item = {**timeline()['shots'][0], 'kind':kind, 'text_overlays':overlays}
    assert blender.shot_safe_rect(item) == expected
    result = blender.render_model_shots(photoreal, 'r1', {'fps':30,'shots':[item]})
    assert 'S1' in result
    command = processes[0].args
    assert tuple(map(float,command[command.index('--safe-rect')+1].split(','))) == expected


def test_analogy_routing_cache_and_look(photoreal, processes, monkeypatch):
    monkeypatch.delenv('KEPU_BLENDER_LOOK', raising=False)
    data = {'fps':30, 'shots':[], 'analogies':{}}
    for i,ref in enumerate(('building_floor','football_field','bus','person'),1):
        aid = f'A_{i}'
        data['analogies'][aid] = {'ref':ref,'ratio':17 if i == 1 else .99,'ref_size_m':3 if i == 1 else 105}
        data['shots'].append({'id':f'S{i}','kind':'analogy','params':{'analogy':aid},'start':0,'end':1})
    original = deepcopy(data)
    result = blender.render_model_shots(photoreal,'r1',data)
    assert set(result) == {'S1','S2'}
    assert data == original
    assert len(processes) == 2
    import json
    for process in processes:
        args = process.args
        assert args[args.index('--look')+1] == 'afternoon'
        payload = json.loads(args[args.index('--shot-json')+1])
        assert payload['analogy_data'] == data['analogies'][payload['params']['analogy']]
    assert blender.render_model_shots(photoreal,'r2',data) == result
    monkeypatch.setenv('KEPU_BLENDER_LOOK','dusk')
    dusk = blender.render_model_shots(photoreal,'r3',data)
    assert len(processes) == 4 and dusk['S1']['frames'] != result['S1']['frames']
    data['analogies']['A_1']['ref_size_m'] = 3.2
    changed = blender.render_model_shots(photoreal,'r4',data)
    assert len(processes) == 5 and changed['S1']['frames'] != dusk['S1']['frames']
