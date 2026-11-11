"""Pure validation/geometry contracts: no Blender, network or renderer subprocess."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec=importlib.util.spec_from_file_location('scale_film_scene_math',Path(__file__).resolve().parents[2]/'blender/scale_film_scene.py')
geometry=importlib.util.module_from_spec(spec)
spec.loader.exec_module(geometry)


def config():
    return {'version':1,'width':1920,'height':1080,'fps':30,'facts_file':'/tmp/facts.json','shots':[
        {'id':'a','role':'detail','start':0,'end':4},
        {'id':'b','role':'hero','start':4,'end':9},
        {'id':'c','role':'compare','start':9,'end':15}]}


def facts(length=132,height=51):
    return {'facts':[{'id':'F_girder_length','value':length,'status':'confirmed','unit':'m'},
                     {'id':'F_overall_height','value':height,'status':'verified','unit':'m'}]}


def test_requires_real_length_height_and_keeps_optional_dimensions_absent():
    accepted=geometry.validate_facts(facts())
    assert accepted=={'F_girder_length':132,'F_overall_height':51}
    with pytest.raises(ValueError,match='missing confirmed dimensions'):
        geometry.validate_facts({'facts':[]})


@pytest.mark.parametrize('value',[None,True,'132',float('nan'),float('inf'),0,-1])
def test_bad_provided_length_is_never_silently_defaulted(value):
    with pytest.raises(ValueError):geometry.validate_facts(facts(value))


@pytest.mark.parametrize('extra',[
    {'id':'F_span','value':float('nan'),'status':'confirmed'},
    {'id':'F_span','value':88,'status':'needs_review'},
    {'id':'F_wheel_count','value':4.5,'status':'confirmed'},
    {'id':'F_span','value':88,'status':'confirmed','unit':'cm'},
    {'id':'F_girder_length','value':104,'status':'confirmed'},
])
def test_invalid_provided_optional_values_and_duplicates_rejected(extra):
    doc=facts();doc['facts'].append(extra)
    with pytest.raises(ValueError):geometry.validate_facts(doc)


@pytest.mark.parametrize('length',[40,104,132,210,500])
@pytest.mark.parametrize('aspect',[16/9,1,9/16])
def test_same_scale_comparison_ratio_and_safe_margins(length,aspect):
    layout=geometry.comparison_layout(length,aspect)
    field=geometry.rect_topdown(-52.5,52.5,-27,41,layout,aspect)
    beam=geometry.rect_topdown(-length/2,length/2,-48.3,-37.7,layout,aspect)
    assert (beam['right']-beam['left'])/(field['right']-field['left'])==pytest.approx(length/105)
    for rect in (field,beam):
        assert .1<=rect['left']<rect['right']<=.9
        assert 0<rect['top']<rect['bottom']<=.96
    assert field['bottom']<beam['top']


def test_approved_t24_reference_composition_and_adaptation():
    dim=SimpleNamespace(length=104,height=51)
    pose=geometry.camera_pose(dim,'hero',.5,16/9)
    assert pose['position']==(84,-143,5.75)
    assert pose['target']==(0,0,26)
    assert geometry.comparison_layout(104,16/9)['ortho_scale']==188
    wider=geometry.camera_pose(SimpleNamespace(length=132,height=51),'hero',.5,16/9)
    assert abs(wider['position'][1])>abs(pose['position'][1])
    assert wider['position'][2]==pose['position'][2]


def test_camera_is_direct_absolute_evaluation():
    dim=SimpleNamespace(length=132,height=68)
    first=geometry.camera_pose(dim,'detail',.25,16/9)
    geometry.camera_pose(dim,'hero',.75,16/9)
    assert geometry.camera_pose(dim,'detail',.25,16/9)==first
    assert geometry.camera_pose(dim,'compare',0,16/9)==geometry.camera_pose(dim,'compare',1,16/9)


def test_timeline_boundaries_and_configurable_duration():
    c=config();geometry.validate_config(c)
    assert geometry.shot_at(c['shots'],119/30)['role']=='detail'
    assert geometry.shot_at(c['shots'],4)['role']=='hero'
    assert geometry.shot_at(c['shots'],9)['role']=='compare'
    c['shots'][-1]['end']=23
    assert geometry.validate_config(c)['shots'][-1]['end']==23


@pytest.mark.parametrize('mutation',[
    lambda c:c.update(version=2),lambda c:c.update(width=1919),
    lambda c:c.update(fps=True),lambda c:c.update(facts_file='relative.json'),
    lambda c:c['shots'][1].update(start=5),lambda c:c['shots'][1].update(end=4),
    lambda c:c['shots'][2].update(end=31),lambda c:c['shots'][0].update(start=.1),
    lambda c:c['shots'][2].update(role='hero'),lambda c:c['shots'][2].update(id='a'),
    lambda c:c['shots'][1].update(end=9.01),
])
def test_invalid_config_fails(mutation):
    c=config();mutation(c)
    with pytest.raises(ValueError):geometry.validate_config(c)


@pytest.mark.parametrize('length,height',[(104,51),(132,51),(80,85),(300,70),(160,160),(42,25)])
@pytest.mark.parametrize('aspect',[16/9,32/9,1,9/16])
@pytest.mark.parametrize('u',[0,.5,1])
def test_adaptive_hero_camera_contains_physical_machine_envelope(length,height,aspect,u):
    dim=SimpleNamespace(length=length,height=height)
    pose=geometry.camera_pose(dim,'hero',u,aspect)
    for point in geometry.hero_envelope(dim):
        x,y=geometry.perspective_point(point,pose['position'],pose['target'],pose['lens'],aspect)
        assert .055<=x<=.945 and .055<=y<=.945
