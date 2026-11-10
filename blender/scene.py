"""船厂环境、傍晚侧光与程序化表面。"""
from __future__ import annotations

import math
import random
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
    concrete = linear_hex('#9A968F')
    mats = {
        "paint": material("暖白涂装", linear_hex('#E9E6DE'), .45, .05, .05, .8, .45*.05),
        "red": material("安全红", linear_hex('#B3261E'), .45, .05, .05),
        "yellow": material("电气房黄", linear_hex('#E0A21B'), .45, .05, .05),
        "metal": material("钢材", (.23,.27,.29), .28, .82),
        "rail_top": material("钢轨顶面", (.32,.35,.38), .25, 1, 0),
        "marking": material("磨损安全标线", linear_hex('#D9A400'), .78, 0, .32, 9, .08),
        "plate": material("深灰钢板", linear_hex('#42474B'), .55, .8, .1, .8),
        "rust": material("钢板边缘锈迹", linear_hex('#80513B'), .85, .15, .3, 5),
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


def ground_disk(g: Geometry, dock_x: float) -> None:
    """8 km 圆盘保留矩形船坞开口；射线连接内外边界，避免重叠地面。"""
    angles = sorted({i*math.tau/256 for i in range(256)} |
                    {math.atan2(z,x) % math.tau for x in (-30,30) for z in (-100,100)})
    vertices = []
    for angle in angles:
        dx, dz = math.cos(angle), math.sin(angle)
        inner = min(30/abs(dx) if abs(dx)>1e-10 else math.inf,
                    100/abs(dz) if abs(dz)>1e-10 else math.inf)
        outer = -dock_x*dx + math.sqrt(8000**2-dock_x**2*dz**2)
        vertices.extend(((dock_x+inner*dx,0,inner*dz), (dock_x+outer*dx,0,outer*dz)))
    count = len(angles)
    g.mesh("ground", "concrete", vertices,
           [(2*i,2*((i+1)%count),2*((i+1)%count)+1,2*i+1) for i in range(count)])


def foreground(g: Geometry, dim: Dimensions) -> None:
    # 两侧低矮参照物避开支腿；不在吊钩下方放置高物体。
    for i in range(3):
        x, z = i*3.8, 60+i*4
        for layer in range(6):
            y = .1+layer*.2
            g.box("steel_plates", (12,.2,3), (x,y,z), "plate")
            for side in (-1,1):
                g.box("plate_rust", (12,.025,.035), (x,y+.07,z+side*1.48), "rust")
        # 板垛总高 1.2 m，细缝分层。
    x,z = dim.span*.43, 60
    g.box("transport_flatbed", (9.4,.4,3), (x-1.3,1.15,z), "plate")
    g.box("transport_cab", (2.6,2.3,2.8), (x+4.7,1.85,z), "yellow")
    g.box("transport_window", (1.8,.85,.04), (x+4.7,2.35,z+1.42), "glass")
    g.box("transport_windscreen", (.04,.85,2.35), (x+6.02,2.35,z), "glass")
    for axle in (-4,-2.5,4.7):
        for side in (-1,1):
            g.cylinder("transport_wheels", (x+axle,.65,z+side*1.2),
                       (x+axle,.65,z+side*1.65), .65, "rubber", 16)


def warehouses(g: Geometry) -> None:
    rng = random.Random(15)
    base = linear_hex('#4F5965')
    horizon = linear_hex('#B9A99A')
    for row in range(2):
        for i in range(7):
            x, z = -210+i*70+row*15, -280-row*170-rng.uniform(0,25)
            w, d, peak = 54, 48, rng.uniform(12,28)
            h = peak-3
            variation = rng.uniform(.92,1.08)
            air = .28 if row else 0
            color = tuple(c*variation*(1-air)+a*air for c,a in zip(base,horizon))
            key = f"warehouse_{row}_{i}"
            g.materials[key] = material("厂房立面",color,.8,.05,.04,.08)
            roof_key = f"roof_{row}_{i}"
            g.materials[roof_key] = material("厂房屋面",tuple(c*.92 for c in color),.7,.15,.04)
            g.box("warehouse", (w,h,d), (x,h/2,z), key)
            for side in (-1,1):
                g.box("warehouse", (w-3,1.4,.06), (x,h*.65,z+side*(d/2+.04)), "skylight")
                g.box("warehouse", (.06,1.4,d-3), (x+side*(w/2+.04),h*.65,z), "skylight")
            if i % 2 == 0:
                for end in (-1,1):
                    g.mesh("warehouse", key,
                           [(x-w/2,h,z+end*d/2),(x+w/2,h,z+end*d/2),(x,peak,z+end*d/2)],
                           [(0,1,2) if end == 1 else (2,1,0)])
                for side in (-1,1):
                    g.mesh("warehouse", roof_key,
                           [(x,h+3,z-d/2),(x+side*w/2,h,z-d/2),
                            (x+side*w/2,h,z+d/2),(x,h+3,z+d/2)],
                           [(3,2,1,0) if side == 1 else (0,1,2,3)])
            else:
                # 三段锯齿屋面，陡直面作为采光天窗。
                for bay in range(3):
                    lo = x-w/2+bay*w/3
                    hi = lo+w/3
                    g.mesh("warehouse", roof_key,
                           [(lo,h,z-d/2),(hi,peak,z-d/2),(hi,peak,z+d/2),(lo,h,z+d/2)],
                           [(3,2,1,0)])
                    g.box("warehouse", (.08,3,d), (hi,h+1.5,z), "skylight")
                    for end in (-1,1):
                        g.mesh("warehouse", key,
                               [(lo,h,z+end*d/2),(hi,h,z+end*d/2),(hi,peak,z+end*d/2)],
                               [(0,1,2) if end == 1 else (2,1,0)])


def yard(g: Geometry, dim: Dimensions) -> None:
    dock_x, half = -dim.span/2-70, 30
    left, right = dock_x-half, dock_x+half
    ground_disk(g,dock_x)
    g.box("water", (60,.05,200), (dock_x,-1.4,0), "water")
    for x in (left,right):
        g.box("dock", (.8,5.0,200), (x,-2.5,0), "concrete")
    for z in (-100,100):
        g.box("dock", (60,5,.8), (dock_x,-2.5,z), "concrete")
    for x in (-dim.span/2,dim.span/2):
        g.box("foundation", (1.2,.35,220), (x,-.155,20), "foundation")
        # 近端延伸至相机下方，原始轨道节点及其外包尺寸不变。
        for z in (-75,95):
            g.box("rail_extension", (.24,.22,30 if z < 0 else 70), (x,.13,z), "metal")
            g.box("rail_extension", (.32,.08,30 if z < 0 else 70), (x,.28,z), "rail_top")
        for side in (-1,1):
            g.box("safety_lines", (.15,.004,220), (x+side*2,.004,20), "marking")
    g.box("parking_line", (dim.span-5,.004,.15), (0,.004,57), "marking")
    for z in range(-498,500,12):
        spans = ((-500,left-.4),(right+.4,500)) if -100 <= z <= 100 else ((-500,500),)
        for lo,hi in spans:
            g.box("ground_seams", (hi-lo,.002,.03), ((lo+hi)/2,.001,z), "seam")
    ship_block(g)
    foreground(g,dim)
    warehouses(g)
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
    for name, value in {"sky_type":"MULTIPLE_SCATTERING", "sun_elevation":math.radians(13),
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
    """500 m 起混合同方向零仰角天空，3 km 完全融合，避免地平线暗缝。"""
    for name in ("concrete", "seam"):
        nodes, links = mats[name].node_tree.nodes, mats[name].node_tree.links
        distance = nodes.new("ShaderNodeCameraData")
        fade = nodes.new("ShaderNodeMapRange")
        set_attr(fade, "clamp", True)
        set_input(fade, "From Min", 500)
        set_input(fade, "From Max", 3000)
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
        set_input(haze, "Strength", .7)
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
    elevation = math.radians(13)
    # 左侧 65° 主光：可见正面受光、可见侧面背光，避免只照到门机背面。
    azimuth = math.radians(midpoint_azimuth-65)
    direction = Vector(to_blender((math.sin(azimuth)*math.cos(elevation), math.sin(elevation),
                                   math.cos(azimuth)*math.cos(elevation))))
    rotation = math.radians(midpoint_azimuth-65-90)
    sky, tone = sky_nodes(nodes, links, rotation)
    # 圆盘以外仍有不到一像素的负仰角射线；钳到零仰角，避免露出暗天空下半球。
    incoming = nodes.new("ShaderNodeNewGeometry")
    direction_node = nodes.new("ShaderNodeVectorMath")
    direction_node.operation = "MULTIPLY"
    direction_node.inputs[1].default_value = (-1,-1,-1)
    links.new(incoming.outputs["Incoming"],direction_node.inputs[0])
    horizon = nodes.new("ShaderNodeVectorMath")
    horizon.operation = "MAXIMUM"
    horizon.inputs[1].default_value = (-1,-1,0)
    links.new(direction_node.outputs["Vector"],horizon.inputs[0])
    normalized = nodes.new("ShaderNodeVectorMath")
    normalized.operation = "NORMALIZE"
    links.new(horizon.outputs["Vector"],normalized.inputs[0])
    link_input(links,normalized,"Vector",sky,"Vector")
    link_input(links, tone, "Color", nodes.get("Background"), "Color")
    set_input(nodes.get("Background"), "Strength", .7)
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
