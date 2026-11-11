"""Scale-film validation/camera math stays importable without Blender.
Scene construction reuses the approved T24 light/material recipe, never its facts.
"""
from __future__ import annotations
import math
from pathlib import Path

REQUIRED_FACTS=('F_girder_length','F_overall_height','F_span','F_lift_height','F_girder_height','F_wheel_count')
ROLES=('detail','hero','compare')

def finite_number(value, label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{label} must be a finite number')
    return value

def validate_config(config):
    if not isinstance(config,dict) or type(config.get('version')) is not int or config['version']!=1:
        raise ValueError('config.version must be 1')
    for key in ('width','height','fps'):
        value=config.get(key)
        if type(value) is not int or value<=0:raise ValueError(f'{key} must be a positive integer')
    if config['width']%2 or config['height']%2:raise ValueError('H264 width and height must be even')
    if not Path(config.get('facts_file','')).is_absolute():raise ValueError('facts_file must be absolute')
    shots=config.get('shots')
    if not isinstance(shots,list) or len(shots)!=3:raise ValueError('exactly three shots required')
    previous=0;ids=set()
    for shot,role in zip(shots,ROLES):
        if not isinstance(shot,dict) or shot.get('role')!=role:raise ValueError('shots must be detail, hero, compare in order')
        sid=shot.get('id')
        if not isinstance(sid,str) or not sid or sid in ids:raise ValueError('shot ids must be unique nonempty strings')
        ids.add(sid)
        start=finite_number(shot.get('start'),'shot.start');end=finite_number(shot.get('end'),'shot.end')
        if abs(start-previous)>1e-7 or end<=start:raise ValueError('shots must be continuous with positive duration from zero')
        for v in (start,end):
            if abs(v*config['fps']-round(v*config['fps']))>1e-6:raise ValueError('shot boundaries must align to frame grid')
        previous=end
    if not 15<=previous<=30:raise ValueError('total duration must be 15–30 seconds')
    return config

def validate_facts(document):
    if not isinstance(document,dict) or not isinstance(document.get('facts'),list):raise ValueError('facts document requires facts list')
    accepted={}
    for fact in document['facts']:
        if not isinstance(fact,dict):raise ValueError('each fact must be an object')
        key=fact.get('id')
        if key not in REQUIRED_FACTS:continue
        if key in accepted:raise ValueError(f'duplicate dimension fact {key}')
        if fact.get('status') not in ('confirmed','verified'):raise ValueError(f'{key} is not confirmed')
        value=finite_number(fact.get('value'),key)
        if value<=0:raise ValueError(f'{key} must be positive')
        unit=fact.get('unit')
        if key!='F_wheel_count' and unit not in (None,'m'):raise ValueError(f'{key} must be normalized metres')
        if key=='F_wheel_count' and (not float(value).is_integer() or value<4):raise ValueError('wheel_count must be integer >= 4')
        accepted[key]=value
    missing={'F_girder_length','F_overall_height'}-set(accepted)
    if missing:raise ValueError('missing confirmed dimensions: '+', '.join(sorted(missing)))
    return accepted

def comparison_layout(length, aspect):
    finite_number(length,'length');finite_number(aspect,'aspect')
    if length<=0 or aspect<=0:raise ValueError('positive length and aspect required')
    # 104m/16:9 recovers the reviewed T24 composition. Adapt to keep both physical objects with margins.
    width=max(188.,length/(105/188),105/.60,2*48.4*aspect/.92)
    return {'ortho_scale':width,'camera_y':-1.,'field_y':7.,'girder_y':-43.,'reference_length_m':105.,'reference_width_m':68.}

def rect_topdown(xmin,xmax,ymin,ymax,layout,aspect):
    width=layout['ortho_scale'];height=width/aspect;cy=layout['camera_y']
    return {'left':.5+xmin/width,'right':.5+xmax/width,'top':.5-(ymax-cy)/height,'bottom':.5-(ymin-cy)/height}

def shot_at(shots,time_s):
    for shot in shots:
        if shot['start']<=time_s<shot['end']:return shot
    raise ValueError('time outside configured timeline')

def perspective_point(point,position,target,lens,aspect):
    def dot(a,b):return sum(x*y for x,y in zip(a,b))
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    def unit(v):
        length=math.sqrt(dot(v,v));return tuple(x/length for x in v)
    forward=unit(tuple(t-p for t,p in zip(target,position)));right=unit(cross(forward,(0,0,1)));up=cross(right,forward)
    delta=tuple(x-p for x,p in zip(point,position));depth=dot(delta,forward)
    if depth<=0:return (float('inf'),float('inf'))
    tan_half=36/(2*lens)
    return (.5+dot(delta,right)/(2*depth*tan_half),.5-dot(delta,up)*aspect/(2*depth*tan_half))

def hero_envelope(dim):
    # Separate component envelopes avoid pretending a trolley-height box fills the beam ends.
    length,height=dim.length,dim.height
    span=getattr(dim,'span',length*88/104)
    return ([(x,y,z) for x in (-length/2-.15,length/2+.15) for y in (-5.35,5.35) for z in (height-12,height-4.2)]
        +[(x,y,height) for x in (-6,6) for y in (-5,5)]
        +[(x,y,0) for x in (-span/2-1.6,span/2+1.6) for y in (-11.2,11.2)]
        +[(x,y,height+1.5) for x in (-span/2-1.5,-span/2+1.5) for y in (-5.35,5.35)])

def fit_hero(position,target,dim,aspect):
    # Rails may continue beyond the frame as in approved T24.
    corners=hero_envelope(dim)
    for _ in range(96):
        points=[perspective_point(c,position,target,45,aspect) for c in corners]
        if all(.055<=x<=.945 and .055<=y<=.945 for x,y in points):return position
        position=(position[0]*1.06,position[1]*1.06,position[2])
    raise ValueError('unable to fit hero camera to input dimensions')

def camera_pose(dim,role,u,aspect):
    sx=dim.length/104;sz=dim.height/51
    def lerp(a,b):return tuple(x+(y-x)*u for x,y in zip(a,b))
    if role=='detail':
        bottom=getattr(dim,'girder_bottom',dim.height-12)
        top=getattr(dim,'girder_top',dim.height-5.5)
        return {'position':lerp((-51*sx,-30,bottom-18*sz),(-37*sx,-27,bottom-12*sz)), 'target':lerp((-20*sx,0,bottom),(0,0,top-2.5)),'projection':'PERSP','lens':30}
    if role=='hero':
        fit=max(sx,sz)*max(1.,(16/9)/aspect)
        p=lerp((88*fit,-148*fit,5.5*sz),(80*fit,-138*fit,6*sz))
        return {'position':fit_hero(p,(0,0,26*sz),dim,aspect),'target':(0,0,26*sz),'projection':'PERSP','lens':45}
    if role=='compare':
        layout=comparison_layout(dim.length,aspect)
        return {'position':(0,layout['camera_y'],max(dim.height+100,180)),'target':(0,layout['camera_y'],0),'projection':'ORTHO','ortho_scale':layout['ortho_scale'],'lens':45}
    raise ValueError('unknown role')

def build_scene(config,dim):
    import bpy
    from mathutils import Vector
    from common import set_attr,set_input
    from crane import build_crane
    from scene import materials,material,linear_hex
    bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
    s = bpy.context.scene
    s.render.engine = 'BLENDER_EEVEE'
    s.render.resolution_x = config["width"]; s.render.resolution_y = config["height"]; s.render.resolution_percentage = 100
    s.render.image_settings.file_format='PNG'; s.render.fps=config["fps"]
    set_attr(s.eevee,'taa_render_samples',48)
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
    parents=build_crane(dim,mats)
    crane_objects=list(bpy.context.scene.objects)
    # Neutral physical stage, not a fictional production facility.
    floor_mat=material('Scale film basalt concrete',linear_hex('#41484C'),.72,.03,.045,.6,.05)
    n=floor_mat.node_tree.nodes;l=floor_mat.node_tree.links
    tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=180
    coord=n.new('ShaderNodeTexCoord');l.new(coord.outputs['Object'],tex.inputs['Vector'])
    bump=n.new('ShaderNodeBump');bump.inputs['Distance'].default_value=.004;bump.inputs['Strength'].default_value=.16
    l.new(tex.outputs['Fac'],bump.inputs['Height']);l.new(bump.outputs['Normal'],n.get('Principled BSDF').inputs['Normal'])
    bpy.ops.mesh.primitive_plane_add(size=20000, location=(0,0,-.035));floor=bpy.context.object;floor.name='Scale film neutral stage';floor.data.materials.append(floor_mat)
    # World fill is deliberately cool; warm side key reveals stiffeners and bevels.
    s.world=bpy.data.worlds.new('Scale film overcast fill');s.world.use_nodes=True
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
    light('Scale film warm side sun','SUN',(-110,-85,85),(0,0,0),4.0,(1,.8,.61))
    light('Scale film broad cool fill','AREA',(0,-65,70),(0,0,29),45000,(.53,.7,1),85)
    light('Scale film rim softbox','AREA',(0,45,75),(0,0,30),50000,(1,.62,.32),95)
    # Mild distance extinction; only a neutral atmosphere, no invented terrain/assets.
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,60));fog=bpy.context.object;fog.name='Scale film atmospheric depth';fog.scale=(20000,20000,350)
    vol=bpy.data.materials.new('Scale film fine atmosphere');vol.use_nodes=True
    nn=vol.node_tree.nodes;nn.clear();ov=nn.new('ShaderNodeOutputMaterial');v=nn.new('ShaderNodeVolumePrincipled')
    v.inputs['Density'].default_value=.0008;v.inputs['Color'].default_value=(.56,.65,.74,1);v.inputs['Anisotropy'].default_value=.15
    vol.node_tree.links.new(v.outputs['Volume'],ov.inputs['Volume']);fog.data.materials.append(vol)
    camd=bpy.data.cameras.new('Scale film camera');cam=bpy.data.objects.new('Scale film camera',camd);s.collection.objects.link(cam);s.camera=cam
    camd.clip_end=15000;camd.sensor_width=36;camd.sensor_fit="HORIZONTAL"
    # Standardized 105x68 m field, direct world-space coordinates.
    field_objects=[]
    fieldmat=material('Scale film reference turf',linear_hex('#253E39'),.9,0,.07,.5)
    line_mat=material('Scale film reference lines',linear_hex('#C9D9CE'),.8,0,0)
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

    scale=max(dim.length/104,dim.height/51)
    for obj in s.objects:
        if obj.type=='LIGHT' and obj.data.type=='AREA':
            obj.location *= scale
            obj.data.size *= scale
            obj.data.energy *= scale*scale
    return {'scene':s,'parents':parents,'crane_objects':crane_objects,'field_objects':field_objects,'fog':fog,'camera':cam,'dim':dim}
