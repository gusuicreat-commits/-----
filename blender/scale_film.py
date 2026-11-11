"""Application-facing parameterized scale-film renderer (Blender entry point)."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from scale_film_scene import validate_config,validate_facts,build_scene,camera_pose,comparison_layout,shot_at
from common import derive_dimensions

def write_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--config',required=True)
    p.add_argument('--out',required=True)
    p.add_argument('--stills',action='store_true')
    args=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    started=time.monotonic()
    config_path=Path(args.config)
    out=Path(args.out)
    if not config_path.is_absolute() or not out.is_absolute():raise ValueError('--config and --out must be absolute')
    config_bytes=config_path.read_bytes();config=validate_config(json.loads(config_bytes))
    facts_path=Path(config['facts_file']);facts_bytes=facts_path.read_bytes();document=json.loads(facts_bytes)
    validate_facts(document);dim=derive_dimensions(document)
    ffmpeg=shutil.which('ffmpeg')
    if not args.stills and ffmpeg is None:raise RuntimeError('ffmpeg is required for video encoding')
    out.mkdir(parents=True,exist_ok=True)
    import bpy
    from mathutils import Vector
    from bpy_extras.object_utils import world_to_camera_view
    state=build_scene(config,dim);scene=state['scene'];cam=state['camera'];aspect=config['width']/config['height']
    compare_shot=config['shots'][2];layout=comparison_layout(dim.length,aspect)
    camera_records=[];render_records=[]
    def evaluate(shot,t):
        role=shot['role'];compare=role=='compare';u=(t-shot['start'])/(shot['end']-shot['start'])
        for obj in state['field_objects']:obj.hide_render=not compare
        state['fog'].hide_render=compare
        state['parents']['girder'].location=(0,layout['girder_y'],-dim.girder_bottom+1) if compare else (0,0,0)
        for obj in state['crane_objects']:
            obj.hide_render=compare and obj.get('geometry_node','')!='girder'
            if obj.type=='EMPTY':obj.hide_render=False
        pose=camera_pose(dim,role,u,aspect)
        cam.location=pose['position'];cam.rotation_euler=(Vector(pose['target'])-cam.location).to_track_quat('-Z','Y').to_euler()
        cam.data.type=pose['projection'];cam.data.lens=pose['lens']
        if compare:cam.rotation_euler=(0,0,0);cam.data.ortho_scale=pose['ortho_scale']
        bpy.context.view_layer.update()
        return dict(pose,shot_id=shot['id'],role=role,t=t)
    # Rectangles come from actual unscaled world-space mesh bounding corners.
    evaluate(compare_shot,compare_shot['start'])
    def projected_rect(objects):
        points=[world_to_camera_view(scene,cam,obj.matrix_world@Vector(corner)) for obj in objects for corner in obj.bound_box]
        return {'left':min(p.x for p in points),'right':max(p.x for p in points),'top':1-max(p.y for p in points),'bottom':1-min(p.y for p in points)}
    girder=[obj for obj in state['crane_objects'] if obj.type=='MESH' and obj.get('geometry_node')=='girder']
    field=[obj for obj in state['field_objects'] if obj.type=='MESH']
    projection={'version':1,'coordinate_system':'normalized_top_left','shot_id':compare_shot['id'],'field':projected_rect(field),'girder':projected_rect(girder),'length_m':dim.length,'reference_length_m':105,'reference_width_m':68,'projection':'ORTHO'}
    for rect in (projection['field'],projection['girder']):
        if not (0<=rect['left']<rect['right']<=1 and 0<=rect['top']<rect['bottom']<=.96):raise ValueError('comparison geometry outside safe image bounds')
    write_json(out/'projection.json',projection)
    stills=out/'stills';stills.mkdir(exist_ok=True)
    # Midpoint keys retained in both modes, filenames independent of user-provided shot IDs.
    def render(path,shot,t,frame=None):
        tick=time.monotonic();pose=evaluate(shot,t);scene.render.filepath=str(path);bpy.ops.render.render(write_still=True)
        record={'path':str(path.relative_to(out)),'frame':frame,'seconds':time.monotonic()-tick,'camera':pose}
        render_records.append(record);return record
    for i,shot in enumerate(config['shots']):
        t=(shot['start']+shot['end'])/2
        render(stills/f'{i+1:02d}-{shot["role"]}.png',shot,t)
        camera_records.append({'id':shot['id'],'role':shot['role'],'start':camera_pose(dim,shot['role'],0,aspect),'midpoint':camera_pose(dim,shot['role'],.5,aspect),'end':camera_pose(dim,shot['role'],1,aspect)})
    duration=config['shots'][-1]['end'];fps=config['fps'];frame_count=round(duration*fps);moving_frames=round(compare_shot['start']*fps)
    video=None;timeline_renders=0;held_frames=0
    if not args.stills:
        # Delete only this invocation's uniquely-owned temporary PNG directory, even on failures.
        with tempfile.TemporaryDirectory(prefix='.scale-film-frames-',dir=out) as temporary:
            folder=Path(temporary)
            for i in range(moving_frames):
                t=i/fps;render(folder/f'{i:05d}.png',shot_at(config['shots'],t),t,i);timeline_renders+=1
                print(f'已完成第 {i+1}/{frame_count} 帧',flush=True)
            # Reuse exactly the static comparison key already rendered above.
            comparison_key=stills/'03-compare.png'
            for i in range(moving_frames,frame_count):
                os.link(comparison_key,folder/f'{i:05d}.png');held_frames+=1
            print(f'已完成第 {frame_count}/{frame_count} 帧（末镜复用静帧）',flush=True)
            video=out/'noaudio.mp4'
            subprocess.run([ffmpeg,'-y','-framerate',str(fps),'-i',str(folder/'%05d.png'),'-frames:v',str(frame_count),'-c:v','libx264','-preset','slow','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
    manifest={'version':1,'mode':'stills' if args.stills else 'film','resolution':[config['width'],config['height']],'fps':fps,'duration':duration,'dims':asdict(dim),'camera':camera_records,'input':{'config_file':str(config_path),'config_sha256':hashlib.sha256(config_bytes).hexdigest(),'facts_file':str(facts_path),'facts_sha256':hashlib.sha256(facts_bytes).hexdigest()},'geometry_source':'blender/crane.py build_crane; parameterized illustration, not measured CAD','reference':'105×68m standardized schematic, not a real site','frames':{'timeline':frame_count,'timeline_moving_rendered':timeline_renders,'retained_keys':3,'independent_render_operations':len(render_records),'static_timeline_frames_reused':held_frames},'renders':render_records,'elapsed_seconds':time.monotonic()-started,'video':str(video) if video else None,'temporary_frames_cleaned':not args.stills,'projection_file':'projection.json','assumptions':list(dim.assumed),'limits':['No manufacturer identity or performance claim.','No text, numerals, source labels, or audio burned in; application must compose evidence labels.']}
    write_json(out/'manifest.json',manifest)
    print('SCALE_FILM_COMPLETE '+json.dumps({'manifest':str(out/'manifest.json'),'elapsed_seconds':manifest['elapsed_seconds']}),flush=True)

if __name__=='__main__':main()
