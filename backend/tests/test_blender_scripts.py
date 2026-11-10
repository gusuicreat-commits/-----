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
    scene = NS(render=NS(engine='', film_transparent=True, use_persistent_data=False,use_motion_blur=True),
               eevee=NS(taa_render_samples=1, use_raytracing=True,use_fast_gi=False,fast_gi_quality=1,fast_gi_ray_count=8,fast_gi_step_count=16),
               cycles=NS(samples=1, use_denoising=False, use_adaptive_sampling=False,
                         max_bounces=1, transparent_max_bounces=1, device='CPU'))
    # 故意缺少 denoiser；应警告并继续，不影响引擎和设备配置。
    result = render_module.configure_engine(scene, engine, 64)
    if engine == 'eevee':
        assert scene.render.engine == 'BLENDER_EEVEE'
        assert scene.eevee.taa_render_samples == 24 and not scene.eevee.use_raytracing
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
        'ShaderNodeBsdfPrincipled': 'Base Color,Metallic,Roughness,Transmission Weight,IOR,Normal,Coat Weight,Coat Roughness',
        'ShaderNodeTexNoise': 'Vector,Scale,Detail,Roughness',
        'ShaderNodeAmbientOcclusion': 'Color,Distance,Normal',
        'ShaderNodeMath': 'Value,Value,Value',
        'ShaderNodeMixRGB': 'Fac,Color1,Color2',
        'ShaderNodeTexVoronoi': 'Vector,Scale',
        'ShaderNodeBsdfTransparent': 'Color',
        'ShaderNodeTexWave': 'Vector,Scale',
        'ShaderNodeTexSky': 'Vector',
        'ShaderNodeVolumePrincipled': 'Density,Color',
        'ShaderNodeTexCoord': '',
        'ShaderNodeValToRGB': 'Fac',
        'ShaderNodeMapRange': 'Value,From Min,From Max,To Min,To Max',
        'ShaderNodeHueSaturation': 'Color,Saturation,Value',
        'ShaderNodeCameraData': '',
        'ShaderNodeNewGeometry': '',
        'ShaderNodeVectorMath': 'Vector,Vector,Vector,Scale',
        'ShaderNodeSeparateXYZ': 'Vector','ShaderNodeVectorTransform': 'Vector','ShaderNodeLightPath': '',
        'ShaderNodeEmission': 'Color,Strength',
        'ShaderNodeMixShader': 'Fac,Shader,Shader',
        'ShaderNodeBump': 'Strength,Distance,Height',
        'ShaderNodeBackground': 'Color,Strength',
        'ShaderNodeOutputMaterial': 'Surface,Volume',
    }
    outputs = {
        'ShaderNodeAmbientOcclusion': 'Color,AO', 'ShaderNodeMath': 'Value',
        'ShaderNodeMixRGB': 'Color', 'ShaderNodeTexVoronoi': 'Distance,Color,Position',
        'ShaderNodeBsdfTransparent': 'BSDF',
        'ShaderNodeBsdfPrincipled': 'BSDF', 'ShaderNodeTexNoise': 'Fac,Color',
        'ShaderNodeTexWave': 'Fac,Color', 'ShaderNodeTexSky': 'Color',
        'ShaderNodeVolumePrincipled': 'Volume', 'ShaderNodeTexCoord': 'Object,Generated',
        'ShaderNodeValToRGB': 'Color', 'ShaderNodeMapRange': 'Result',
        'ShaderNodeBump': 'Normal', 'ShaderNodeBackground': 'Background',
        'ShaderNodeOutputMaterial': '',
        'ShaderNodeHueSaturation': 'Color', 'ShaderNodeCameraData': 'View Distance',
        'ShaderNodeNewGeometry': 'Incoming', 'ShaderNodeVectorMath': 'Vector',
        'ShaderNodeEmission': 'Emission', 'ShaderNodeMixShader': 'Shader',
        'ShaderNodeSeparateXYZ': 'X,Y,Z','ShaderNodeVectorTransform': 'Vector','ShaderNodeLightPath': 'Is Camera Ray',
    }
    created = []

    class Sockets(dict):
        def __init__(self, names):
            self.ordered = [NS(default_value=None,links=[],driver_add=lambda _:NS(driver=NS(variables=NS(new=lambda:NS(targets=[NS()]))))) for name in names if name]
            super().__init__(zip(names,self.ordered))

        def __getitem__(self, key):
            return self.ordered[key] if isinstance(key,int) else super().__getitem__(key)

    class Nodes(dict):
        def new(self, kind):
            node = NS(inputs=Sockets(inputs[kind].split(',')),
                      outputs=Sockets(outputs[kind].split(',')))
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
                class Elements(list):
                    def new(self,position):
                        element = NS(color=None,position=position)
                        self.append(element)
                        return element
                node.color_ramp = NS(interpolation='LINEAR', elements=Elements([NS(color=None, position=0), NS(color=None, position=1)]))
            self[kind] = node
            created.append((kind, node))
            return node

    def new_material(name):
        nodes = Nodes()
        nodes['Principled BSDF'] = nodes.new('ShaderNodeBsdfPrincipled')
        nodes['Background'] = nodes.new('ShaderNodeBackground')
        nodes['Material Output'] = nodes.new('ShaderNodeOutputMaterial')
        return NS(use_nodes=False, surface_render_method="DITHERED", sun_threshold=0, use_sun_shadow=True,
                  node_tree=NS(nodes=nodes, links=NS(new=lambda a,b:b.links.append(NS(from_socket=a)))))

    lights = []
    def new_light(name, kind):
        assert kind == 'SUN'
        light = NS(energy=0, angle=0, color=None, use_shadow=False, use_shadow_jitter=False)
        lights.append(light)
        return light

    scene = NS(view_settings=NS(view_transform='NONE', look='NONE', exposure=0),eevee=NS(use_shadows=False))
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
    assert sky.aerosol_density == 1.2 and sky.ozone_density == 1.0 and not sky.sun_disc
    assert sky.sun_intensity == 1 and sky.sun_elevation == pytest.approx(math.radians(24))
    assert sky.sun_rotation == pytest.approx(math.radians(35-110-90))
    assert sky.sun_size == pytest.approx(math.radians(.6))
    assert lights[0].energy == 5.5 and lights[0].use_shadow
    assert lights[0].angle == pytest.approx(math.radians(.8))
    assert lights[0].use_shadow_jitter
    assert scene.eevee.use_shadows
    assert scene.world.sun_threshold == 1e10 and not scene.world.use_sun_shadow
    assert mats['paint'].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value == (
        *module.linear_hex('#D9461C'), 1)
    assert scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value == .55
    assert not any(kind == 'ShaderNodeVolumePrincipled' for kind, _ in created)
    assert mats['glass'].node_tree.nodes['Principled BSDF'].inputs['Transmission Weight'].default_value == .92
    assert scene.view_settings.view_transform == 'AgX'
    assert scene.view_settings.look == 'AgX - Punchy'
    assert scene.view_settings.exposure == 0
    for name in ('concrete','seam'):
        assert 'ShaderNodeEmission' not in mats[name].node_tree.nodes
    assert mats['concrete'].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value == (
        *module.linear_hex('#9C968C'),1)
    assert 'ShaderNodeEmission' not in mats['hull'].node_tree.nodes
    assert mats['hull'].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value == (
        *module.linear_hex('#7A3B2A'),1)
    assert mats['warehouse'].node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value == (
        *module.linear_hex('#E5E7E7'),1)
    for key in ('paint','red'):
        shader = mats[key].node_tree.nodes['Principled BSDF']
        assert shader.inputs['Base Color'].default_value == (*module.linear_hex('#D9461C'),1)
        assert shader.inputs['Coat Weight'].default_value == .25
        assert shader.inputs['Roughness'].default_value == .32
    assert mats['window'].node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value == .05
    module.Geometry.reset_mock()
    module.environment(common.derive_dimensions({}),mats,35,'dusk')
    dusk = scene.world.node_tree.nodes['ShaderNodeTexSky']
    assert dusk.sun_elevation == pytest.approx(math.radians(13))
    assert dusk.aerosol_density == 2.0
    assert scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value == .7
    assert scene.view_settings.look == 'AgX - Medium High Contrast'
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
    factories = [c for c in geometry.box.call_args_list if c.args[0].startswith('decor_factory_') and c.args[3] == 'warehouse']
    assert len(factories) == 3
    assert all(30 <= c.args[1][1] <= 40 and 120 <= c.args[1][0] <= 180 for c in factories)
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
        assert report['median'] == pytest.approx(.44,abs=.001)
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


@pytest.mark.parametrize('engine,samples', [('eevee',12),('cycles',64)])
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
    monkeypatch.setitem(sys.modules,'mathutils',NS(Vector=Vector))
    monkeypatch.setattr(render_module,'surface_pin',lambda *args: Vector((3,5,8)))
    centers_projection = [(0.25,.75,10),(-.1,.5,10),(.5,.5,-1),(0,1,10),(.5,.5,0),(1.1,.5,10)]
    projections = iter([p for center in centers_projection for p in [(.26,.76,10),center]+[(.1,.2,10),(.3,.4,10)]*4])
    centers = []
    def project(actual_scene, camera, center):
        assert actual_scene is scene and camera is scene.camera
        centers.append(tuple(center))
        return NS(**dict(zip('xyz',next(projections))))
    monkeypatch.setitem(sys.modules,'bpy_extras.object_utils',NS(world_to_camera_view=project))
    result = render_module.anchors(scene,{name:name for name in common.ANCHOR_NODES})
    assert centers[1::10] == [(3,5,7)]*6
    assert centers[::10] == [(3,5,8)]*6
    assert len(centers) == 60
    assert result['girder'].pop('pin') == pytest.approx({'x':249.6,'y':129.6})
    assert result['girder'] == {'x':240,'y':135,'visible':True,'in_frame':True,'center_m':(3,7,-5),'bbox':[96,324,288,432]}
    assert [result[name]['visible'] for name in common.ANCHOR_NODES] == [True,False,False,True,False,False]
    assert result['hoist_hook']['x'] is None


@pytest.mark.parametrize('options,count,video', [([],180,True),
    (['--stills','0.5,3,5.5','--preview'],3,False),(['--still-at','3','--look','dusk'],1,False),
    (['--duration','1.25','--skip-video'],38,False)])
@pytest.mark.parametrize('shot', [{'kind':'model_orbit'}, {'kind':'title'},
    {'kind':'data_card'}, {'kind':'outro'},
    {'kind':'analogy','analogy_data':{'ref':'building_floor','fact':'F_overall_height','ratio':17,'ref_size_m':3}},
    {'kind':'analogy','analogy_data':{'ref':'football_field','fact':'F_girder_length','ratio':.99,'ref_size_m':105}},
    {'kind':'exploded','params':{'parts':['girder','leg_left','leg_right','trolley','hoist_hook']}},
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
    from unittest.mock import MagicMock
    monkeypatch.setitem(sys.modules,'crane',NS(build_crane=lambda *a:parents,Geometry=MagicMock()))
    monkeypatch.setitem(sys.modules,'scene',NS(environment=lambda *a:[],materials=lambda:{},analogy_reference=lambda *a:None))
    monkeypatch.setitem(sys.modules,'bpy_extras.object_utils',NS(world_to_camera_view=lambda scene,camera,point:NS(x=.3+point[0]/1000,y=.2+point[2]/1000,z=100)))
    monkeypatch.setattr(render_module,'part_objects',lambda parent:[obj])
    monkeypatch.setattr(render_module,'bounds',lambda *a:(Vector((-dim.length/2,-60,0)),Vector((dim.length/2,60,dim.height))))
    monkeypatch.setattr(render_module,'read_facts',lambda _: {})
    monkeypatch.setattr(render_module,'configure_engine',lambda *a:{'warnings':[],'device':'模拟设备'})
    meters = []
    calibrations = []
    def calibrate(scene, target):
        assert not meters
        calibrations.append(target)
        return {'sun_sky_ratio':target, 'sun_energy':22.0}
    monkeypatch.setattr(render_module,'meter_sun_sky',calibrate)
    def meter(*args):
        meters.append(tuple(camera.location))
        return {'exposure':[0,.2,.1,-.1,0][len(meters)-1],'median':.42,'p98':.8}
    monkeypatch.setattr(render_module,'meter_exposure',meter)
    monkeypatch.setattr(render_module,'frame_quality',lambda *a:{'warnings':[], 'passed':True})
    monkeypatch.setattr(render_module,'anchors',lambda *a:{n:{'x':1,'y':2,'visible':True} for n in common.ANCHOR_NODES})
    encoded = []
    monkeypatch.setattr(render_module,'compose_video',lambda *a:encoded.append(a) or {'status':'ok'})
    render_module.main(['--facts','facts.json','--shot-json',json.dumps(shot),
                        '--out',str(tmp_path),*options])
    payload = json.loads((tmp_path/'anchors.json').read_text())
    report = json.loads((tmp_path/'render_eevee.json').read_text())
    assert len(meters) == 5
    target = 2.5 if 'dusk' in options else 4.0
    assert calibrations == [target]
    assert report['sun_sky_ratio'] == report['light_calibration']['sun_sky_ratio'] == target
    assert report['sun_energy'] == 22.0
    duration = 1.25 if '--duration' in options else 6
    assert [m['time_s'] for m in report['metering_frames']] == [duration*i/4 for i in range(5)]
    assert len(payload['frames']) == len(report['camera_frames']) == len(rendered) == count
    assert len(report['quality_frames']) == len(report['frame_seconds']) == count
    assert all((tmp_path/f['file']).is_file() and len(f['nodes']) == 6 for f in payload['frames'])
    if shot['kind'] == 'analogy':
        layout = common.analogy_layout(dim,shot['analogy_data'])
        for frame in payload['frames']:
            assert set(frame['dims']) == set(layout['dims'])
            for name,point in layout['dims'].items():
                assert frame['dims'][name]['x'] == pytest.approx((.3+point[0]/1000)*payload['width'])
                assert frame['dims'][name]['y'] == pytest.approx((.8-point[1]/1000)*payload['height'])
    assert [f['exposure'] for f in payload['frames']] == rendered
    x0,y0,x1,y1 = report['safe_rect']
    width,height = report['resolution']
    for frame in report['camera_frames']:
        edges = frame['projected_bounds_px']
        assert edges['left'] >= x0*width-1e-5 and edges['right'] <= x1*width+1e-5
        assert edges['top'] >= y0*height-1e-5 and edges['bottom'] <= y1*height+1e-5
    if shot['kind'] == 'exploded':
        assert len({tuple(f['position_m']) for f in report['camera_frames']}) == 1
        assert len({tuple(f['target_m']) for f in report['camera_frames']}) == 1
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


@pytest.fixture
def exploded_boxes():
    # 腿顶比梁底高 0.7 m，验证实际外包修正而非仅用参数高度。
    return {'girder':((-52,34,-5.3),(52,43.2,5.3)),
            'leg_left':((-45,.3,-11.3),(-38,34.7,11.3)),
            'leg_right':((43,.3,-11.3),(45,34.5,11.3)),
            'trolley':((-6,42.02,-4.5),(6,47.5,4.5)),
            'hoist_hook':((-1.5,28,-1.5),(1.5,32,1.5)),
            'cab':((-43,22,-1.5),(-39,34,1.5))}


@pytest.mark.parametrize('spread', [1,12,30])
def test_exploded_clearance_endpoints_and_rigid_cab(exploded_boxes,spread):
    parts = list(exploded_boxes)
    for t in (0,6):
        offsets = common.exploded_offsets(parts,spread,t,6,exploded_boxes)
        assert all(value == (0,0,0) for value in offsets.values())
    offsets = common.exploded_offsets(parts,spread,3,6,exploded_boxes)
    assert exploded_boxes['girder'][0][1]+offsets['girder'][1] >= 34.7+6
    assert exploded_boxes['trolley'][0][1]+offsets['trolley'][1] >= 43.2+offsets['girder'][1]+2-1e-9
    assert offsets['cab'] == offsets['leg_left'] == (-spread*.6,0,0)
    assert offsets['leg_right'] == (spread*.6,0,0)
    assert offsets['hoist_hook'] == (0,-spread*.6,0)
    assert common.exploded_offsets(parts,spread,1e-5,6,exploded_boxes)['girder'][1] < 1e-10
    assert all(v == (0,0,0) for v in common.exploded_offsets(parts,0,3,6,exploded_boxes).values())
    assert common.exploded_offsets(['cab'],spread,3,6,exploded_boxes)['cab'] == (0,0,0)


@pytest.mark.parametrize('t', [0,.5,3,5.5,6])
@pytest.mark.parametrize('spread', [0,12])
def test_exploded_rope_endpoints_and_hook_independence(exploded_boxes,t,spread):
    dim = common.derive_dimensions({})
    for parts in (list(exploded_boxes),['trolley']):
        offsets = common.exploded_offsets(parts,spread,t,6,exploded_boxes)
        scale,shift = common.exploded_rope(dim,offsets)
        transform = lambda y: dim.girder_top+offsets['trolley'][1]+(y-dim.girder_top)*scale+shift
        upper = dim.girder_bottom+offsets['girder'][1] if spread and 0 < t < 6 else dim.girder_top+1
        assert transform(dim.girder_top+1) == pytest.approx(upper)
        assert transform(dim.hook_height+3.9) == pytest.approx(dim.hook_height+3.9+offsets['hoist_hook'][1])
        if parts == ['trolley']:
            assert offsets['hoist_hook'] == (0,0,0)


@pytest.mark.parametrize('safe', [(.05,.2,.95,.86),(.05,.2,.74,.86),(.12,.3,.7,.8)])
@pytest.mark.parametrize('size', [(1920,1080),(960,540),(1080,1920)])
def test_exploded_fixed_camera_contains_every_part(exploded_boxes,safe,size):
    parts = list(exploded_boxes)
    peak = common.exploded_offsets(parts,12,3,6,exploded_boxes)
    envelope = common.displaced_corners(exploded_boxes,peak)+common.displaced_corners(exploded_boxes,{})
    camera,target,shift = common.safe_camera(envelope,13,safe,*size)
    assert camera[1] == 8
    assert math.degrees(math.atan2(camera[0],camera[2])) == pytest.approx(13)
    for t in (0,3,6):
        points = common.displaced_corners(exploded_boxes,common.exploded_offsets(parts,12,t,6,exploded_boxes))
        for p in points:
            q = common.project_point(p,camera,target,*size,common.hero_fov_y(*size))
            x,y = q['x']/size[0]+shift[0],q['y']/size[1]+shift[1]
            assert safe[0]-1e-9 <= x <= safe[2]+1e-9
            assert safe[1]-1e-9 <= y <= safe[3]+1e-9
    # 最近距离：稍微前移后，即使重新平移画幅，也无法容纳外包。
    closer = (camera[0]*.999,camera[1],camera[2]*.999)
    q = [common.project_point(p,closer,target,*size,common.hero_fov_y(*size)) for p in common.enclosing_corners(envelope)]
    assert ((max(p['x'] for p in q)-min(p['x'] for p in q))/size[0] > safe[2]-safe[0]
            or (max(p['y'] for p in q)-min(p['y'] for p in q))/size[1] > safe[3]-safe[1])


@pytest.mark.parametrize('rect', ['0.1,0.2,0.8', 'nan,0,1,1', '0.8,0.2,0.1,1', '-1,0,1,1'])
def test_invalid_safe_rect_rejected(render_module,rect):
    with pytest.raises(SystemExit):
        render_module.arguments(['--facts','f','--shot-json','{}','--out','frames','--safe-rect='+rect])


def test_rope_passages_avoid_solid_deck_and_girder(monkeypatch, exploded_boxes):
    """读取真实建模调用，验证八条绳索的通道和上端滑轮接点；不加载渲染器。"""
    from types import SimpleNamespace as NS
    from unittest.mock import MagicMock
    class Parent(dict):
        matrix_world = NS(inverted=lambda:None)
    fake = NS(data=NS(objects=NS(new=lambda *a:Parent())),
              context=NS(collection=NS(objects=NS(link=lambda _:None)),view_layer=NS(update=lambda:None)))
    monkeypatch.setitem(sys.modules,'bpy',fake)
    monkeypatch.setitem(sys.modules,'mathutils',NS(Vector=object))
    monkeypatch.setitem(sys.modules,'common',common)
    spec = importlib.util.spec_from_file_location('crane_geometry_test',ROOT/'blender/crane.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    geometry = MagicMock()
    monkeypatch.setattr(module,'Geometry',lambda *a:geometry)
    monkeypatch.setattr(module,'curve_hook',lambda *a:None)
    dim = common.derive_dimensions({})
    module.build_crane(dim,{'metal':None})
    ropes = [c.args for c in geometry.cylinder.call_args_list if c.args[0] == 'rope']
    boxes = [c.args for c in geometry.box.call_args_list if c.args[0] in {'girder','trolley'}]
    pulleys = [c.args for c in geometry.cylinder.call_args_list if c.args[0] == 'trolley']
    offsets = common.exploded_offsets(['girder','leg_left','leg_right','trolley','hoist_hook'],12,3,6,exploded_boxes)
    assert len(ropes) == 8
    for state in ({},offsets):
        for _,bottom,top,radius,*_ in ropes:
            x,z = top[0],top[2]
            low_y = bottom[1]+state.get('hoist_hook',(0,0,0))[1]
            scale, shift = common.exploded_rope(dim, state)
            high_y = dim.girder_top+state.get('trolley',(0,0,0))[1]+(top[1]-dim.girder_top)*scale+shift
            for node,size,center,*_ in boxes:
                y = center[1]+state.get(node,(0,0,0))[1]
                intersects = (abs(x-center[0]) < size[0]/2+radius
                              and abs(z-center[2]) < size[2]/2+radius
                              and low_y < y+size[1]/2 and high_y > y-size[1]/2)
                assert not intersects, (node,size,center,x,z)
    for _,bottom,top,radius,*_ in ropes:
        assert any(a[0] <= top[0] <= b[0] and a[1] == top[1] and abs(top[2]-a[2]) == r
                   for _,a,b,r,*_ in pulleys)
        assert any(node == 'hoist_hook' and all(abs(a-b) <= d/2 for a,b,d in zip(bottom,center,size))
                   for node,size,center,*_ in (c.args for c in geometry.box.call_args_list))


@pytest.mark.parametrize('kind,safe,ratio,angle', [
    ('data_card',(.46,.05,.95,.86),.96,23),
    ('outro',(.40,.30,.95,.80),1.08,50),
])
@pytest.mark.parametrize('size', [(1920,1080),(960,540)])
def test_graphic_camera_motion_and_safe_frame(kind,safe,ratio,angle,size):
    points = common.framing_points(common.derive_dimensions({}))
    start,target,_ = common.graphic_camera(points,kind,0,6,safe,*size)
    end,_,_ = common.graphic_camera(points,kind,6,6,safe,*size)
    assert math.dist(end,target)/math.dist(start,target) == pytest.approx(ratio)
    assert math.degrees(math.atan2(start[0]-target[0],start[2]-target[2])) == pytest.approx(angle)
    for t in (0,1.5,3,4.5,6):
        camera,target,shift = common.graphic_camera(points,kind,t,6,safe,*size)
        for p in points:
            q = common.project_point(p,camera,target,*size,common.hero_fov_y(*size))
            x,y = q['x']/size[0]+shift[0],q['y']/size[1]+shift[1]
            assert safe[0]-1e-9 <= x <= safe[2]+1e-9
            assert safe[1]-1e-9 <= y <= safe[3]+1e-9


def test_surface_pin_skips_accessories_and_uses_body_center(render_module,monkeypatch):
    import numpy as np
    from types import SimpleNamespace as NS

    class Vector(np.ndarray):
        def __new__(cls,values):
            return np.array(values,dtype=float).view(cls)
        @property
        def length(self):
            return float(np.linalg.norm(self))
        def normalized(self):
            return self/self.length

    class Object(dict):
        type = 'MESH'
        def as_pointer(self):
            return id(self)

    body,accessory = Object(anchor_body='cabin'),Object()
    monkeypatch.setattr(render_module,'bounds',lambda objects,graph: (
        (Vector((-2,-2,-2)),Vector((2,2,2))) if objects == [body]
        else (Vector((-2,-2,-2)),Vector((2,2,20)))))
    calls = []
    hits = iter([(True,Vector((0,0,5)),None,None,accessory,None),
                 (True,Vector((0,0,2)),None,None,body,None)])
    def cast(graph,origin,direction,**kwargs):
        calls.append((origin.copy(),direction.copy(),kwargs))
        return next(hits)
    scene = NS(camera=NS(matrix_world=NS(translation=Vector((0,0,10)))),ray_cast=cast)
    pin = render_module.surface_pin(scene,None,[body,accessory])
    assert tuple(pin) == (0,0,2)
    assert tuple(calls[0][1]) == (0,0,-1)
    assert calls[1][2]['distance'] < calls[0][2]['distance']
    scene.ray_cast = lambda *args,**kwargs: (False,None,None,None,None,None)
    assert tuple(render_module.surface_pin(scene,None,[body,accessory])) == (0,0,0)


@pytest.mark.parametrize('height,floor_size', [(51,3),(50,3),(51,3.2),(65,3)])
def test_residential_height_preserves_facts_and_partial_floor(height,floor_size):
    dim = common.derive_dimensions(facts(F_overall_height=height))
    a = {'ref':'building_floor','fact':'F_overall_height','ref_size_m':floor_size,'ratio':round(height/floor_size,3)}
    layout = common.analogy_layout(dim,a)
    assert len(layout['floors']) == math.ceil(height/floor_size)
    assert sum(layout['floors']) == pytest.approx(height,abs=.00001)
    assert layout['floors'][-1] == pytest.approx(height-(len(layout['floors'])-1)*floor_size)
    assert layout['bounds'][1][1] == layout['dims']['ref_top'][1] == dim.height
    assert layout['bounds'][0][0]-(dim.span/2+1.2) == pytest.approx(20)


@pytest.mark.parametrize('length,ref_size', [(104,105),(120,105),(104,100)])
def test_field_length_and_parallel_scale(length,ref_size):
    dim = common.derive_dimensions(facts(F_girder_length=length))
    layout = common.analogy_layout(dim,{'ref':'football_field','fact':'F_girder_length','ref_size_m':ref_size,'ratio':round(length/ref_size,3)})
    assert layout['length'] == ref_size
    assert layout['dims']['ref_right'][0]-layout['dims']['ref_left'][0] == ref_size
    assert layout['dims']['crane_right'][0]-layout['dims']['crane_left'][0] == length


@pytest.mark.parametrize('ref,fact,size,ratio', [('building_floor','F_overall_height',3,20),('football_field','F_span',105,.99),('bus','F_girder_length',12,8.67)])
def test_analogy_rejects_inconsistent_facts(ref,fact,size,ratio):
    with pytest.raises(ValueError):
        common.analogy_layout(common.derive_dimensions({}),{'ref':ref,'fact':fact,'ref_size_m':size,'ratio':ratio})


@pytest.mark.parametrize('ref,size,fact', [('building_floor',3,'F_overall_height'),('football_field',105,'F_girder_length')])
@pytest.mark.parametrize('resolution', [(1920,1080),(960,540)])
def test_analogy_camera_full_frame_and_physical_pose(ref,size,fact,resolution):
    dim = common.derive_dimensions({})
    layout = common.analogy_layout(dim,{'ref':ref,'fact':fact,'ref_size_m':size,'ratio':(dim.height if ref=='building_floor' else dim.length)/size})
    safe = (.08,.23,.92,.80)
    poses = []
    for time in (0,3,6):
        position,target,shift,fov = common.analogy_camera(dim,layout,time,*resolution,safe)
        poses.append(position)
        assert position[1] == (20 if ref == 'building_floor' else 120)
        if ref == 'football_field':
            assert math.degrees(math.atan2(position[1]-target[1],position[2]-target[2])) == pytest.approx(35)
        else:
            assert 36*resolution[1]/max(resolution)/(2*math.tan(math.radians(fov)/2)) == pytest.approx(35)
        points = common.framing_points(dim)+common.enclosing_corners(layout['bounds'])+list(layout['dims'].values())
        for point in points:
            q = common.project_point(point,position,target,*resolution,fov)
            x,y = q['x']/resolution[0]+shift[0],q['y']/resolution[1]+shift[1]
            assert safe[0]-1e-8 <= x <= safe[2]+1e-8
            assert safe[1]-1e-8 <= y <= safe[3]+1e-8
    if ref == 'building_floor':
        assert math.dist(poses[0],poses[-1]) == pytest.approx(3)


@pytest.fixture
def geometry_runtime(monkeypatch):
    """执行实际网格构造，仅替换运行时对象容器，不启动图形进程。"""
    import numpy as np
    from types import SimpleNamespace as NS
    class Vector(np.ndarray):
        def __new__(cls,values):
            return np.array(values,dtype=float).view(cls)
        x = property(lambda self: self[0])
        y = property(lambda self: self[1])
        z = property(lambda self: self[2])
        def cross(self,other):
            return Vector(np.cross(self,other))
        def normalized(self):
            return self/np.linalg.norm(self)
        def normalize(self):
            self[:] = self.normalized()
    class Parent(dict):
        matrix_world = NS(inverted=lambda:None)
    fake = NS(data=NS(objects=NS(new=lambda *a:Parent())),
              context=NS(collection=NS(objects=NS(link=lambda _:None)),view_layer=NS(update=lambda:None)))
    monkeypatch.setitem(sys.modules,'bpy',fake)
    monkeypatch.setitem(sys.modules,'mathutils',NS(Vector=Vector))
    monkeypatch.setitem(sys.modules,'common',common)
    spec = importlib.util.spec_from_file_location('crane_t19_test',ROOT/'blender/crane.py')
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules,'crane',module)
    batches = []
    module.real_finish = module.Geometry.finish
    monkeypatch.setattr(module.Geometry,'finish',lambda self:batches.append(self.batches) or [])
    monkeypatch.setattr(module,'curve_hook',lambda *args:None)
    return module,batches


@pytest.mark.parametrize('height,girder', [(51,6.5),(65,8),(58,7)])
def test_actual_crane_mesh_envelope_and_taper(geometry_runtime,height,girder):
    module,batches = geometry_runtime
    dim = common.derive_dimensions(facts(F_overall_height=height,F_girder_height=girder))
    module.build_crane(dim,{'metal':None})
    vertices = [v for data in batches[0].values() for v in data[0]]
    assert max(v[2] for v in vertices)-min(v[2] for v in vertices) == pytest.approx(height,abs=.01)
    assert max(v[0] for v in vertices)-min(v[0] for v in vertices) == pytest.approx(dim.length,abs=.01)
    profile = common.rigid_leg_profile(dim)
    assert profile['base_width'] == girder*3.2 and profile['top_width'] == girder*1.2
    assert dim.girder_top+profile['top_extension'] <= height
    assert all(node.startswith('leg_') for node,mat,_ in batches[0] if mat == 'hazard')


def test_reference_mesh_rooftop_and_field_surface(geometry_runtime):
    module,batches = geometry_runtime
    spec = importlib.util.spec_from_file_location('scene_t19_test',ROOT/'blender/scene.py')
    scene = importlib.util.module_from_spec(spec);spec.loader.exec_module(scene)
    dim = common.derive_dimensions(facts(F_overall_height=50))
    for ref,size,fid,value in [('building_floor',3,'F_overall_height',50),('football_field',105,'F_girder_length',104)]:
        layout = common.analogy_layout(dim,{'ref':ref,'ref_size_m':size,'fact':fid,'ratio':round(value/size,3)})
        g = module.Geometry({},{});scene.analogy_reference(g,layout)
        if ref == 'building_floor':
            vertices = [v for batch in g.batches.values() for v in batch[0]]
            assert max(v[2] for v in vertices) == pytest.approx(50,abs=.01)
        else:
            grass = [v for (_,material,_),batch in g.batches.items() if material.startswith('grass_') for v in batch[0]]
            assert max(v[0] for v in grass)-min(v[0] for v in grass) == 105


def test_afternoon_exposure_target_and_cli(render_module):
    assert render_module.arguments(['--facts','f','--shot-json','{}','--out','o']).look == 'afternoon'
    assert render_module.arguments(['--facts','f','--shot-json','{}','--out','o','--look','dusk']).look == 'dusk'
    _,stats = common.solve_exposure(lambda ev:{'median':.2*2**ev,'p98':.3*2**ev},target=.44)
    assert stats['median'] == pytest.approx(.44,abs=.001)


def test_yard_detail_geometry_is_finite_and_keeps_human_scale(geometry_runtime):
    module,_ = geometry_runtime
    spec = importlib.util.spec_from_file_location('yard_t19_test',ROOT/'blender/scene.py')
    scene = importlib.util.module_from_spec(spec);spec.loader.exec_module(scene)
    g = module.Geometry({},{})
    scene.yard(g,common.derive_dimensions({}))
    before = {}
    for (node,_,_),batch in g.batches.items():
        before.setdefault(node,[]).extend(batch[0])
        assert all(math.isfinite(v) for point in batch[0] for v in point)
        assert all(0 <= index < len(batch[0]) for face in batch[1] for index in face)
    assert len([key for key in before if key.startswith('decor_crawler_')]) == 2
    assert len([key for key in before if key.startswith('decor_factory_')]) == 3
    workers = [vertices for key,vertices in before.items() if key.startswith('decor_worker_')]
    assert 12 <= len(workers) <= 20
    assert all(max(v[2] for v in vertices) == pytest.approx(1.75) for vertices in workers)
    lamps = [vertices for key,vertices in before.items() if key.startswith('decor_lamp_')]
    assert len(lamps) == 6
    assert all(max(v[2] for v in vertices) == pytest.approx(30) for vertices in lamps)
    scene.orient_backdrop(g,35)
    for (node,_,_),batch in g.batches.items():
        if node.startswith('decor_factory_'):
            assert all(math.isfinite(v) for point in batch[0] for v in point)
            assert max(v[2] for v in batch[0]) <= 40


def test_worker_groups_are_spaced_varied_and_repeatable():
    workers = common.worker_layout(common.derive_dimensions({}))
    assert workers == common.worker_layout(common.derive_dimensions({}))
    for group in range(4):
        members = [p for p in workers if p['group'] == group]
        assert 3 <= len(members) <= 5
        assert {p['walking'] for p in members} == {False,True}
        assert len({p['yaw'] for p in members}) == len(members)
        for i,p in enumerate(members):
            for q in members[i+1:]:
                assert 1 <= math.hypot(p['x']-q['x'],p['z']-q['z']) <= 3


@pytest.mark.parametrize('energy,e_sun,e_sky,target,expected', [
    (5.5, .2, .4, 4.0, 44.0),
    (5.5, 2.0, .1, 4.0, 1.1),
    (1.6, .2, .4, 2.5, 8.0),
    (5.5, .4, .1, 4.0, 5.5),
    (5.5, 4e-9, 1e-9, 4.0, 5.5),
])
def test_sun_energy_calibration_scales_linear_light(energy,e_sun,e_sky,target,expected):
    calibrated = common.calibrate_sun_energy(energy,e_sun,e_sky,target)
    assert calibrated == pytest.approx(expected)
    assert e_sun*(calibrated/energy)/e_sky == pytest.approx(target)


@pytest.mark.parametrize('index', range(4))
@pytest.mark.parametrize('invalid', [0, -1, float('nan'), float('inf')])
def test_sun_energy_calibration_rejects_invalid_measurement(index,invalid):
    values = [5.5, .2, .4, 4.0]
    values[index] = invalid
    with pytest.raises(ValueError,match='光比标定失败'):
        common.calibrate_sun_energy(*values)


@pytest.mark.parametrize('engine', ['BLENDER_EEVEE','CYCLES'])
@pytest.mark.parametrize('failure', [None, 'mask', 'render', 'zero'])
def test_light_probes_isolate_sources_and_restore_settings(render_module,monkeypatch,engine,failure):
    from types import SimpleNamespace as NS
    import numpy as np
    settings = NS(file_format='PNG',color_mode='RGB',color_depth='8')
    render = NS(resolution_x=1920,resolution_y=1080,resolution_percentage=50,
                film_transparent=True,image_settings=settings,engine=engine)
    sun = NS(type='LIGHT',data=NS(type='SUN',energy=5.5))
    strength = NS(default_value=.55)
    scene = NS(objects=[sun],render=render,view_settings=NS(exposure=3),
        eevee=NS(taa_render_samples=24),cycles=NS(samples=64,use_adaptive_sampling=True,use_denoising=True),
        world=NS(node_tree=NS(nodes={'Background':NS(inputs={'Strength':strength})})))
    calls, removed, paths = [], [], []
    def mask(*args):
        assert (render.resolution_x,render.resolution_y) == (192,108)
        if failure == 'mask':
            raise RuntimeError('光比标定失败：受光地面不足')
        return list(range(32))
    monkeypatch.setattr(render_module,'sunlit_ground_indices',mask)
    def do_render(**kwargs):
        calls.append((sun.data.energy,strength.default_value))
        assert kwargs == {'write_still':False}
        assert render.resolution_percentage == 100 and not render.film_transparent
        assert settings.file_format == 'OPEN_EXR' and settings.color_depth == '32'
        assert scene.view_settings.exposure == 3
        if failure == 'render' and len(calls) == 2:
            raise RuntimeError('模拟探针失败')
    def save(path,scene):
        from pathlib import Path
        paths.append(Path(path))
        Path(path).write_bytes(b'probe')
    def load(*args,**kwargs):
        # 掩码外故意放入极亮像素，不应影响地面中位数。
        values = np.full((192*108,4),1000,dtype=np.float32)
        values[:32,:3] = .4 if sun.data.energy == 0 else (0 if failure == 'zero' else .2)
        return NS(size=(192,108),pixels=NS(foreach_get=lambda buf:buf.__setitem__(slice(None),values.ravel())))
    monkeypatch.setitem(sys.modules,'bpy',NS(context=NS(view_layer=NS(update=lambda:None)),
        ops=NS(render=NS(render=do_render)),data=NS(images=NS(
            get=lambda _:NS(save_render=save),load=load,remove=removed.append))))
    if failure:
        with pytest.raises((RuntimeError,ValueError)):
            render_module.meter_sun_sky(scene)
        assert sun.data.energy == 5.5
    else:
        result = render_module.meter_sun_sky(scene)
        assert calls == [(0,.55),(5.5,0)]
        assert result['sun_energy'] == sun.data.energy == pytest.approx(44)
        assert result['sun_sky_ratio'] == pytest.approx(4)
        assert result['measured_ratio_before'] == pytest.approx(.5)
        assert result['e_sky'] == pytest.approx(.4)
        assert result['sample_count'] == 32
    assert strength.default_value == .55 and scene.view_settings.exposure == 3
    assert (render.resolution_x,render.resolution_y,render.resolution_percentage) == (1920,1080,50)
    assert render.film_transparent
    assert vars(settings) == dict(file_format='PNG',color_mode='RGB',color_depth='8')
    assert scene.eevee.taa_render_samples == 24
    assert vars(scene.cycles) == dict(samples=64,use_adaptive_sampling=True,use_denoising=True)
    assert len(removed) == len(paths)
    assert all(not path.exists() for path in paths)


def test_quality_metrics_use_display_samples_and_warn_for_failures():
    samples = {'crane':[(.8,.2,.1)]*4, 'sunlit_paint':[(.8,.4,.2)]*4,
               'shaded_paint':[(.16,.08,.04)]*4,'ground':[(.36,.36,.36)]*4,
               'crane_shadow':[(.16,.16,.16)]*4,'sunlit_ground':[(.4,.4,.4)]*4}
    result = common.quality_statistics(samples)
    assert result['passed'] and result['warnings'] == []
    assert result['crane_mean_saturation'] == pytest.approx(.875)
    assert result['sunlit_paint_median_hue_deg'] == pytest.approx(20)
    assert result['sunlit_paint_median_saturation'] == pytest.approx(.75)
    assert result['sunlit_to_shaded_ratio'] == pytest.approx(5)
    assert result['shadow_to_sunlit_ground_ratio'] == pytest.approx(.4)
    samples['shaded_paint'] = samples['sunlit_paint']
    samples['ground'] = [(1,1,1)]*4
    samples['crane_shadow'] = samples['sunlit_ground']
    samples['sunlit_paint'] = [(.8,.8,.8)]*4
    samples['shaded_paint'] = samples['sunlit_paint']
    assert len(common.quality_statistics(samples)['warnings']) == 5
    missing = common.quality_statistics({})
    assert missing['sunlit_to_shaded_ratio'] is None
    assert not missing['passed'] and len(missing['warnings']) == 5


@pytest.mark.parametrize('kind', ['model_orbit','analogy'])
def test_factories_have_complete_visible_outline_at_review_cameras(geometry_runtime,kind):
    module,batches = geometry_runtime
    dim = common.derive_dimensions({})
    module.build_crane(dim,{'metal':None})
    by_node = {}
    for (node,_,_),batch in batches[0].items():
        if node not in {'rail_left','rail_right'}:
            by_node.setdefault(node,[]).extend((x,z,-y) for x,y,z in batch[0])
    protected = [common.enclosing_corners(points) for points in by_node.values()]
    protected.append(common.enclosing_corners([(-18,1.2,-26),(18,15.2,-4)]))
    silhouette = common.enclosing_corners([p for points in protected[:-1] for p in points])
    if kind == 'analogy':
        reference = common.analogy_layout(dim,{'ref':'building_floor','fact':'F_overall_height','ref_size_m':3,'ratio':17})
        protected.append(common.enclosing_corners(reference['bounds']))
    poses = []
    for t in sorted(set([6*i/8 for i in range(9)]+[2.5,3.7])):
        if kind == 'analogy':
            position,target,shift,fov = common.analogy_camera(dim,reference,t,1920,1080,(.08,.23,.92,.8))
        else:
            position,target,shift = common.safe_camera(silhouette,common.hero_azimuth({},t,6),(.05,.2,.95,.86),1920,1080)
            fov = common.hero_fov_y(1920,1080)
        poses.append({'position':position,'target':target,'shift':shift,'fov':fov})
    placements = common.backdrop_layout(poses,protected,1920,1080)
    assert len(placements) == 3
    assert all(250 <= p['depth_m'] <= 450 for p in placements)
    for i,pose in enumerate(poses):
        assert any(p['visible'][i] for p in placements), (kind,i,placements)
        rects = [common.projected_rect(p['points'],pose,1920,1080) for p in placements]
        def separate(a,b):
            return a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3]
        assert any(p['visible'][i] and all(j == k or separate(rects[j],rects[k])
                   for k in range(3)) for j,p in enumerate(placements)), (kind,i,rects)


def test_linked_meshes_preserve_world_geometry_after_backdrop_rotation(geometry_runtime,monkeypatch):
    import numpy as np
    from types import SimpleNamespace as NS
    module,_ = geometry_runtime
    Vector = sys.modules['mathutils'].Vector
    class Matrix(np.ndarray):
        def __new__(cls,value):
            return np.array(value,dtype=float).view(cls)
        @staticmethod
        def Identity(n):
            return Matrix(np.eye(n))
        @staticmethod
        def Translation(v):
            m = Matrix.Identity(4); m[:3,3] = v
            return m
        @staticmethod
        def Rotation(angle,n,axis):
            assert axis == 'Z'
            m = Matrix.Identity(n); c,s = math.cos(angle),math.sin(angle)
            m[:2,:2] = ((c,-s),(s,c))
            return m
        def transposed(self):
            return Matrix(self.T)
        def to_4x4(self):
            m = Matrix.Identity(4); m[:3,:3] = self
            return m
        def inverted(self):
            return Matrix(np.linalg.inv(self))
        def __matmul__(self,other):
            if np.shape(other) == (3,) and self.shape == (4,4):
                return Vector(np.asarray(self).dot([*other,1])[:3])
            return Matrix(np.asarray(self) @ np.asarray(other))
        translation = property(lambda self:Vector(self[:3,3]),lambda self,v:self.__setitem__((slice(0,3),3),v))
    class Mesh:
        def __init__(self,name):
            self.name,self.materials = name,[]
        def from_pydata(self,vertices,edges,faces):
            self.vertices = vertices
            self.polygons = [NS() for _ in faces]
        def update(self):
            pass
    class Object(dict):
        def __init__(self,name,mesh):
            super().__init__(); self.name,self.data = name,mesh
    fake = NS(data=NS(meshes=NS(new=Mesh),objects=NS(new=Object)),
              context=NS(collection=NS(objects=NS(link=lambda _:None))))
    monkeypatch.setitem(sys.modules,'mathutils',NS(Vector=Vector,Matrix=Matrix))
    monkeypatch.setattr(module,'bpy',fake)
    g = module.Geometry({'metal':object(),'paint':object()}, {})
    g.cylinder('decor_crawler_0',(1,2,3),(8,4,6),.2,'metal',8)
    g.cylinder('decor_crawler_1',(-5,3,1),(-5,23,1),.6,'metal',8)
    g.instance_detail = True
    g.bar('girder',(0,10,0),(0,11,0),.1)
    g.bar('girder',(4,10,0),(4,11,0),.1)
    g.instance_detail = False
    g.box('decor_lamp_0',(4,.3,1),(20,29.65,-10),'metal')
    g.box('decor_lamp_1',(4,.3,1),(-20,29.65,40),'metal')
    scene_spec = importlib.util.spec_from_file_location('instance_scene',ROOT/'blender/scene.py')
    scene = importlib.util.module_from_spec(scene_spec);scene_spec.loader.exec_module(scene)
    scene.orient_backdrop(g,35)
    objects = module.real_finish(g)
    for obj,batch in zip(objects,g.batches.values()):
        actual = [tuple(obj.matrix_world @ Vector(v)) for v in obj.data.vertices]
        assert np.asarray(actual) == pytest.approx(np.asarray(batch[0]),abs=1e-5)
    assert objects[0].data is objects[1].data
    assert objects[2].data is objects[3].data
    assert objects[4].data is objects[5].data


def test_final_frame_quality_classifies_actual_rays_and_encoded_pixels(render_module,geometry_runtime,monkeypatch,tmp_path):
    import numpy as np
    from types import SimpleNamespace as NS
    Vector = sys.modules['mathutils'].Vector
    class Object(dict):
        hide_render = False
        def as_pointer(self):
            return id(self)
    crane = Object(geometry_material='paint',geometry_node='girder')
    ground = Object(geometry_material='concrete',geometry_node='ground')
    rgba = np.ones((54,96,4),dtype=np.float32)
    rgba[:,:24,:3] = (.8,.4,.2)
    rgba[:,24:48,:3] = (.16,.08,.04)
    rgba[:,48:72,:3] = (.16,.16,.16)
    rgba[:,72:,:3] = (.4,.4,.4)
    image = NS(colorspace_settings=NS(name='sRGB'),size=(96,54),
               pixels=NS(foreach_get=lambda buffer:buffer.__setitem__(slice(None),rgba.ravel())))
    removed = []
    identity = NS(to_3x3=lambda:np.eye(3),translation=Vector((0,0,10)))
    scene = NS(camera=NS(matrix_world=identity,data=NS(view_frame=lambda **kw:[
        Vector((-1,-1,-1)),Vector((1,-1,-1)),Vector((1,1,-1)),Vector((-1,1,-1))])),
        objects=[NS(type='LIGHT',data=NS(type='SUN'),matrix_world=identity)])
    def cast(graph,start,direction,distance):
        if start[2] == 10:
            x = direction[0]/-direction[2]
            obj = crane if x < 0 else ground
            normal = Vector((0,0,-1 if -.5 < x < 0 else 1))
            return True,Vector((x,0,0)),normal,0,obj,None
        # 地面中间一带由门机遮挡太阳。
        if 0 < start[0] < .5:
            return True,Vector((0,0,2)),Vector((0,0,1)),0,crane,None
        return False,None,None,None,None,None
    scene.ray_cast = cast
    monkeypatch.setitem(sys.modules,'bpy',NS(data=NS(images=NS(load=lambda *a,**kw:image,remove=removed.append)),
        context=NS(evaluated_depsgraph_get=lambda:None)))
    result = render_module.frame_quality(scene,tmp_path/'frame.png',[crane])
    assert result['sample_counts']['crane'] == 2592
    assert result['sample_counts']['crane_shadow'] == 1296
    assert result['sunlit_to_shaded_ratio'] == pytest.approx(5,rel=1e-6)
    assert result['shadow_to_sunlit_ground_ratio'] == pytest.approx(.4,rel=1e-6)
    assert result['crane_mean_saturation'] == pytest.approx(.75,rel=1e-6)
    assert image.colorspace_settings.name == 'Non-Color' and removed == [image]
    indices = render_module.sunlit_ground_indices(scene,scene.objects[0],96,54)
    assert len(indices) == 1296
    assert all(index % 96 >= 72 for index in indices)
    ground['geometry_node'] = 'water'
    with pytest.raises(RuntimeError,match='受光混凝土地面不足'):
        render_module.sunlit_ground_indices(scene,scene.objects[0],96,54)
