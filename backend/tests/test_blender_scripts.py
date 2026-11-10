"""不导入渲染运行时、不启动子进程、不联网的镜头数学验证。"""
import importlib.util
import json
import math
import sys

import pytest
from app.config import ROOT
from app.model3d.parametric import build_parametric
from app.model3d.rig import _dimensions

spec = importlib.util.spec_from_file_location("blender_common", ROOT / "blender/common.py")
common = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = common
spec.loader.exec_module(common)


def facts(**values):
    return {"facts":[{"id":key,"value":value,"status":"confirmed"} for key,value in values.items()]}


def test_default_dimensions_match_model():
    dim = common.derive_dimensions({"facts":[]})
    used = _dimensions({})
    assert (dim.length,dim.height,dim.span,dim.lift_height,dim.girder_height) == tuple(used.values())
    assert dim.wheel_count == 16
    assert dim.hoist_range == (2,dim.girder_bottom-3)


@pytest.mark.parametrize("values", [{}, {"F_girder_length":104,"F_overall_height":51,"F_span":88,"F_lift_height":45},
                                      {"F_girder_length":120,"F_overall_height":65,"F_span":100,"F_girder_height":8}])
def test_bounds_match_exported_model(tmp_path,values):
    dim = common.derive_dimensions(facts(**values))
    actual = build_parametric(values,tmp_path/"reference.glb")
    assert dim.bbox == pytest.approx(tuple(actual["bbox_m"].values()))


def test_only_accepted_facts_and_dependent_defaults():
    document = facts(F_girder_length=120,F_overall_height=60)
    document["facts"].extend([
        {"id":"F_span","value":999,"status":"rejected"},
        {"id":"F_wheel_count","value":64,"status":"needs_review"},
        {"id":"F_girder_height","value":7,"status":"verified"},
    ])
    dim = common.derive_dimensions(document)
    assert dim.span == 102
    assert dim.lift_height == 52.8
    assert dim.girder_height == 7
    assert dim.wheel_count == 16
    assert "F_span" in dim.assumed and "F_girder_height" not in dim.assumed


@pytest.mark.parametrize("key,value",[("F_girder_length",float("nan")),("F_overall_height",-1),
    ("F_span",200),("F_girder_height",45),("F_wheel_count",3),("F_wheel_count",5.2),("F_wheel_count",float("inf"))])
def test_invalid_dimensions(key,value):
    with pytest.raises(ValueError):
        common.derive_dimensions(facts(**{key:value}))


@pytest.mark.parametrize("count,expected",[(4,(1,1,1,1)),(16,(4,4,4,4)),(64,(16,16,16,16)),(67,(17,17,17,16))])
def test_wheel_distribution(count,expected):
    assert common.wheel_distribution(count) == expected
    assert sum(common.wheel_distribution(count)) == count


def test_axis_mapping_and_handedness():
    assert common.to_blender((2,3,4)) == (2,-4,3)
    assert common.to_blender((0,1,0)) == (0,0,1)


@pytest.mark.parametrize("time,expected",[(-1,0),(0,0),(.25,.0625),(.5,.5),(.75,.9375),(1,1),(2,1)])
def test_ease_matches_player(time,expected):
    assert common.ease(time) == expected


def test_orbit_radius_angles_and_seconds():
    dim = common.derive_dimensions(facts(F_span=88))
    radius = math.sqrt(104**2+51**2+120**2)*1.6
    for time,angle in ((0,-30),(3,0),(6,30),(.5,-30+60*4*(.5/6)**3)):
        position,target = common.orbit(dim,{},time,6)
        delta = tuple(p-t for p,t in zip(position,target))
        assert math.sqrt(sum(v*v for v in delta)) == pytest.approx(radius)
        assert math.degrees(math.atan2(delta[0],delta[2])) == pytest.approx(angle)
        assert math.degrees(math.asin(delta[1]/radius)) == pytest.approx(15)


@pytest.mark.parametrize("params",[{"distance":0},{"from_deg":float("nan")},{"elevation_deg":90}])
def test_invalid_orbit(params):
    with pytest.raises(ValueError):
        common.orbit(common.derive_dimensions({}),params,0,6)


def test_frame_numbering_excludes_end_and_covers_fractional_duration():
    assert len(common.frame_times(6,30)) == 180
    assert common.frame_times(6,30)[-1] == 179/30
    assert common.frame_times(.05,30) == [0,1/30]


@pytest.mark.parametrize("width,height",[(1920,1080),(1080,1920),(960,540)])
def test_projection_vertical_fov_and_top_left(width,height):
    camera,target = (0,0,10),(0,0,0)
    center = common.project_point(target,camera,target,width,height)
    assert (center["x"],center["y"],center["in_frame"]) == (width/2,height/2,True)
    top = common.project_point((0,10*math.tan(math.radians(20)),0),camera,target,width,height)
    assert top["y"] == pytest.approx(0,abs=1e-9)
    right = common.project_point((1,0,0),camera,target,width,height)
    assert right["x"] > width/2
    assert not common.project_point((0,0,11),camera,target,width,height)["in_frame"]
    assert common.project_point(camera,camera,target,width,height)["x"] is None


def test_project_path_override_and_loading(tmp_path,monkeypatch):
    monkeypatch.setenv("KEPU_PROJECTS_DIR",str(tmp_path))
    project = tmp_path/"sample"
    project.mkdir()
    (project/"facts.json").write_text(json.dumps(facts(F_span=88)),encoding="utf-8")
    assert common.read_facts("projects/sample/facts.json")["facts"][0]["value"] == 88
    assert common.resolve_path("blender/samples") == ROOT/"blender/samples"


def test_isolated_import_needs_only_standard_library(monkeypatch, tmp_path):
    import builtins
    import runpy

    original_import = builtins.__import__

    def standard_only(name, *args, **kwargs):
        if name.split('.')[0] not in sys.stdlib_module_names:
            raise ImportError(f"测试禁止加载非标准库模块：{name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', standard_only)
    monkeypatch.setenv('KEPU_PROJECTS_DIR', str(tmp_path))
    isolated = runpy.run_path(str(ROOT / 'blender/common.py'))
    assert isolated['ROOT'] == ROOT
    assert isolated['resolve_path']('projects/example') == tmp_path / 'example'
    dim = isolated['derive_dimensions'](facts(F_span=88, F_wheel_count=64))
    assert (dim.length, dim.span, dim.wheel_count) == (104, 88, 64)


def test_sample_dimensions_match_backend():
    values = dict(F_girder_length=104, F_overall_height=51, F_span=88,
                  F_lift_height=45, F_girder_height=6.5, F_wheel_count=64)
    dim = common.derive_dimensions(facts(**values))
    assert (dim.length, dim.height, dim.span, dim.lift_height, dim.girder_height) == tuple(_dimensions(values).values())


@pytest.mark.parametrize('error', [AttributeError, TypeError, ValueError, RuntimeError])
def test_optional_settings_reject_invalid_values_without_aborting(error, capsys):
    class Restricted:
        @property
        def mode(self):
            return 'DEFAULT'

        @mode.setter
        def mode(self, value):
            raise error('unsupported')

        default_value = mode

    from types import SimpleNamespace
    obj = Restricted()
    assert not common.set_attr(obj, 'mode', 'INVALID')
    assert obj.mode == 'DEFAULT'
    assert not common.set_input(SimpleNamespace(inputs={'Color': obj}), 'Color', 'INVALID')
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2 and all(line.startswith('警告：') for line in lines)


def test_optional_settings_missing_and_valid(capsys):
    from types import SimpleNamespace
    obj = SimpleNamespace(samples=1)
    assert common.set_attr(obj, 'samples', 64)
    assert obj.samples == 64
    assert not common.set_attr(obj, 'missing', 1)
    assert not hasattr(obj, 'missing')
    socket = SimpleNamespace(default_value=0)
    node = SimpleNamespace(inputs={'Scale': socket}, outputs={'Fac': socket})
    assert common.set_input(node, 'Scale', 3.8)
    assert socket.default_value == 3.8
    assert not common.set_input(node, 'missing', 1)
    connected = []
    links = SimpleNamespace(new=lambda a, b: connected.append((a, b)))
    assert common.link_input(links, node, 'Fac', node, 'Scale')
    assert not common.link_input(links, node, 'Fac', node, 'missing')
    assert not common.link_input(links, node, 'missing', node, 'Scale')
    assert connected == [(socket, socket)]
    assert len(capsys.readouterr().out.splitlines()) == 4


@pytest.fixture
def render_module(monkeypatch):
    monkeypatch.setitem(sys.modules, 'common', common)
    render_spec = importlib.util.spec_from_file_location('render_shot_test', ROOT / 'blender/render_shot.py')
    module = importlib.util.module_from_spec(render_spec)
    render_spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('engine,metal', [('eevee', False), ('cycles', False), ('cycles', True)])
def test_engine_configuration_and_device_fallback(render_module, monkeypatch, capsys, engine, metal):
    from types import SimpleNamespace as NS
    devices = [NS(type='CPU', use=True)] + ([NS(type='METAL', use=False)] if metal else [])
    prefs = NS(compute_device_type='NONE', refresh_devices=lambda: None, devices=devices)
    monkeypatch.setitem(sys.modules, 'bpy', NS(context=NS(preferences=NS(addons={'cycles': NS(preferences=prefs)}))))
    scene = NS(render=NS(engine='', film_transparent=True, use_persistent_data=False),
               eevee=NS(taa_render_samples=1, use_raytracing=False),
               cycles=NS(samples=1, use_denoising=False, use_adaptive_sampling=False,
                         max_bounces=1, transparent_max_bounces=1, device='CPU'))
    # 故意缺少 denoiser；应警告并继续，不影响引擎和设备配置。
    result = render_module.configure_engine(scene, engine, 64)
    if engine == 'eevee':
        assert scene.render.engine == 'BLENDER_EEVEE'
        assert scene.eevee.taa_render_samples == 64 and scene.eevee.use_raytracing
        assert not scene.render.film_transparent
        assert capsys.readouterr().out == ''
    else:
        assert scene.render.engine == 'CYCLES'
        assert scene.cycles.samples == 64 and scene.cycles.use_denoising
        assert scene.cycles.device == ('GPU' if metal else 'CPU')
        assert result['device'] == ('Metal GPU' if metal else 'CPU')
        assert bool(result['warnings']) is not metal
        assert '警告：' in capsys.readouterr().out


def test_required_engine_failure_is_not_suppressed(render_module, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'bpy', SimpleNamespace())
    class BrokenRender:
        @property
        def engine(self):
            return ''

        @engine.setter
        def engine(self, value):
            raise TypeError('测试引擎不可用')

    with pytest.raises(TypeError, match='测试引擎不可用'):
        render_module.configure_engine(SimpleNamespace(render=BrokenRender()), 'eevee', 64)


def test_scene_settings_match_supplied_api(monkeypatch, capsys):
    from types import SimpleNamespace as NS
    from unittest.mock import MagicMock

    # 插槽名取自验收方清单；清单未覆盖的基础节点也显式列出，禁止自动补槽。
    inputs = {
        'ShaderNodeBsdfPrincipled': 'Base Color,Metallic,Roughness,Transmission Weight,IOR,Normal',
        'ShaderNodeTexNoise': 'Vector,Scale,Detail',
        'ShaderNodeTexWave': 'Vector,Scale',
        'ShaderNodeTexSky': 'Vector',
        'ShaderNodeVolumePrincipled': 'Density,Color',
        'ShaderNodeTexCoord': '',
        'ShaderNodeValToRGB': 'Fac',
        'ShaderNodeMapRange': 'Value,From Min,From Max,To Min,To Max',
        'ShaderNodeHueSaturation': 'Color,Saturation,Value',
        'ShaderNodeCameraData': '',
        'ShaderNodeNewGeometry': '',
        'ShaderNodeVectorMath': 'Vector,Vector,Vector',
        'ShaderNodeEmission': 'Color,Strength',
        'ShaderNodeMixShader': 'Fac,Shader,Shader',
        'ShaderNodeBump': 'Strength,Distance,Height',
        'ShaderNodeBackground': 'Color,Strength',
        'ShaderNodeOutputMaterial': 'Surface,Volume',
    }
    outputs = {
        'ShaderNodeBsdfPrincipled': 'BSDF', 'ShaderNodeTexNoise': 'Fac,Color',
        'ShaderNodeTexWave': 'Fac,Color', 'ShaderNodeTexSky': 'Color',
        'ShaderNodeVolumePrincipled': 'Volume', 'ShaderNodeTexCoord': 'Object',
        'ShaderNodeValToRGB': 'Color', 'ShaderNodeMapRange': 'Result',
        'ShaderNodeBump': 'Normal', 'ShaderNodeBackground': 'Background',
        'ShaderNodeOutputMaterial': '',
        'ShaderNodeHueSaturation': 'Color', 'ShaderNodeCameraData': 'View Distance',
        'ShaderNodeNewGeometry': 'Incoming', 'ShaderNodeVectorMath': 'Vector',
        'ShaderNodeEmission': 'Emission', 'ShaderNodeMixShader': 'Shader',
    }
    created = []

    class Sockets(dict):
        def __init__(self, names):
            self.ordered = [NS(default_value=None) for name in names if name]
            super().__init__(zip(names,self.ordered))

        def __getitem__(self, key):
            return self.ordered[key] if isinstance(key,int) else super().__getitem__(key)

    class Nodes(dict):
        def new(self, kind):
            node = NS(inputs=Sockets(inputs[kind].split(',')),
                      outputs={name: object() for name in outputs[kind].split(',') if name})
            if kind == 'ShaderNodeTexSky':
                node.sky_type = 'SINGLE_SCATTERING'
                for name in ('sun_elevation', 'sun_rotation', 'sun_disc', 'sun_intensity', 'sun_size',
                             'altitude', 'air_density', 'aerosol_density', 'ozone_density'):
                    setattr(node, name, 0)
            elif kind == 'ShaderNodeMapRange':
                node.clamp = False
            elif kind == 'ShaderNodeTexWave':
                node.wave_type, node.bands_direction = 'BANDS', 'X'
            elif kind == 'ShaderNodeValToRGB':
                node.color_ramp = NS(interpolation='LINEAR', elements=[NS(color=None, position=0), NS(color=None, position=1)])
            self[kind] = node
            created.append((kind, node))
            return node

    def new_material(name):
        nodes = Nodes()
        nodes['Principled BSDF'] = nodes.new('ShaderNodeBsdfPrincipled')
        nodes['Background'] = nodes.new('ShaderNodeBackground')
        nodes['Material Output'] = nodes.new('ShaderNodeOutputMaterial')
        return NS(use_nodes=False, node_tree=NS(nodes=nodes, links=NS(new=lambda a, b: None)))

    lights = []
    def new_light(name, kind):
        assert kind == 'SUN'
        light = NS(energy=0, angle=0, color=None, use_shadow=False)
        lights.append(light)
        return light

    scene = NS(view_settings=NS(view_transform='NONE', look='NONE', exposure=0))
    fake_bpy = NS(context=NS(scene=scene, collection=NS(objects=NS(link=lambda obj: None)),
                             object=NS(data=NS(materials=[]))),
                  data=NS(materials=NS(new=new_material), worlds=NS(new=new_material),
                          lights=NS(new=new_light), objects=NS(new=lambda name, data: NS())),
                  ops=NS(mesh=NS(primitive_cube_add=lambda **kwargs: None)))
    monkeypatch.setitem(sys.modules, 'bpy', fake_bpy)
    monkeypatch.setitem(sys.modules, 'mathutils', NS(Vector=MagicMock()))
    monkeypatch.setitem(sys.modules, 'crane', NS(Geometry=MagicMock()))
    monkeypatch.setitem(sys.modules, 'common', common)
    scene_spec = importlib.util.spec_from_file_location('scene_test', ROOT / 'blender/scene.py')
    module = importlib.util.module_from_spec(scene_spec)
    scene_spec.loader.exec_module(module)
    mats = module.materials()
    module.environment(common.derive_dimensions({}), mats)
    sky = next(node for kind, node in created if kind == 'ShaderNodeTexSky')
    assert sky.sky_type == 'MULTIPLE_SCATTERING'
    # 保留 API 兼容检查，验证新版天空与远景渐隐。
    assert sky.aerosol_density == 2.0 and sky.ozone_density == 1.0 and sky.sun_disc
    assert sky.sun_intensity == 1 and sky.sun_elevation == pytest.approx(math.radians(13))
    assert sky.sun_rotation == pytest.approx(math.radians(35-65-90))
    assert sky.sun_size == pytest.approx(math.radians(.6))
    assert lights[0].energy == 1.6 and lights[0].use_shadow
    assert lights[0].angle == pytest.approx(math.radians(.6))
    assert scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value == .7
    assert not any(kind == 'ShaderNodeVolumePrincipled' for kind, _ in created)
    assert mats['glass'].node_tree.nodes['Principled BSDF'].inputs['Transmission Weight'].default_value == .92
    assert scene.view_settings.view_transform == 'AgX'
    assert scene.view_settings.look == 'AgX - Medium High Contrast'
    assert scene.view_settings.exposure == 0
    for name in ('concrete','seam'):
        fade = mats[name].node_tree.nodes['ShaderNodeMapRange']
        assert fade.inputs['From Min'].default_value == 500
        assert fade.inputs['From Max'].default_value == 3000
        assert fade.clamp
    assert 'ShaderNodeEmission' not in mats['hull'].node_tree.nodes
    assert mats['hull'].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value == (
        *module.linear_hex('#7A3B2A'),1)
    assert mats['warehouse'].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value == (
        *module.linear_hex('#4F5965'),1)
    assert capsys.readouterr().out == ''

    # 船段有平底、半径 4 m 舭部与垂直舷侧；几何尺寸独立于门机参数。
    profile = module.hull_profile()
    assert min(z for z,y in profile) == -11 and max(z for z,y in profile) == 11
    assert min(y for z,y in profile) == 0 and max(y for z,y in profile) == 14
    assert (-7,0) == pytest.approx(profile[13])
    assert (7,0) in profile
    for z,y in profile:
        if 0 < y < 4:
            assert math.hypot(abs(z)-7, y-4) == pytest.approx(4)
    geometry = sys.modules['crane'].Geometry.return_value
    shell = next(call for call in geometry.mesh.call_args_list if call.args[0] == 'hull')
    vertices = shell.args[2]
    assert tuple(max(p[i] for p in vertices)-min(p[i] for p in vertices) for i in range(3)) == pytest.approx((36,14,22))
    assert min(p[1] for p in vertices) == pytest.approx(1.2)
    assert (max(p[2] for p in vertices)+min(p[2] for p in vertices))/2 == -15
    supports = [call for call in geometry.box.call_args_list if call.args[0] == 'hull_support']
    assert len(supports) == 6
    assert all(call.args[1][1] == 1.2 and call.args[2][1] == .6 for call in supports)
    assert len([call for call in geometry.mesh.call_args_list if call.args[0] == 'hull_bulkheads']) == 3
    water = next(call for call in geometry.box.call_args_list if call.args[0] == 'water')
    assert water.args[1] == (60,.05,120)
    assert water.args[2][2] == 0
    ground = next(call for call in geometry.mesh.call_args_list if call.args[0] == 'ground')
    vertices = ground.args[2]
    assert all(math.hypot(v[0],v[2]) == pytest.approx(8000) for v in vertices[1::2])
    assert all(abs(v[0]-water.args[2][0]) == pytest.approx(30) or abs(v[2]) == pytest.approx(60)
               for v in vertices[::2])
    bed = next(c for c in geometry.box.call_args_list if c.args[0] == 'transport_flatbed')
    wheels = [c for c in geometry.cylinder.call_args_list if c.args[0] == 'transport_wheels']
    assert len(wheels) == 6
    for wheel in wheels:
        start,end,radius = wheel.args[1:4]
        assert start[1]-radius == pytest.approx(0)
        assert start[1]+radius < bed.args[2][1]-bed.args[1][1]/2
        assert all(abs(p[2]-bed.args[2][2]) < bed.args[1][2]/2 for p in (start,end))
    assert any(c.args[0] == 'transport_windscreen' and c.args[3] == 'glass'
               for c in geometry.box.call_args_list)
    foundations = [c for c in geometry.box.call_args_list if c.args[0] == 'foundation']
    assert len(foundations) == 2 and all(c.args[1][0] == 1.2 for c in foundations)
    assert mats['rail_top'].node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value == .25
    assert mats['rail_top'].node_tree.nodes['Principled BSDF'].inputs['Metallic'].default_value == 1
    plates = [c for c in geometry.box.call_args_list if c.args[0] == 'steel_plates']
    assert len(plates) == 18
    assert all(c.args[1][0] == 12 and c.args[1][2] == 3 for c in plates)
    factories = [c for c in geometry.box.call_args_list if c.args[3].startswith('warehouse_')]
    assert len(factories) == 14
    assert all(12 <= c.args[1][1]+3 <= 28 for c in factories)
    assert all(250 <= math.hypot(c.args[2][0],c.args[2][2]) <= 600 for c in factories)



@pytest.mark.parametrize('values', [{}, {'F_girder_length':120,'F_overall_height':65,'F_span':100}])
@pytest.mark.parametrize('time_s', [0,.5,3,5.5,6])
@pytest.mark.parametrize('size', [(1920,1080),(960,540)])
def test_hero_camera_fits_safe_frame_with_physical_lens(values, time_s, size):
    import numpy as np

    dim = common.derive_dimensions(facts(**values))
    points = common.framing_points(dim)
    camera, target = common.hero_camera(dim,{},time_s,6,*size,points)
    assert camera[1] == 8
    assert target[0] == target[2] == 0
    assert math.degrees(math.atan2(camera[0],camera[2])) == pytest.approx(
        23+24*common.ease(time_s/6))
    assert target[1] > camera[1]
    # 独立针孔矩阵：30 mm 焦距 / 36 mm 水平传感器，不依赖被测投影函数。
    forward = np.array(target)-np.array(camera)
    forward /= np.linalg.norm(forward)
    right = np.cross(forward,[0,1,0])
    right /= np.linalg.norm(right)
    up = np.cross(right,forward)
    view = (np.array(points)-camera) @ np.array([right,up,forward]).T
    assert (view[:,2] > 0).all()
    screen_x = .5 + view[:,0]/view[:,2]*30/36
    screen_y = .5 - view[:,1]/view[:,2]*30/36*size[0]/size[1]
    assert screen_x.max()-screen_x.min() <= .82+1e-9
    assert screen_y.max()-screen_y.min() <= .78+1e-9
    assert .82 <= screen_y.max() <= .86
    assert screen_y.max() == pytest.approx(.84)
    assert min(screen_x.min(),screen_y.min()) >= .06-1e-9
    assert max(screen_x.max(),screen_y.max()) <= .94+1e-9
    # 最近距离至少触及一个宽度或上沿约束，竖直构图优先。
    assert max((screen_x.max()-screen_x.min())/.82,
               (.5-screen_x.min())/.44,(screen_x.max()-.5)/.44,
               (.84-screen_y.min())/.78) == pytest.approx(1)
    projected_y = [common.project_point(p,camera,target,*size,common.hero_fov_y(*size))['y'] for p in points]
    assert projected_y == pytest.approx(screen_y*size[1])
    projected = [common.project_point(p,camera,target,*size,common.hero_fov_y(*size)) for p in points]
    assert [p['x'] for p in projected] == pytest.approx(screen_x*size[0])
    assert common.hero_fov_y(*size) == pytest.approx(37.2990775081,abs=1e-9)


def test_hero_camera_solves_custom_outline_and_ignores_legacy_distance():
    dim = common.derive_dimensions({})
    outline = [(-40,dim.height*.45,0),(40,dim.height*.45,0)]
    camera, target = common.hero_camera(dim,{'from_deg':-35,'to_deg':-35,'distance':100},3,6,points=outline)
    reference, _ = common.hero_camera(dim,{'from_deg':-35,'to_deg':-35},3,6,points=outline)
    assert camera == reference
    assert math.degrees(math.atan2(camera[0],camera[2])) == pytest.approx(23)
    projected = [common.project_point(p,camera,target,1920,1080,common.hero_fov_y(1920,1080)) for p in outline]
    assert all(p['in_frame'] for p in projected)
    assert (max(p['x'] for p in projected)-min(p['x'] for p in projected))/1920 <= .82+1e-9


@pytest.mark.parametrize('params,duration', [({'from_deg':float('nan')},6),
    ({'to_deg':float('inf')},6), ({},0)])
def test_hero_camera_rejects_invalid_orbit(params,duration):
    with pytest.raises(ValueError):
        common.hero_camera(common.derive_dimensions({}),params,0,duration)


def test_batch_stills_arguments_and_names(render_module):
    base = ['--facts','sample.json','--shot-json','{}','--out','example']
    args = render_module.arguments(base+['--stills','0.5,3,5.5'])
    assert args.stills == [.5,3,5.5]
    assert [render_module.frame_filename(args,i,t) for i,t in enumerate(args.stills,1)] == [
        'still_eevee_0.5.png','still_eevee_3.png','still_eevee_5.5.png']
    args = render_module.arguments(base+['--engine','cycles','--still-at','3'])
    assert render_module.frame_filename(args,1,3) == 'still_cycles.png'
    args = render_module.arguments(base)
    assert render_module.frame_filename(args,1,0) == 'frame_00001.jpg'


@pytest.mark.parametrize('options', [['--stills','nan'],['--stills','7'],['--stills','-1'],
    ['--stills',''],['--stills','1,'],['--stills','1,1.0'],['--stills','1','--still-at','1']])
def test_batch_stills_reject_invalid_times(render_module, options):
    with pytest.raises(SystemExit):
        render_module.arguments(['--facts','sample.json','--shot-json','{}','--out','example']+options)


def test_enclosing_corners_are_conservative():
    points = [(-50,10,-10),(40,50,6),(0,0,2)]
    corners = common.enclosing_corners(points)
    assert len(corners) == 8
    assert (-50,50,6) in corners and (40,0,-10) in corners


def test_display_meter_excludes_background_and_uses_encoded_values():
    pixels = [1,1,1,0, .2,.2,.2,1, .4,.4,.4,1, .6,.6,.6,.51, 1,1,1,.5]
    stats = common.display_luminance(pixels)
    assert stats['pixel_count'] == 3
    assert stats['median'] == pytest.approx(.4)
    assert stats['p98'] == pytest.approx(.592)
    with pytest.raises(ValueError, match='测光失败'):
        common.display_luminance([1,1,1,0])


@pytest.mark.parametrize('offset', [-10,0,12])
def test_exposure_solver_handles_nonlinear_saturated_display(offset):
    def measure(exposure):
        value = 2**(exposure+offset)
        return {'median':value/(1+value), 'p98':value*3/(1+value*3), 'pixel_count':200}
    exposure, stats = common.solve_exposure(measure)
    assert stats['median'] == pytest.approx(.42,abs=.001)
    assert stats['p98'] <= .92
    assert exposure == pytest.approx(math.log2(.42/.58)-offset,abs=.01)
    assert not stats['highlight_limited']


def test_exposure_solver_prioritizes_highlight_ceiling():
    def measure(exposure):
        value = 2**exposure
        return {'median':value/(1+value), 'p98':value*100/(1+value*100)}
    exposure, stats = common.solve_exposure(measure)
    assert stats['highlight_limited']
    assert stats['p98'] == pytest.approx(.92,abs=.001)
    assert stats['median'] < .42
    assert measure(exposure)['median'] == stats['median']


@pytest.mark.parametrize('engine', ['CYCLES','BLENDER_EEVEE'])
@pytest.mark.parametrize('fail', [False,True])
def test_meter_uses_display_transform_and_restores_scene(render_module, monkeypatch, engine, fail):
    from types import SimpleNamespace as NS

    subject = NS(type='MESH', hide_render=False, as_pointer=lambda:1)
    background = NS(type='MESH', hide_render=False, as_pointer=lambda:2)
    hidden = NS(type='MESH', hide_render=True, as_pointer=lambda:3)
    light = NS(type='LIGHT', hide_render=False)
    settings = NS(file_format='JPEG', color_mode='RGB', color_depth='8')
    render = NS(engine=engine, resolution_x=1920, resolution_y=1080, resolution_percentage=100,
                film_transparent=False, image_settings=settings, filepath='正式帧.png')
    scene = NS(render=render, cycles=NS(samples=64,use_adaptive_sampling=True),
               eevee=NS(taa_render_samples=64),view_settings=NS(exposure=0),
               objects=[subject,background,hidden,light])
    rendered, saved, loaded, removed = [],[],[],[]

    def render_probe(**kwargs):
        assert kwargs == {'write_still':False}
        assert scene.render.engine == engine
        assert (render.resolution_x,render.resolution_y,render.film_transparent) == (192,108,True)
        assert (settings.color_mode,settings.color_depth) == ('RGBA','16')
        assert background.hide_render and hidden.hide_render
        assert not subject.hide_render and not light.hide_render
        assert (scene.cycles.samples if engine == 'CYCLES' else scene.eevee.taa_render_samples) == 8
        rendered.append(True)

    def save_render(path, *, scene):
        from pathlib import Path
        saved.append((path,scene.view_settings.exposure))
        Path(path).touch()

    class Image:
        def __init__(self):
            self.colorspace_settings = NS(name='sRGB')

        @property
        def pixels(self):
            assert self.colorspace_settings.name == 'Non-Color'
            if fail:
                raise RuntimeError('模拟读取失败')
            value = 2**(saved[-1][1]+8)
            value /= 1+value
            return [value,value,value,1, 1,1,1,0]

    def load(path, check_existing):
        assert not check_existing and path == saved[-1][0]
        image = Image()
        loaded.append(image)
        return image

    images = NS(get=lambda name:NS(save_render=save_render),load=load,remove=removed.append)
    monkeypatch.setitem(sys.modules,'bpy',NS(data=NS(images=images),
        context=NS(view_layer=NS(update=lambda:None)),ops=NS(render=NS(render=render_probe))))
    if fail:
        with pytest.raises(RuntimeError,match='模拟读取失败'):
            render_module.meter_exposure(scene,[subject])
        assert scene.view_settings.exposure == 0
    else:
        report = render_module.meter_exposure(scene,[subject])
        assert report['median'] == pytest.approx(.42,abs=.001)
        assert scene.view_settings.exposure == report['exposure']
    assert len(rendered) == 1
    assert loaded == removed
    from pathlib import Path
    assert all(not Path(path).exists() for path,_ in saved)
    assert (render.resolution_x,render.resolution_y,render.film_transparent) == (1920,1080,False)
    assert (settings.color_mode,settings.color_depth) == ('RGB','8')
    assert render.filepath == '正式帧.png'
    assert scene.cycles.samples == scene.eevee.taa_render_samples == 64
    assert scene.cycles.use_adaptive_sampling
    assert not subject.hide_render and not background.hide_render and hidden.hide_render


@pytest.mark.parametrize('size,expected', [((1920,1080),(1120,380)),
    ((960,540),(560,190)), ((1080,1920),(700,800))])
def test_auto_sensor_known_pinhole_projection(size, expected):
    projection = common.project_point((1,1,0),(0,0,10),(0,0,0),*size,common.hero_fov_y(*size))
    assert (projection['x'],projection['y']) == pytest.approx(expected)
    assert projection['in_frame']
    assert not common.project_point((0,0,11),(0,0,10),(0,0,0),*size,
                                    common.hero_fov_y(*size))['in_frame']


@pytest.mark.parametrize('values', [[0,.2,.1,-.1,0], [0,8,-4,6,2]])
def test_animation_exposure_has_no_overshoot_or_frame_jumps(values):
    samples = [(i*1.5,v) for i,v in enumerate(values)]
    curve = common.exposure_curve(samples,30)
    assert all(ev <= raw for (_,ev),raw in zip(curve,values))
    frames = [common.interpolate_exposure(curve,t) for t in common.frame_times(6,30)]
    assert len(frames) == 180
    assert max(abs(b-a) for a,b in zip(frames,frames[1:])) <= .02+1e-12
    for t,ev in curve:
        assert common.interpolate_exposure(curve,t) == pytest.approx(ev)
    if max(values)-min(values) < .9:
        assert curve == samples


@pytest.mark.parametrize('engine,samples', [('eevee',32),('cycles',64)])
def test_preview_halves_resolution_and_only_realtime_samples(render_module, engine, samples):
    args = render_module.arguments(['--facts','f.json','--shot-json','{}','--out','frames',
                                    '--preview','--engine',engine])
    assert (args.width,args.height,args.samples) == (960,540,samples)


def test_video_command_overrides_executable_and_limits_frame_count(render_module, monkeypatch, tmp_path):
    from types import SimpleNamespace as NS
    monkeypatch.setenv('KEPU_FFMPEG','/自定义工具/encoder')
    monkeypatch.setattr(render_module.shutil,'which',lambda path: path)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs == {'capture_output':True,'text':True,'check':False}
        (tmp_path/'orbit.mp4').touch()
        return NS(returncode=0,stderr='')
    monkeypatch.setattr(render_module.subprocess,'run',run)
    result = render_module.compose_video(tmp_path,30,180)
    assert result['status'] == 'ok'
    command = calls[0]
    assert command[0] == '/自定义工具/encoder'
    for key,value in [('-framerate','30'),('-start_number','1'),('-frames:v','180'),
                      ('-c:v','libx264'),('-pix_fmt','yuv420p'),('-crf','18')]:
        assert command[command.index(key)+1] == value
    assert str(tmp_path/'frame_%05d.png') in command


def test_video_missing_tool_skips_and_encoder_failure_is_reported(render_module, monkeypatch, tmp_path, capsys):
    from types import SimpleNamespace as NS
    monkeypatch.setattr(render_module.shutil,'which',lambda path: None)
    assert render_module.compose_video(tmp_path,30,180)['status'] == 'skipped'
    assert '提示：未找到' in capsys.readouterr().out
    monkeypatch.setattr(render_module.shutil,'which',lambda path: '/encoder')
    monkeypatch.setattr(render_module.subprocess,'run',lambda *a,**kw: NS(returncode=1,stderr='模拟编码失败'))
    with pytest.raises(RuntimeError,match='视频合成失败.*模拟编码失败'):
        render_module.compose_video(tmp_path,30,180)


def test_anchors_use_runtime_projection_and_only_frame_visibility(render_module, monkeypatch):
    from types import SimpleNamespace as NS
    import numpy as np
    class Vector(np.ndarray):
        def __new__(cls, values):
            return np.asarray(values,dtype=float).view(cls)
        x = property(lambda self: float(self[0]))
        y = property(lambda self: float(self[1]))
        z = property(lambda self: float(self[2]))
    scene = NS(render=NS(resolution_x=960,resolution_y=540,resolution_percentage=100),camera=object())
    monkeypatch.setitem(sys.modules,'bpy',NS(context=NS(evaluated_depsgraph_get=lambda: 'graph')))
    monkeypatch.setattr(render_module,'part_objects',lambda parent: [parent])
    monkeypatch.setattr(render_module,'bounds',lambda objects,graph: (Vector((2,4,6)),Vector((4,6,8))))
    projections = iter([(0.25,.75,10),(-.1,.5,10),(.5,.5,-1),(0,1,10),(.5,.5,0),(1.1,.5,10)])
    centers = []
    def project(actual_scene, camera, center):
        assert actual_scene is scene and camera is scene.camera
        centers.append(tuple(center))
        return NS(**dict(zip('xyz',next(projections))))
    monkeypatch.setitem(sys.modules,'bpy_extras.object_utils',NS(world_to_camera_view=project))
    result = render_module.anchors(scene,{name:name for name in common.ANCHOR_NODES})
    assert centers == [(3,5,7)]*6
    assert result['girder'] == {'x':240,'y':135,'visible':True,'in_frame':True,'center_m':(3,7,-5)}
    assert [result[name]['visible'] for name in common.ANCHOR_NODES] == [True,False,False,True,False,False]
    assert result['hoist_hook']['x'] is None


@pytest.mark.parametrize('options,count,video', [([],180,True),
    (['--stills','0.5,3,5.5','--preview'],3,False),(['--still-at','3'],1,False),
    (['--duration','1.25','--skip-video'],38,False)])
@pytest.mark.parametrize('shot', [{'kind':'model_orbit'}, {'kind':'title'},
    *({'kind':'motion','params':{'axis':axis,'from_m':5,'to_m':20}} for axis in ('trolley','hoist','gantry'))])
def test_render_orchestration_meters_five_times_and_exports_all_frames(
        render_module, monkeypatch, tmp_path, capsys, options, count, video, shot):
    from types import SimpleNamespace as NS
    import numpy as np
    class Vector(np.ndarray):
        def __new__(cls, values):
            return np.asarray(values,dtype=float).view(cls)
        x = property(lambda self: float(self[0]))
        y = property(lambda self: float(self[1]))
        z = property(lambda self: float(self[2]), lambda self, value: self.__setitem__(2, value))
        def to_track_quat(self, *args):
            return NS(to_euler=lambda: tuple(self))
    class Identity:
        def copy(self):
            return self
        def __matmul__(self, value):
            return value
    camera = NS()
    settings = NS()
    scene = NS(render=NS(image_settings=settings), view_settings=NS(exposure=0), frame_set=lambda _: None)
    dim = common.derive_dimensions({})
    obj = NS(matrix_world=Identity(),bound_box=[common.to_blender(p) for p in common.framing_points(dim)])
    obj.evaluated_get = lambda graph: obj
    parents = {name:NS(matrix_world=Identity(),location=Vector((0,0,0)),scale=NS(z=1)) for name in common.NODES}
    rendered = []
    def render(**kwargs):
        assert kwargs == {'write_still':True}
        assert settings.quality == 92
        assert settings.file_format == ('JPEG' if scene.render.filepath.endswith('.jpg') else 'PNG')
        rendered.append(scene.view_settings.exposure)
        from pathlib import Path
        Path(scene.render.filepath).write_bytes(b'frame')
    fake = NS(context=NS(scene=scene,view_layer=NS(update=lambda:None),
                        evaluated_depsgraph_get=lambda:None,collection=NS(objects=NS(link=lambda _:None))),
              data=NS(cameras=NS(new=lambda _:NS()),objects=NS(new=lambda *a:camera)),
              ops=NS(object=NS(select_all=lambda **kw:None,delete=lambda **kw:None),render=NS(render=render)))
    monkeypatch.setitem(sys.modules,'bpy',fake)
    monkeypatch.setitem(sys.modules,'mathutils',NS(Vector=Vector))
    monkeypatch.setitem(sys.modules,'crane',NS(build_crane=lambda *a:parents))
    monkeypatch.setitem(sys.modules,'scene',NS(environment=lambda *a:None,materials=lambda:{}))
    monkeypatch.setattr(render_module,'part_objects',lambda parent:[obj])
    monkeypatch.setattr(render_module,'bounds',lambda *a:(Vector((-dim.length/2,-60,0)),Vector((dim.length/2,60,dim.height))))
    monkeypatch.setattr(render_module,'read_facts',lambda _: {})
    monkeypatch.setattr(render_module,'configure_engine',lambda *a:{'warnings':[],'device':'模拟设备'})
    meters = []
    def meter(*args):
        meters.append(tuple(camera.location))
        return {'exposure':[0,.2,.1,-.1,0][len(meters)-1],'median':.42,'p98':.8}
    monkeypatch.setattr(render_module,'meter_exposure',meter)
    monkeypatch.setattr(render_module,'anchors',lambda *a:{n:{'x':1,'y':2,'visible':True} for n in common.ANCHOR_NODES})
    encoded = []
    monkeypatch.setattr(render_module,'compose_video',lambda *a:encoded.append(a) or {'status':'ok'})
    render_module.main(['--facts','facts.json','--shot-json',json.dumps(shot),
                        '--out',str(tmp_path),*options])
    payload = json.loads((tmp_path/'anchors.json').read_text())
    report = json.loads((tmp_path/'render_eevee.json').read_text())
    assert len(meters) == 5
    duration = 1.25 if '--duration' in options else 6
    assert [m['time_s'] for m in report['metering_frames']] == [duration*i/4 for i in range(5)]
    assert len(payload['frames']) == len(report['camera_frames']) == len(rendered) == count
    assert all((tmp_path/f['file']).is_file() and len(f['nodes']) == 6 for f in payload['frames'])
    assert [f['exposure'] for f in payload['frames']] == rendered
    if shot['kind'] == 'model_orbit':
        assert all(f['projected_bounds_px']['bottom']/report['resolution'][1] == pytest.approx(.84)
                   for f in report['camera_frames'])
    assert all(not f['cropped'] for f in report['camera_frames'])
    assert bool(encoded) is video
    if video:
        assert encoded == [(tmp_path,30,180,'jpg')]
        assert payload['frames'][0]['file'] == 'frame_00001.jpg'
        assert payload['frames'][-1]['file'] == 'frame_00180.jpg'
        assert payload['frames'][-1]['time_s'] == 179/30
        assert max(abs(b-a) for a,b in zip(rendered,rendered[1:])) <= .02
        progress = [line for line in capsys.readouterr().out.splitlines() if '预计剩余' in line]
        assert len(progress) == 18 and '第 180/180 帧' in progress[-1]
    if '--preview' in options:
        assert (payload['width'],payload['height']) == (960,540)


@pytest.mark.parametrize('size', [(1920,1080),(960,540)])
def test_title_framing_and_six_percent_push(size):
    dim = common.derive_dimensions({})
    width,height = size
    points = common.framing_points(dim)
    start,target,_ = common.title_camera(dim,0,*size)
    end,_,_ = common.title_camera(dim,6,*size)
    assert math.dist(end,target)/math.dist(start,target) == pytest.approx(.94)
    assert math.degrees(math.atan2(start[0]-target[0],start[2]-target[2])) == pytest.approx(23)
    for t in (0,1,3,6,10):
        camera,target,(dx,dy) = common.title_camera(dim,t,*size)
        pts = [common.project_point(p,camera,target,width,height,common.hero_fov_y(*size)) for p in points]
        xs,ys = [p['x']/width+dx for p in pts],[p['y']/height+dy for p in pts]
        assert (max(xs)+min(xs))/2 == pytest.approx(.70)
        assert (max(ys)+min(ys))/2 == pytest.approx(.56)
        assert all(0 <= v <= 1 for v in xs+ys)
        if t == 0:
            assert max(xs)-min(xs) == pytest.approx(.5)


@pytest.mark.parametrize('axis', ['trolley','hoist','gantry'])
@pytest.mark.parametrize('t,weight', [(0,0),(1,.0625),(2,.5),(3,.9375),(4,1)])
def test_motion_matches_player_and_rope_endpoints(axis,t,weight):
    dim = common.derive_dimensions({})
    params = {'axis':axis,'from_m':5,'to_m':20}
    state = common.motion_state(dim,params,t,4)
    value = 5+15*weight
    assert state['value'] == pytest.approx(value)
    assert state['trolley_x'] == (value if axis == 'trolley' else 0)
    assert state['hook_height'] == (value if axis == 'hoist' else dim.hook_height)
    assert state['crane'] == (0,0,value if axis == 'gantry' else 0)
    top,old_bottom = dim.girder_top+1,dim.hook_height+3.9
    transform = lambda y: dim.girder_top+(y-dim.girder_top)*state['rope_scale']+state['rope_offset']
    assert transform(top) == pytest.approx(top)
    assert transform(old_bottom) == pytest.approx(state['hook_height']+3.9)
    camera,target = common.motion_camera(dim,state['crane'])
    assert camera[1] == 8 and target[0] == 10 and target[1] == dim.height/2
    base_camera,base_target = common.motion_camera(dim)
    assert tuple(p-d for p,d in zip(camera,state['crane'])) == pytest.approx(base_camera)
    assert tuple(p-d for p,d in zip(target,state['crane'])) == pytest.approx(base_target)
    assert math.degrees(math.atan2(camera[0]-target[0],camera[2]-target[2])) == pytest.approx(24)


def test_frame_format_png_is_optional(render_module):
    args = render_module.arguments(['--facts','f','--shot-json','{}','--out','frames','--frame-format','png'])
    assert render_module.frame_filename(args,1,0) == 'frame_00001.png'
