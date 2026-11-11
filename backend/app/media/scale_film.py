"""Dedicated scale-film render/cache and dynamic editorial finishing; never falls back."""
import array
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import wave

from app import config, events, storage
from app.agent import scale_film as director, validator
from app.agent.text import format_value
from . import blender, tts


def cache_key(pid, built):
    script = config.ROOT / 'blender/scale_film.py'
    if not script.is_file():
        raise ValueError('尺度短片渲染脚本缺失')
    digest = hashlib.sha256()
    # Include dependencies too, not only the wrapper entrypoint.
    for path in sorted((config.ROOT / 'blender').glob('*.py')):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    digest.update((config.ROOT / 'backend/app/model3d/rig.py').read_bytes())
    payload = {'facts': storage.read_json(pid, 'model/scale-film-facts.json'),
               'timeline': {k: built[k] for k in ('shots', 'duration_s', 'facts', 'analogies', 'fps', 'width', 'height')},
               'plan': storage.read_json(pid, 'shotlist.json'),
               'renderer': blender.blender_executable()}
    digest.update(json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False).encode())
    return digest.hexdigest()


def check_projection(data, length):
    for key in ('field', 'girder'):
        rect = data.get(key, {})
        for name in ('left', 'right', 'top', 'bottom'):
            value = rect.get(name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError('尺度短片投影无效：' + key)
        if not rect['left'] < rect['right'] or not rect['top'] < rect['bottom']:
            raise ValueError('尺度短片投影为空')
    if not math.isclose(data.get('length_m', 0), length, rel_tol=1e-6) or data.get('reference_length_m') != 105 or data.get('reference_width_m') != 68:
        raise ValueError('尺度短片投影参数与确认事实不符')
    ratio = (data['girder']['right'] - data['girder']['left']) / (data['field']['right'] - data['field']['left'])
    if not math.isclose(ratio, length / 105, rel_tol=.01):
        raise ValueError('尺度短片投影比例与确认事实不符')


def render(pid, run, built):
    plan = director.assert_current(pid)
    issues = validator.validate(pid, run)
    if any(i['severity'] == 'block' or i['code'] == 'CHECK_ERROR' for i in issues['issues']):
        raise ValueError('尺度短片正式渲染前校验未通过')
    executable = blender.blender_executable()
    if not executable:
        raise ValueError('尺度短片需要Blender，不回退旧风格')
    directory = storage.project_dir(pid)
    key = cache_key(pid, built)
    out = directory / 'renders/scale-film' / key
    out.mkdir(parents=True, exist_ok=True)
    normalized = storage.read_json(pid, plan['scale_film']['normalized_facts'])
    length = next(f['value'] for f in normalized['facts'] if f['id'] == 'F_girder_length')
    target = sum(s['end'] - s['start'] for s in built['shots'])
    roles = plan['scale_film']['roles']
    if len(built['shots']) != 3 or roles != ['detail', 'hero', 'compare'] or not 15 <= target <= 30:
        raise ValueError('尺度短片时间线与固定三镜不符')
    cfg = {'version': 1, 'width': 1920, 'height': 1080, 'fps': 30,
           'facts_file': str((directory / plan['scale_film']['normalized_facts']).resolve()),
           'shots': [{'id': s['id'], 'role': role, 'start': s['start'], 'end': s['end']} for s, role in zip(built['shots'], roles)]}
    storage.atomic_json(out / 'config.json', cfg)
    with events.tool_call(pid, run, 'render', 'render.scale_film', '正在渲染尺度短片专用三镜画面') as call:
        done = out / 'done.json'
        artifacts = [out / name for name in ('noaudio.mp4', 'projection.json', 'manifest.json')]
        cached = False
        if done.is_file() and all(p.is_file() and p.stat().st_size > 0 for p in artifacts):
            recorded = json.loads(done.read_text())
            cached = recorded.get('sha256') == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}
        if not cached:
            done.unlink(missing_ok=True)
            for path in artifacts:
                path.unlink(missing_ok=True)
            timeout = float(os.environ.get('KEPU_BLENDER_TIMEOUT_S', '1800'))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError('渲染时限必须为有限正数')
            def progress(line):
                parsed = blender.parse_progress(line)
                if parsed:
                    frame, total = parsed
                    if frame % 30 == 0 or frame == total:
                        events.emit(pid, run=run, stage='render', tool='render.scale_film', status='start',
                                    summary=f'尺度短片 {frame}/{total} 帧', detail={'frame': frame, 'total': total})
            blender._render([executable, '--background', '--factory-startup', '--python-exit-code', '1', '--python',
                             str(config.ROOT / 'blender/scale_film.py'), '--', '--config', str((out / 'config.json').resolve()),
                             '--out', str(out.resolve())], timeout, progress)
            if not all(p.is_file() and p.stat().st_size > 0 for p in artifacts):
                raise RuntimeError('尺度短片渲染产物缺失，不能标为完成')
        projection = json.loads((out / 'projection.json').read_text())
        check_projection(projection, length)
        actual = tts.probe_duration(out / 'noaudio.mp4')
        if abs(actual - target) > 1 / 30 + .01:
            raise ValueError('尺度短片渲染时长与时间线不一致')
        storage.atomic_json(done, {'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}})
        storage.write_json(pid, 'renders/scale-film-render.json', {'cache': str(out.relative_to(directory)), 'key': key, 'projection': projection,
                                                                  'input_hash': plan['scale_film']['input_hash']})
        # Only publish after every validation passes, leaving failures visibly failed.
        shutil.copyfile(out / 'noaudio.mp4', directory / 'renders/video_noaudio.mp4')
        call.ok('尺度短片专用画面就绪' + ('（缓存）' if cached else ''))
    return out


def _stamp(value):
    cs = round(value * 100)
    return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'


def _ass_text(value):
    return str(value).replace('\\', '／').replace('{', '（').replace('}', '）').replace('\r', ' ').replace('\n', ' ')


def titles(pid, built, projection):
    plan = director.assert_current(pid)
    fid = plan['scale_film']['length_fact']
    fact = built['facts'][fid]
    source = fact['source']
    analogy = next(a for a in built['analogies'].values() if a['fact'] == fid and a['ref'] == 'football_field')
    length = projection['length_m']
    source_text = f"{source['doc']} · 第 {source['page']} 页"
    is_sample = any(word in json.dumps(fact, ensure_ascii=False).lower() for word in ('示例', 'sample', 'synthetic', '合成测试'))
    badge = ('示例参数 · ' if is_sample else '') + '参数化示意 · 非真实测绘'
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,Hiragino Sans GB,56,&H00F4F4EF,&H00F4F4EF,&H90302118,&H00000000,0,0,0,0,100,100,1,0,1,0.5,0,7,0,0,0,1
Style: Number,DIN Alternate,172,&H00F4F4EF,&H00F4F4EF,&H90302118,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    lines = []
    def text(start, end, content, x, y, size=30, align=7, style='Main', fade=180, raw=False):
        lines.append(f'Dialogue: 1,{_stamp(start)},{_stamp(end)},{style},,0,0,0,,{{\\an{align}\\pos({round(x)},{round(y)})\\fs{size}\\fad({fade},{fade})}}' + (content if raw else _ass_text(content)))
    detail, hero, compare = built['shots']
    duration = built['duration_s']
    text(0, duration, badge, 1830, 42, 23, 9, fade=0)
    text(detail['start'] + .2, detail['end'], 'ENGINEERING / SCALE', 90, 760, 20)
    text(detail['start'] + .35, detail['end'], '一根主梁，\\N能有多长？', 90, 800, 64, raw=True)
    text(hero['start'] + .2, hero['end'], '主梁总长', 965, 610, 26, 8)
    number = f'{length:g}'
    number_size = min(176, round(680 / max(1, len(number)) / .55))
    text(hero['start'] + .35, hero['end'], number, 960, 635, number_size, 8, 'Number')
    text(hero['start'] + .35, hero['end'], 'm', 960 + len(number) * number_size * .205 + 22, 727, 48)
    source_size = min(23, max(15, round(1400 / max(1, len(source_text)))))
    text(hero['start'] + .45, hero['end'], source_text, 965, 850, source_size, 8)
    text(compare['start'] + .15, duration, analogy['text'], 90, 42, 40)
    text(compare['start'] + .25, duration, '同一比例 · 正交俯视', 90, 109, 22)
    field, rect = projection['field'], projection['girder']
    field_y = (field['top'] + field['bottom']) * 540
    girder_y = (rect['top'] + rect['bottom']) * 540
    text(compare['start'] + .3, duration, '足球场参照', 88, field_y - 60, 23)
    text(compare['start'] + .3, duration, '105', 86, field_y - 20, 78, style='Number')
    text(compare['start'] + .3, duration, 'm', 205, field_y + 20, 27)
    text(compare['start'] + .5, duration, '主梁总长', 88, girder_y - 80, 23)
    text(compare['start'] + .5, duration, number, 86, girder_y - 40, 78, style='Number')
    text(compare['start'] + .5, duration, 'm', 106 + len(number) * 33, girder_y, 27)
    text(compare['start'] + .4, duration, source_text + f' · 主梁 {length:g} m / 参照 105 m', 1830, 1040, min(source_size, 21), 9)
    # Animated measure follows the actual girder endpoints at any supported length.
    x1, x2 = round(rect['left'] * 1920), round(rect['right'] * 1920)
    measure_y = round((field['bottom'] + .35 * (rect['top'] - field['bottom'])) * 1080)
    start = compare['start'] + 1
    for x in (x1, x2):
        text(start, duration, '{\\p1}m 0 -8 l 0 8{\\p0}', x, measure_y, raw=True, fade=0)
    for i in range(24):
        end = start + (i + 1) / 30 if i < 23 else duration
        width = round((x2 - x1) * (i + 1) / 24)
        text(start + i / 30, end, f'{{\\p1}}m 0 0 l {width} 0 {width} 2 0 2{{\\p0}}', x1, measure_y, raw=True, fade=0)
    return header + '\n'.join(lines) + '\n'


def sound_bed(path, duration, transitions):
    rate = 48000
    samples = array.array('h')
    for i in range(round(duration * rate)):
        t = i / rate
        fade = max(0, min(1, t / .7, (duration - t) / 1.2))
        value = sum(math.sin(2 * math.pi * f * t) * gain for f, gain in ((73.416, .025), (110, .015), (146.832, .009)))
        for at in transitions:
            if t >= at:
                value += .025 * math.exp(-(t - at) * 1.8) * math.sin(2 * math.pi * 440 * (t - at))
        samples.append(round(value * fade * 32767))
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate); out.writeframes(samples.tobytes())


def mux(pid, run):
    director.assert_current(pid)
    directory = storage.project_dir(pid)
    built = storage.read_json(pid, 'timeline.json')
    render = storage.read_json(pid, 'renders/scale-film-render.json', {})
    if render.get('key') != cache_key(pid, built):
        raise ValueError('尺度短片画面或输入已变化，请从render重新生成')
    duration = built['duration_s']
    with events.tool_call(pid, run, 'compose', 'ffmpeg.scale_film', '正在合成动态来源标题、配音与原创声景') as call:
        ass = directory / 'renders/scale-film.ass'
        ass.write_text(titles(pid, built, render['projection']), encoding='utf-8')
        bed = directory / 'renders/scale-film-sound.wav'
        sound_bed(bed, duration, [s['start'] for s in built['shots'][1:]])
        # Run in renders so libass gets a simple, shell-free relative filename.
        temp = directory / 'renders/scale-film-final.tmp.mp4'
        temp.unlink(missing_ok=True)
        try:
            subprocess.run([tts.ffmpeg(), '-y', '-v', 'error', '-i', str(directory / 'renders/video_noaudio.mp4'),
                            '-i', str(directory / 'renders/narration.wav'), '-i', str(bed),
                            '-vf', 'ass=scale-film.ass', '-filter_complex',
                            '[1:a][2:a]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9[a]',
                            '-map', '0:v', '-map', '[a]', '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-b:a', '192k', '-t', str(duration), '-movflags', '+faststart', str(temp)],
                           cwd=directory / 'renders', check=True, capture_output=True, timeout=600)
            actual = tts.probe_duration(temp)
            if abs(actual - duration) > 1 / 30 + .01:
                raise ValueError('尺度短片最终音画时长不一致')
            temp.replace(directory / 'renders/final.mp4')
        finally:
            temp.unlink(missing_ok=True)
        built['rendered_duration_s'] = actual
        built['rendered_source_hash'] = director.source_hash(pid)
        built['rendered_run'] = run
        built['rendered_video_hash'] = hashlib.sha256((directory / 'renders/final.mp4').read_bytes()).hexdigest()
        built['style'] = 'scale_film'
        built['music'] = {'title': '原创合成声景', 'credit': '程序原创合成；非实机录音', 'file': 'renders/scale-film-sound.wav'}
        storage.write_json(pid, 'timeline.json', built)
        call.ok('尺度短片已合成，来源与比例标题按当前事实生成')
    return directory / 'renders/final.mp4'
