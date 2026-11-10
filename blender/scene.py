"""船厂环境、傍晚侧光与程序化表面。"""
from __future__ import annotations

import math
from typing import Any

import bpy
from mathutils import Vector

from common import Dimensions, Vec3, link_input, set_attr, set_input, to_blender
from crane import Geometry


def linear_hex(value: str) -> tuple[float, float, float]:
    """色板为显示色，着色器使用线性颜色。"""
    srgb = [int(value.lstrip('#')[i:i+2], 16)/255 for i in (0, 2, 4)]
    return tuple(c/12.92 if c <= .04045 else ((c+.055)/1.055)**2.4 for c in srgb)


def material(name: str, color: tuple, roughness: float, metallic: float = 0.0,
             variation: float = .04, scale: float = 3.8,
             rough_variation: float = .06) -> Any:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    shader = nodes.get("Principled BSDF")
    set_input(shader, "Base Color", (*color, 1))
    set_input(shader, "Metallic", metallic)
    set_input(shader, "Roughness", roughness)
    if variation:
        texture = nodes.new("ShaderNodeTexNoise")
        set_input(texture, "Scale", scale)
        set_input(texture, "Detail", 3)
        coord = nodes.new("ShaderNodeTexCoord")
        link_input(links, coord, "Object", texture, "Vector")
        ramp = nodes.new("ShaderNodeValToRGB")
        for element, factor in zip(ramp.color_ramp.elements, (1-variation, 1+variation)):
            set_attr(element, "color", (*(min(1, c*factor) for c in color), 1))
        link_input(links, texture, "Fac", ramp, "Fac")
        link_input(links, ramp, "Color", shader, "Base Color")
        rough = nodes.new("ShaderNodeMapRange")
        set_input(rough, "To Min", max(.01, roughness-rough_variation))
        set_input(rough, "To Max", min(1, roughness+rough_variation))
        link_input(links, texture, "Fac", rough, "Value")
        link_input(links, rough, "Result", shader, "Roughness")
    return mat


def materials() -> dict[str, Any]:
    concrete = linear_hex('#8C8984')
    mats = {
        "paint": material("暖白涂装", linear_hex('#E9E6DE'), .45, .05, .05, .8, .45*.05),
        "red": material("安全红", linear_hex('#B3261E'), .45, .05, .05),
        "yellow": material("电气房黄", linear_hex('#E0A21B'), .45, .05, .05),
        "metal": material("钢材", (.23,.27,.29), .28, .82),
        "rope": material("钢丝绳", (.14,.17,.19), .34, .8, 0),
        "grate": material("深灰格栅", (.065,.08,.085), .48, .7),
        "rubber": material("缓冲器", (.022,.027,.029), .8, 0, 0),
        "glass": material("司机室玻璃", (.27,.46,.52), .12, .05, 0),
        "concrete": material("混凝土", concrete, .8, 0, .12, .055, .1),
        "foundation": material("基础混凝土", tuple(c*1.12 for c in concrete), .8, 0, .10, .055, .1),
        "seam": material("浅伸缩缝", tuple(c*.9 for c in concrete), .8, 0, .12, .055, .1),
        "hull": material("船段防锈底漆", linear_hex('#7A3B2A'), .72, .08, .28, .7, .1),
        "water": material("船坞水面", linear_hex('#1E3A40'), .04, .15, 0),
        "warehouse": material("远景厂房", linear_hex('#4F5965'), .8, .05, .08, .08),
        "roof": material("厂房屋顶", linear_hex('#49515C'), .7, .15, .06),
        "skylight": material("天窗条", linear_hex('#84969E'), .25, .15, 0),
        "silhouette": material("远景门机", linear_hex('#39434B'), .8, .05, 0),
    }
    glass = mats["glass"].node_tree.nodes.get("Principled BSDF")
    set_input(glass, "Transmission Weight", .92)
    set_input(glass, "IOR", 1.45)
    hazard = material("黄黑斜纹", (.8,.5,.02), .45, .2, 0)
    nodes, links = hazard.node_tree.nodes, hazard.node_tree.links
    coord = nodes.new("ShaderNodeTexCoord")
    wave = nodes.new("ShaderNodeTexWave")
    set_attr(wave, "wave_type", "BANDS")
    set_attr(wave, "bands_direction", "DIAGONAL")
    set_input(wave, "Scale", 1.7)
    link_input(links, coord, "Object", wave, "Vector")
    ramp = nodes.new("ShaderNodeValToRGB")
    set_attr(ramp.color_ramp, "interpolation", "CONSTANT")
    set_attr(ramp.color_ramp.elements[0], "color", (.015,.019,.018,1))
    set_attr(ramp.color_ramp.elements[1], "position", .5)
    set_attr(ramp.color_ramp.elements[1], "color", (.95,.59,.025,1))
    link_input(links, wave, "Fac", ramp, "Fac")
    link_input(links, ramp, "Color", nodes.get("Principled BSDF"), "Base Color")
    mats["hazard"] = hazard
    # 混凝土第一层为米级色斑，第二层为毫米级颗粒；水面保持细微波纹。
    for name, scale, strength, distance in (
        ("concrete", 32, .22, .012), ("foundation", 32, .22, .012),
        ("seam", 32, .22, .012), ("hull", 7, .18, .018),
        ("water", 2.5, .18, .035), ("grate", 18, .5, .035),
    ):
        mat = mats[name]
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        coord = nodes.new("ShaderNodeTexCoord")
        tex = nodes.new("ShaderNodeTexNoise" if name != "grate" else "ShaderNodeTexWave")
        set_input(tex, "Scale", scale)
        link_input(links, coord, "Object", tex, "Vector")
        bump = nodes.new("ShaderNodeBump")
        set_input(bump, "Strength", strength)
        set_input(bump, "Distance", distance)
        link_input(links, tex, "Fac", bump, "Height")
        link_input(links, bump, "Normal", nodes.get("Principled BSDF"), "Normal")
    return mats


def hull_profile() -> list[tuple[float, float]]:
    """截面 (横向 z, 离船底高度)：22 m 宽、14 m 高、舭部半径 4 m。"""
    profile = [(-11.0, 14.0), (-11.0, 4.0)]
    for i in range(1, 13):
        angle = math.pi + i*math.pi/24
        profile.append((-7+4*math.cos(angle), 4+4*math.sin(angle)))
    profile.append((7.0, 0.0))
    for i in range(1, 13):
        angle = -math.pi/2 + i*math.pi/24
        profile.append((7+4*math.cos(angle), 4+4*math.sin(angle)))
    profile.append((11.0, 14.0))
    return profile


def ship_block(g: Geometry) -> None:
    bottom, center_z = 1.2, -15.0
    profile = hull_profile()
    count = len(profile)
    outer = [(x, bottom+y, center_z+z) for x in (-18, 18) for z,y in profile]
    # 0.16 m 壳厚，开口顶缘与两端壳板封边，不封闭船段上方。
    inner_profile = [(z*.985, y+.16 if y < 4 else y) for z,y in profile]
    inner = [(x, bottom+y, center_z+z) for x in (-18, 18) for z,y in inner_profile]
    faces = [(i, i+count, i+count+1, i+1) for i in range(count-1)]
    faces += [(i+2*count, i+2*count+1, i+3*count+1, i+3*count) for i in range(count-1)]
    for offset in (0, count):
        faces += [(offset+i, offset+i+2*count, offset+i+1+2*count, offset+i+1) for i in range(count-1)]
    for i in (0, count-1):
        faces.append((i, i+count, i+3*count, i+2*count))
    g.mesh("hull", "hull", outer+inner, faces)
    # 纵骨沿 x 延伸；沿整个内壳弧长每 0.8 m 布置一根细板条。
    walked, next_rib = 0.0, .8
    for (z0,y0), (z1,y1) in zip(inner_profile, inner_profile[1:]):
        dz, dy = z1-z0, y1-y0
        distance = math.hypot(dz, dy)
        while next_rib <= walked+distance:
            ratio = (next_rib-walked)/distance
            z, y = z0+dz*ratio, y0+dy*ratio
            nz, ny = -dy/distance, dz/distance
            verts = [(x, bottom+y+ny*d, center_z+z+nz*d)
                     for x in (-17.96,17.96) for d in (0,.32)]
            g.mesh("hull_frames", "hull", verts, [(0,2,3,1)])
            next_rib += .8
        walked += distance
    for x in (-12, 0, 12):
        section = [(x,bottom+y,center_z+z) for z,y in inner_profile]
        # 横舱壁保留顶面开放，薄板沿周边加一圈框材。
        g.mesh("hull_bulkheads", "hull", section, [tuple(range(count))])
        g.tube("hull_frames", section+[section[0]], .065, "hull")
    for x in range(-18, 19, 6):
        section = [(x,bottom+y-.018,center_z+z*1.0015) for z,y in profile]
        g.tube("hull_welds", section, .035, "hull", 6)
    for x in (-12, 0, 12):
        for z in (-5, 5):
            g.box("hull_support", (3.5,1.2,3), (x,.6,center_z+z), "foundation")


def yard(g: Geometry, dim: Dimensions) -> None:
    # 3 km 地坪在一侧开 60 m 船坞；地面顶标高为零。
    dock_x, half = -dim.span/2-70, 30
    left, right = dock_x-half, dock_x+half
    for lo,hi in ((-1500,left), (right,1500)):
        g.box("ground", (hi-lo,.4,3000), ((lo+hi)/2,-.2,0), "concrete")
    for lo,hi in ((-1500,-100), (100,1500)):
        g.box("ground", (60,.4,hi-lo), (dock_x,-.2,(lo+hi)/2), "concrete")
    g.box("water", (60,.05,200), (dock_x,-1.4,0), "water")
    for x in (left,right):
        g.box("dock", (.8,5.0,200), (x,-2.5,0), "concrete")
    for z in (-100,100):
        g.box("dock", (60,5,.8), (dock_x,-2.5,z), "concrete")
    for x in (-dim.span/2,dim.span/2):
        g.box("foundation", (2.8,.35,124), (x,-.155,0), "foundation")
    # 仅单向、低对比伸缩缝，避免十字网格；不叠加亮色轨枕线。
    for z in range(-1494,1500,12):
        spans = ((-1500,left-.4), (right+.4,1500)) if -100 <= z <= 100 else ((-1500,1500),)
        for lo,hi in spans:
            g.box("ground_seams", (hi-lo,.002,.03), ((lo+hi)/2,.001,z), "seam")

    ship_block(g)
    for i in range(8):
        x, z = -245+i*70, -275-(i%3)*45
        w, h, d = 54, (12,18,25,15)[i%4]-3, 48
        g.box("warehouse", (w,h,d), (x,h/2,z), "warehouse")
        for end in (-1,1):
            g.mesh("warehouse", "warehouse",
                   [(x-w/2,h,z+end*d/2), (x+w/2,h,z+end*d/2), (x,h+3,z+end*d/2)],
                   [(0,1,2) if end == 1 else (2,1,0)])
        # 双坡屋面，天窗条跟随坡面，避免误做成立面窗户。
        for side in (-1,1):
            def roof_point(dx: float, dz: float, offset: float = 0) -> Vec3:
                return (x+dx, h+3*(1-abs(dx)/(w/2))+offset, z+dz)
            g.mesh("warehouse", "roof",
                   [roof_point(dx,dz) for dx,dz in ((0,-d/2),(side*w/2,-d/2),(side*w/2,d/2),(0,d/2))],
                   [(3,2,1,0) if side == 1 else (0,1,2,3)])
            for dz in (-14,0,14):
                g.mesh("warehouse", "skylight",
                       [roof_point(dx,zz,.05) for dx,zz in ((side*5,dz-1.1),(side*23,dz-1.1),
                                                          (side*23,dz+1.1),(side*5,dz+1.1))],
                       [(3,2,1,0) if side == 1 else (0,1,2,3)])
    # 远景门机位于厂房外侧，不与主门机重叠成同一轮廓。
    for cx,cz,w,h in ((-170,-230,54,38),(200,-370,66,46)):
        g.box("distant_crane", (w,3,4), (cx,h-1.5,cz), "silhouette")
        g.box("distant_crane", (7,3,5), (cx+8,h+1.5,cz), "silhouette")
        for side in (-1,1):
            x = cx+side*(w/2-4)
            for depth in (-1,1):
                g.bar("distant_crane", (x,1,cz+depth*7), (x,h-3,cz+depth*1.5), 1.4, material="silhouette")
            g.box("distant_crane", (2,1.4,17), (x,.7,cz), "silhouette")
        g.bar("distant_crane", (cx+8,h,cz), (cx+8,h*.42,cz), .10, material="silhouette")


def sky_nodes(nodes: Any, links: Any, rotation: float) -> tuple[Any, Any]:
    sky = nodes.new("ShaderNodeTexSky")
    for name, value in {"sky_type":"MULTIPLE_SCATTERING", "sun_elevation":math.radians(9),
                        "sun_rotation":rotation, "sun_disc":True, "sun_intensity":1.0,
                        "sun_size":math.radians(.6), "altitude":.1, "air_density":1.0,
                        "aerosol_density":2.0, "ozone_density":1.0}.items():
        set_attr(sky, name, value)
    tone = nodes.new("ShaderNodeHueSaturation")
    set_input(tone, "Saturation", 1.15)
    set_input(tone, "Value", .15)
    link_input(links, sky, "Color", tone, "Color")
    return sky, tone


def ground_haze(mats: dict[str, Any], rotation: float) -> None:
    """800 m 外才混入同方向的地平线天空；近处保持真实受光与长投影。"""
    for name in ("concrete", "seam"):
        nodes, links = mats[name].node_tree.nodes, mats[name].node_tree.links
        distance = nodes.new("ShaderNodeCameraData")
        fade = nodes.new("ShaderNodeMapRange")
        set_attr(fade, "clamp", True)
        set_input(fade, "From Min", 800)
        set_input(fade, "From Max", 1500)
        link_input(links, distance, "View Distance", fade, "Value")
        incoming = nodes.new("ShaderNodeNewGeometry")
        horizontal = nodes.new("ShaderNodeVectorMath")
        horizontal.operation = "MULTIPLY"
        horizontal.inputs[1].default_value = (-1,-1,0)
        links.new(incoming.outputs["Incoming"], horizontal.inputs[0])
        normalized = nodes.new("ShaderNodeVectorMath")
        normalized.operation = "NORMALIZE"
        links.new(horizontal.outputs["Vector"], normalized.inputs[0])
        sky, tone = sky_nodes(nodes, links, rotation)
        link_input(links, normalized, "Vector", sky, "Vector")
        haze = nodes.new("ShaderNodeEmission")
        set_input(haze, "Strength", .5)
        link_input(links, tone, "Color", haze, "Color")
        mixed = nodes.new("ShaderNodeMixShader")
        link_input(links, fade, "Result", mixed, "Fac")
        links.new(nodes.get("Principled BSDF").outputs["BSDF"], mixed.inputs[1])
        links.new(haze.outputs["Emission"], mixed.inputs[2])
        link_input(links, mixed, "Shader", nodes.get("Material Output"), "Surface")


def environment(dim: Dimensions, mats: dict[str, Any], midpoint_azimuth: float = 35) -> None:
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("傍晚天空")
    scene.world.use_nodes = True
    nodes, links = scene.world.node_tree.nodes, scene.world.node_tree.links
    elevation = math.radians(9)
    # 左侧 65° 主光：可见正面受光、可见侧面背光，避免只照到门机背面。
    azimuth = math.radians(midpoint_azimuth-65)
    direction = Vector(to_blender((math.sin(azimuth)*math.cos(elevation), math.sin(elevation),
                                   math.cos(azimuth)*math.cos(elevation))))
    rotation = math.radians(midpoint_azimuth-65-90)
    _, tone = sky_nodes(nodes, links, rotation)
    link_input(links, tone, "Color", nodes.get("Background"), "Color")
    set_input(nodes.get("Background"), "Strength", .5)
    ground_haze(mats, rotation)
    data = bpy.data.lights.new("傍晚侧光", "SUN")
    # 太阳为主光；最终曝光由门机透明背景探测图测量。
    set_attr(data, "energy", 1.6)
    set_attr(data, "angle", math.radians(.6))
    set_attr(data, "color", (1,.79,.60))
    set_attr(data, "use_shadow", True)
    sun = bpy.data.objects.new("傍晚侧光", data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (-direction).to_track_quat('-Z','Y').to_euler()
    set_attr(scene.view_settings, "view_transform", "AgX")
    set_attr(scene.view_settings, "look", "AgX - Medium High Contrast")
    set_attr(scene.view_settings, "exposure", 0.0)
    g = Geometry(mats, {})
    yard(g, dim)
    g.finish()
