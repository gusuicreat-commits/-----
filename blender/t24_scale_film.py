"""T24 isolated product-CG sample. Run with Blender; never modifies shared scripts.
Geometry is the project's existing parameterized illustration, not measured CAD.
"""
import argparse, json, math, sys, time, os, subprocess
from pathlib import Path
import bpy
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import derive_dimensions, read_facts, set_attr, set_input
from crane import build_crane
from scene import materials, material, linear_hex

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--mode', choices=['stills','film'], default='stills')
p.add_argument('--width', type=int, default=1280)
p.add_argument('--height', type=int, default=720)
p.add_argument('--samples', type=int, default=48)
p.add_argument('--facts', default='outputs/T24-scale-film/facts.synthetic-example.json')
p.add_argument('--start', type=int, default=0)
p.add_argument('--end', type=int, default=449)
p.add_argument('--out', default='outputs/T24-scale-film')
a = p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
out = ROOT / a.out; out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
s = bpy.context.scene
s.render.engine = 'BLENDER_EEVEE'
s.render.resolution_x = a.width; s.render.resolution_y = a.height; s.render.resolution_percentage = 100
s.render.image_settings.file_format='PNG'; s.render.fps=30
set_attr(s.eevee,'taa_render_samples',a.samples)
set_attr(s.eevee,'use_raytracing',True)
set_attr(s.eevee,'fast_gi_quality',.75)
set_attr(s.eevee,'fast_gi_ray_count',4)
s.view_settings.view_transform='AgX'; set_attr(s.view_settings,'look','AgX - Medium High Contrast')
s.view_settings.exposure=0.0
mats=materials()
for name in ('paint','red'):
    mat=mats[name]; n=mat.node_tree.nodes; l=mat.node_tree.links; bs=n.get('Principled BSDF')
    set_input(bs,'Roughness',.29); set_input(bs,'Coat Weight',.34); set_input(bs,'Coat Roughness',.24)
    tex=n.new('ShaderNodeTexNoise'); tex.inputs['Scale'].default_value=140
    coord=n.new('ShaderNodeTexCoord'); l.new(coord.outputs['Object'],tex.inputs['Vector'])
    bump=n.new('ShaderNodeBump'); bump.inputs['Strength'].default_value=.16; bump.inputs['Distance'].default_value=.002
    l.new(tex.outputs['Fac'],bump.inputs['Height']); l.new(bump.outputs['Normal'],bs.inputs['Normal'])
facts_path=ROOT/a.facts
dim=derive_dimensions(read_facts(facts_path)); parents=build_crane(dim,mats)
crane_objects=list(bpy.context.scene.objects)
# Neutral physical stage, not a fictional production facility.
floor_mat=material('T24 basalt concrete',linear_hex('#41484C'),.72,.03,.045,.6,.05)
n=floor_mat.node_tree.nodes;l=floor_mat.node_tree.links
tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=180
coord=n.new('ShaderNodeTexCoord');l.new(coord.outputs['Object'],tex.inputs['Vector'])
bump=n.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.004;bump.inputs['Strength'].default_value=.16
l.new(tex.outputs['Fac'],bump.inputs['Height']);l.new(bump.outputs['Normal'],n.get('Principled BSDF').inputs['Normal'])
bpy.ops.mesh.primitive_plane_add(size=20000, location=(0,0,-.035));floor=bpy.context.object;floor.name='T24 neutral stage';floor.data.materials.append(floor_mat)
# World fill is deliberately cool; warm side key reveals stiffeners and bevels.
s.world=bpy.data.worlds.new('T24 overcast fill');s.world.use_nodes=True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.26,.35,.48,1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.22

wn=s.world.node_tree.nodes;wl=s.world.node_tree.links
bg=wn.get('Background');outw=wn.get('World Output');path=wn.new('ShaderNodeLightPath')
visible=wn.new('ShaderNodeBackground');visible.inputs['Color'].default_value=(.24,.29,.33,1);visible.inputs['Strength'].default_value=.7
mix=wn.new('ShaderNodeMixShader');wl.new(path.outputs['Is Camera Ray'],mix.inputs[0]);wl.new(bg.outputs[0],mix.inputs[1]);wl.new(visible.outputs[0],mix.inputs[2]);wl.new(mix.outputs[0],outw.inputs['Surface'])
def light(name,kind,pos,target,power,color,size=1):
    d=bpy.data.lights.new(name,kind);d.energy=power;d.color=color
    o=bpy.data.objects.new(name,d);s.collection.objects.link(o);o.location=pos
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()
    if kind=='AREA': d.shape='DISK';d.size=size
    else: d.angle=math.radians(2)
    return o
light('T24 warm side sun','SUN',(-110,-85,85),(0,0,0),4.0,(1,.8,.61))
light('T24 broad cool fill','AREA',(0,-65,70),(0,0,29),45000,(.53,.7,1),85)
light('T24 rim softbox','AREA',(0,45,75),(0,0,30),50000,(1,.62,.32),95)
# Mild distance extinction; only a neutral atmosphere, no invented terrain/assets.
bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,60));fog=bpy.context.object;fog.name='T24 atmospheric depth';fog.scale=(20000,20000,350)
vol=bpy.data.materials.new('T24 fine atmosphere');vol.use_nodes=True
nn=vol.node_tree.nodes;nn.clear();ov=nn.new('ShaderNodeOutputMaterial');v=nn.new('ShaderNodeVolumePrincipled')
v.inputs['Density'].default_value=.0008;v.inputs['Color'].default_value=(.56,.65,.74,1);v.inputs['Anisotropy'].default_value=.15
vol.node_tree.links.new(v.outputs['Volume'],ov.inputs['Volume']);fog.data.materials.append(vol)
camd=bpy.data.cameras.new('T24 camera');cam=bpy.data.objects.new('T24 camera',camd);s.collection.objects.link(cam);s.camera=cam
camd.clip_end=15000;camd.sensor_width=36
# Standardized 105x68 m field, direct world-space coordinates.
field_objects=[]
fieldmat=material('T24 reference turf',linear_hex('#253E39'),.9,0,.07,.5)
line_mat=material('T24 reference lines',linear_hex('#C9D9CE'),.8,0,0)
def line(name,points,width=.10):
    c=bpy.data.curves.new(name,'CURVE');c.dimensions='3D';c.bevel_depth=width/2;c.bevel_resolution=1
    sp=c.splines.new('POLY');sp.points.add(len(points)-1)
    for p,co in zip(sp.points,points):p.co=(*co,1)
    ob=bpy.data.objects.new(name,c);s.collection.objects.link(ob);ob.data.materials.append(line_mat);field_objects.append(ob)
field_y=7
bpy.ops.mesh.primitive_plane_add(size=2,location=(0,field_y,.03));field=bpy.context.object;field.name='105 x 68 m standardized reference';field.scale=(52.5,34,1);field.data.materials.append(fieldmat);field_objects.append(field)
z=.06
line('field boundary',[(-52.5,field_y-34,z),(52.5,field_y-34,z),(52.5,field_y+34,z),(-52.5,field_y+34,z),(-52.5,field_y-34,z)],.16)
line('halfway',[(0,field_y-34,z),(0,field_y+34,z)],.14)
line('centre circle',[(9.15*math.cos(i*math.tau/128),field_y+9.15*math.sin(i*math.tau/128),z) for i in range(129)],.14)
for side in (-1,1):
    x=side*52.5
    for dep,wide in ((16.5,40.32),(5.5,18.32)):
        line('reference penalty box',[(x,field_y-wide/2,z),(x-side*dep,field_y-wide/2,z),(x-side*dep,field_y+wide/2,z),(x,field_y+wide/2,z)],.14)
# All cameras evaluated directly at time. No accumulation or perspective comparison.
def lerp(a,b,t):return tuple(x+(y-x)*t for x,y in zip(a,b))
def evaluate(t):
    compare=t>=9
    for ob in field_objects:ob.hide_render=not compare
    fog.hide_render=compare
    parents['girder'].location=(0,-43,-dim.girder_bottom+1) if compare else (0,0,0)
    for ob in crane_objects:
        node=ob.get('geometry_node','')
        ob.hide_render=compare and node!='girder'
        if ob.type=='EMPTY':ob.hide_render=False
    if t<4:
        u=t/4; pos=lerp((-51,-30,21),(-37,-27,27),u);target=lerp((-20,0,39),(0,0,43),u);camd.type='PERSP';camd.lens=30
    elif t<9:
        u=(t-4)/5;pos=lerp((88,-148,5.5),(80,-138,6.0),u);target=(0,0,26);camd.type='PERSP';camd.lens=45
    else:
        pos=(0,-1,180);target=(0,-1,0);camd.type='ORTHO';camd.ortho_scale=188
    cam.location=pos;cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
    # Exact overhead has no usable Y-up tracking direction; force north-up.
    if compare:cam.rotation_euler=(0,0,0)
    bpy.context.view_layer.update()
    return {'t':t,'position':pos,'target':target,'projection':camd.type,'lens':camd.lens,'ortho_scale':camd.ortho_scale}

rows=[]
frames=[(60,'01-detail'),(195,'02-hero'),(345,'03-scale')] if a.mode=='stills' else [(i,f'{i:05d}') for i in range(a.start,min(a.end,270)+1)]
folder=out/('stills' if a.mode=='stills' else 'frames');folder.mkdir(parents=True,exist_ok=True)
for i,name in frames:
    tick=time.monotonic();row=evaluate(i/30);path=folder/(name+'.png');s.render.filepath=str(path)
    bpy.ops.render.render(write_still=True);row.update(path=str(path),seconds=time.monotonic()-tick,frame=i);rows.append(row)
    print('T24_FRAME '+json.dumps(row),flush=True)
held_frames=[]
if a.mode=='film' and a.end>=271:
    source=folder/'00270.png'
    if not source.exists(): raise RuntimeError('Missing static comparison frame 270')
    for i in range(max(a.start,271),a.end+1):
        dest=folder/f'{i:05d}.png'
        if dest.exists():dest.unlink()
        os.link(source,dest);held_frames.append(i)
video=None
if a.mode=='film' and a.end==449 and all((folder/f'{i:05d}.png').exists() for i in range(450)):
    video=out/'noaudio.mp4'
    subprocess.run(['/opt/homebrew/bin/ffmpeg','-y','-framerate','30','-i',str(folder/'%05d.png'),'-frames:v','450','-c:v','libx264','-preset','slow','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(video)],check=True)
manifest={'mode':a.mode,'resolution':[a.width,a.height],'fps':30,'duration':15,'elapsed_seconds':time.monotonic()-started,'renders':rows,'geometry_source':'blender/crane.py build_crane() unchanged','facts_source':str(facts_path.relative_to(ROOT)),'status':'示例参数·参数化示意','reference':'105×68m标准化足球场示意，非实际场地','limits':['Existing structural additions are illustrative, not measured CAD.','No validated manufacturer identity or performance claim.','Neutral CG stage, no real factory or field validation.'],'camera_cut_seconds':[0,4,9,15],'independent_frames_this_run':len(rows),'held_frame_indices':held_frames,'video':str(video) if video else None,'final_timeline_frames':450,'full_film_unique_renders':271}
(out/(a.mode+f'-{a.start}-{a.end}-manifest.json')).write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
