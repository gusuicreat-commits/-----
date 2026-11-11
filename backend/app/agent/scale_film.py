"""Deterministic, evidence-bound three-shot scale film (no language model)."""
from copy import deepcopy
import hashlib
import json
import math

from app import config, events, storage
from app.model3d import parametric, rig
from .analogy import compute
from .director import _selector

GEOMETRY = {'F_girder_length', 'F_overall_height', 'F_span', 'F_lift_height', 'F_girder_height', 'F_wheel_count'}


def profile():
    book = json.loads((config.ROOT / 'skills/industrial-explainer-storyboard/references/director-recipes.json').read_text())
    return book['recipes']['scale']['render_profiles']['scale_film']


def settings(project):
    target = project.get('target_s', 15)
    if not isinstance(target, (int, float)) or not 15 <= target <= 30:
        raise ValueError('尺度短片目标时长必须为15–30秒')
    if not math.isclose(target * 30, round(target * 30), abs_tol=1e-6, rel_tol=0):
        raise ValueError('尺度短片目标时长必须对齐30fps帧网格（1/30秒）')
    if project.get('director_recipe', 'off') not in {'scale', 'auto'}:
        raise ValueError('尺度短片需选择 scale 或 auto 讲解配方')
    if (project.get('model') or {}).get('kind', 'parametric') != 'parametric':
        raise ValueError('尺度短片仅支持参数化模型，不支持STEP')
    return target


def inputs(pid):
    project = storage.read_json(pid, 'project.json')
    target = settings(project)
    facts = storage.read_json(pid, 'facts.json', {'facts': []})['facts']
    selector = _selector()
    # Use precisely the same semantic/evidence gates as the portable skill.
    namespace = selector.__globals__
    accepted = namespace['confirmed_facts'](facts)
    length = next((f for f in accepted if namespace['scale_axis'](f) == 'length'
                   and f.get('unit') in {'m', 'mm'} and namespace['positive'](f.get('value'))), None)
    lengths = [f for f in accepted if namespace['scale_axis'](f) == 'length' and f.get('unit') in {'m', 'mm'} and namespace['positive'](f.get('value'))]
    if len({f['value'] / (1000 if f['unit'] == 'mm' else 1) for f in lengths}) > 1:
        raise ValueError('主梁总长语义别名存在冲突，不能自行选值')
    if length is None:
        raise ValueError('尺度短片缺无冲突、有出处的确认主梁总长；整机高度、跨度不能替代')
    # Conflicting confirmed geometry is a stop, rather than silently falling back to defaults.
    accepted_ids = {f['id'] for f in accepted}
    for f in facts:
        if f.get('id') in GEOMETRY and f.get('status') in {'confirmed', 'verified'} and f['id'] not in accepted_ids:
            raise ValueError('几何参数出处缺失或冲突：' + f['id'])
    values, normalized = {}, []
    for f in accepted:
        canonical = 'F_girder_length' if f is length else f['id']
        if canonical not in GEOMETRY:
            continue
        if canonical == 'F_girder_length' and namespace['scale_axis'](f) != 'length':
            raise ValueError('主梁总长ID与名称/key语义冲突')
        if canonical == 'F_overall_height' and namespace['scale_axis'](f) != 'height':
            raise ValueError('整机高度ID与名称/key语义冲突')
        value = f.get('value')
        if not namespace['positive'](value):
            raise ValueError('几何参数必须为正数：' + f['id'])
        if canonical != 'F_wheel_count':
            if f.get('unit') not in {'m', 'mm'}:
                raise ValueError('几何参数单位必须为m或mm：' + f['id'])
            value = value / 1000 if f['unit'] == 'mm' else value
        values[canonical] = value
        normalized.append({**deepcopy(f), 'id': canonical, 'value': value,
                           'unit': 'm' if canonical != 'F_wheel_count' else f.get('unit', ''),
                           'original_id': f['id'], 'original_value': f['value'], 'original_unit': f.get('unit', '')})
    if 'F_overall_height' not in values:
        raise ValueError('尺度短片需确认整机高度（m/mm），不使用默认高度')
    dims = rig._dimensions(values)
    if dims['F_span'] + 3.2 > dims['F_girder_length'] or dims['F_span'] < 12:
        raise ValueError('跨度与主梁总长不相容；请核实原始事实，不自动改数')
    if dims['F_lift_height'] > dims['F_overall_height']:
        raise ValueError('起升高度大于整机高度，请核实原始事实')
    return project, target, length, values, {'facts': normalized}


def fingerprint(pid):
    project, target, length, values, normalized = inputs(pid)
    payload = {'brief': project.get('brief', ''), 'director_recipe': project.get('director_recipe'), 'target_s': target, 'length': length, 'values': values, 'normalized': normalized, 'profile': profile()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def compile_plan(pid, run):
    project, target, length, values, normalized = inputs(pid)
    render_profile = profile()
    aid = f"A_{length['id'].removeprefix('F_')}_football_field"
    analogy = compute(aid, length, 'football_field', 'length')
    templates = render_profile['shots']
    shots = []
    target_frames = round(target * 30)
    consumed_frames = 0
    weight_total = sum(template['weight'] for template in templates)
    for index, template in enumerate(templates, 1):
        frames = round(target_frames * template['weight'] / weight_total) if index < len(templates) else target_frames - consumed_frames
        consumed_frames += frames
        duration = frames / 30
        narration = template['narration'].replace('$F', '{{' + length['id'] + '}}').replace('$A', '{{' + aid + '}}')
        shots.append({'id': f'S{index}', 'kind': template['kind'], 'source': 'model', 'duration_s': duration,
                      'narration': narration, 'claims': [{'text': narration, 'support': length['id'] if '$F' in template['narration'] or '$A' in template['narration'] else 'generic'}],
                      'fact_refs': [length['id']], 'asset_refs': [], 'analogy_refs': [aid] if template['role'] == 'compare' else [],
                      'params': {'analogy': aid} if template['role'] == 'compare' else {'from_deg': -24, 'to_deg': -12, 'elevation_deg': 10, 'distance': 1.35, 'highlight': ['girder']},
                      'review': {'status': 'pending', 'note': ''}})
    previous = storage.read_json(pid, 'shotlist.json', {})
    locked = [s for s in previous.get('shots', []) if s.get('human_edited') or s.get('review', {}).get('status') == 'approved']
    old_fingerprint = previous.get('scale_film', {}).get('input_hash')
    current_hash = fingerprint(pid)
    for original in locked:
        match = next((s for s in shots if s['id'] == original.get('id')), None)
        creative = ('kind', 'source', 'duration_s', 'narration', 'claims', 'fact_refs', 'asset_refs', 'analogy_refs', 'params')
        if not match or old_fingerprint != current_hash or any(match.get(k) != original.get(k) for k in creative):
            raise ValueError('固定三镜尺度模板无法完整保留人工镜头；请明确解除或调整原镜头后重跑：' + str(original.get('id')))
        shots[shots.index(match)] = deepcopy(original)
    with events.tool_call(pid, run, 'plan', 'director.scale_film', '正在按尺度短片模板编译三镜分镜（不调用大模型）') as call:
        # Rebuild even from plan: facts edits must never leave the old geometry behind.
        temporary = storage.project_dir(pid) / 'model/scale-film-build.glb'
        try:
            result = parametric.build_parametric(values, temporary)
            if project.get('director_recipe') == 'auto':
                brief = project.get('brief', '').lower()
                if any(word in brief for word in ('多高', '高度', 'height')):
                    raise ValueError('auto未选择可支持的纯主梁长度主题；当前模式不替代高度讲解，请明确选择scale或更换模式')
                selected = _selector()({'brief': project.get('brief', ''),
                                        'facts': storage.read_json(pid, 'facts.json')['facts'],
                                        'model': {'nodes': result['nodes'], 'rig': {'axes': {}}}}, 'auto', target)
                axes = [r['axis'] for s in selected.get('sequence', []) for r in s.get('analogy_requests', [])]
                if selected.get('status') != 'selected' or selected.get('recipe') != 'scale' or axes != ['length']:
                    raise ValueError('auto未选择主梁长度尺度主题；请明确选择scale或补齐所要求主题证据，不自动换题')
            temporary.replace(storage.project_dir(pid) / 'model/crane.glb')
        finally:
            temporary.unlink(missing_ok=True)
        motion = rig.build_rig(values, result['bbox_m'], 'parametric', result['nodes'])
        storage.write_json(pid, 'model/rig.json', motion)
        model = {'kind': 'parametric', 'glb': 'model/crane.glb', 'assumed': result['assumed'],
                 'detail_assumptions': result.get('detail_assumptions', []), 'derived_from': list(values),
                 'dims_check': rig.dims_check(result['bbox_m'], values), 'scale_film_input_hash': current_hash}
        project['model'] = model
        storage.write_json(pid, 'project.json', project)
        storage.write_json(pid, 'model/scale-film-facts.json', normalized)
        plan = {'version': 1, 'title': '工程的尺度', 'fps': 30, 'width': 1920, 'height': 1080,
                'shots': shots, 'analogies': [analogy], 'notes': ['固定三镜模板；附属几何为参数化示意，非真实测绘'],
                'scale_film': {'input_hash': current_hash, 'roles': [s['role'] for s in templates],
                               'normalized_facts': 'model/scale-film-facts.json', 'length_fact': length['id'],
                               'shot_hash': shot_hash(shots)}}
        storage.write_json(pid, 'shotlist.json', plan)
        call.ok('尺度短片三镜模板编译完成；默认几何：' + ('、'.join(model['assumed']) or '无'))
    return plan


def shot_hash(shots):
    fields = ('id', 'kind', 'source', 'duration_s', 'narration', 'claims', 'fact_refs', 'asset_refs', 'analogy_refs', 'params')
    return hashlib.sha256(json.dumps([{k: s.get(k) for k in fields} for s in shots], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def assert_current(pid):
    plan = storage.read_json(pid, 'shotlist.json', {})
    if plan.get('scale_film', {}).get('input_hash') != fingerprint(pid):
        raise ValueError('尺度短片参数或时长已变化，请从plan重新生成模型和分镜')
    if plan.get('scale_film', {}).get('shot_hash') != shot_hash(plan.get('shots', [])):
        raise ValueError('固定尺度模板镜头已修改，请明确调整后从plan重新生成，不忽略人工创作')
    if storage.read_json(pid, 'model/scale-film-facts.json') != inputs(pid)[4]:
        raise ValueError('归一化渲染事实已变化，请从plan重建')
    if (storage.read_json(pid, 'project.json').get('model') or {}).get('scale_film_input_hash') != fingerprint(pid):
        raise ValueError('尺度短片模型已变化，请从plan重建')
    return plan


def source_hash(pid):
    plan = assert_current(pid)
    directory = storage.project_dir(pid)
    model = storage.read_json(pid, 'project.json')['model']
    glb = storage.safe_path(directory, model['glb'])
    digest = hashlib.sha256()
    digest.update(fingerprint(pid).encode())
    digest.update(shot_hash(plan['shots']).encode())
    digest.update(glb.read_bytes())
    for shot in plan['shots']:
        for suffix in ('.mp3', '.words.json'):
            path = storage.safe_path(directory / 'tts', shot['id'] + suffix)
            if path.is_file():
                digest.update(path.read_bytes())
    for path in sorted((config.ROOT / 'blender').glob('*.py')):
        digest.update(path.name.encode()); digest.update(path.read_bytes())
    for relative in ('backend/app/media/scale_film.py', 'backend/app/model3d/rig.py',
                     'backend/app/agent/timeline.py', 'backend/app/media/tts.py'):
        path = config.ROOT / relative
        digest.update(relative.encode()); digest.update(path.read_bytes())
    return digest.hexdigest()


def ready(pid):
    try:
        project = storage.read_json(pid, 'project.json')
        if project.get('render_mode') != 'scale_film':
            return False
        run = storage.read_json(pid, 'run.json', {})
        built = storage.read_json(pid, 'timeline.json', {})
        return (run.get('state') == 'done' and built.get('rendered_run') == run.get('run')
                and (storage.project_dir(pid) / 'renders/final.mp4').is_file()
                and built.get('rendered_source_hash') == source_hash(pid)
                and built.get('rendered_video_hash') == hashlib.sha256((storage.project_dir(pid) / 'renders/final.mp4').read_bytes()).hexdigest())
    except (KeyError, ValueError, OSError, TypeError):
        return False


def assert_final(pid, run):
    built = storage.read_json(pid, 'timeline.json', {})
    final = storage.project_dir(pid) / 'renders/final.mp4'
    if (built.get('rendered_run') != run or not final.is_file()
            or built.get('rendered_source_hash') != source_hash(pid)
            or built.get('rendered_video_hash') != hashlib.sha256(final.read_bytes()).hexdigest()):
        raise ValueError('本次尺度短片尚无与当前参数、台词、模型匹配的成功合成记录，请从render或更早阶段重跑，不能仅补报告标完成')
