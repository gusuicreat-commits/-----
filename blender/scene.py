"""船厂环境、晴天下午侧光与程序化表面。"""
from __future__ import annotations

import math
import random
from typing import Any

import bpy
from mathutils import Vector

from common import Dimensions, Vec3, link_input, set_attr, set_input, to_blender, worker_layout
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
    concrete = linear_hex('#9C968C')
    mats = {
        "paint": material("橙红清漆涂装", linear_hex('#D9461C'), .32, .05, .04, .8, .016),
        "red": material("橙红端梁", linear_hex('#D9461C'), .32, .05, .04),
        "electrical": material("浅灰电气房", linear_hex('#D8DCDF'), .32, .05),
        "yellow": material("安全黄", linear_hex('#E0A21B'), .45, .05, .05),
        "metal": material("钢材", (.23,.27,.29), .28, .82),
        "rail_top": material("钢轨顶面", (.32,.35,.38), .25, 1, 0),
        "marking": material("磨损安全标线", linear_hex('#D9A400'), .78, 0, .32, 9, .08),
        "plate": material("深灰钢板", linear_hex('#42474B'), .55, .8, .1, .8),
        "rust": material("钢板边缘锈迹", linear_hex('#80513B'), .85, .15, .3, 5),
        "rope": material("钢丝绳", (.14,.17,.19), .34, .8, 0),
        "grate": material("深灰格栅", (.065,.08,.085), .48, .7),
        "rubber": material("缓冲器", (.022,.027,.029), .8, 0, 0),
        "glass": material("司机室玻璃", (.27,.46,.52), .12, .05, 0),
        "concrete": material("混凝土", concrete, .8, 0, .08, .055, .1),
        "foundation": material("基础混凝土", tuple(c*1.02 for c in concrete), .8, 0, .10, .055, .1),
        "seam": material("浅伸缩缝", tuple(c*.65 for c in concrete), .8, 0, .12, .055, .1),
        "stain": material("轮胎与油渍", linear_hex("#514B41"), .92, 0, .3, 2),
        "frame": material("深灰窗框", linear_hex("#343A3E"), .4, .2, 0),
        "hull": material("船段防锈底漆", linear_hex('#7A3B2A'), .72, .08, .28, .7, .1),
        "water": material("船坞水面", linear_hex('#1E3A40'), .04, .15, 0),
        "warehouse": material("远景厂房", linear_hex('#E5E7E7'), .8, .05, .08, .08),
        "roof": material("厂房屋顶", linear_hex('#49515C'), .7, .15, .06),
        "skylight": material("天窗条", linear_hex('#84969E'), .25, .15, 0),
        "silhouette": material("远景门机", linear_hex('#39434B'), .8, .05, 0),
    }
    for key,color,roughness in (
        ("white","#E7E9E8",.65),("blue","#2C5FA8",.5),("wall","#CCC7BD",.65),
        ("window","#7699B0",.05),("grass_a","#517E4C",.9),("grass_b","#628D56",.9),
        ("vest","#C9E339",.7),("skin","#C79C7C",.8),("navy","#374958",.8),
        ("container_red","#976F63",.65),("container_green","#6E867C",.65)):
        mats[key] = material("场景_"+key,linear_hex(color),roughness,.25 if key == "window" else .05)
    for key in ("paint","red"):
        nodes,links = mats[key].node_tree.nodes,mats[key].node_tree.links
        shader = nodes.get("Principled BSDF")
        set_input(shader,"Coat Weight",.25)
        set_input(shader,"Coat Roughness",.2)
        base = shader.inputs["Base Color"].links[0].from_socket
        ao = nodes.new("ShaderNodeAmbientOcclusion")
        set_input(ao,"Distance",.12)
        wear = nodes.new("ShaderNodeMath")
        wear.operation = "MULTIPLY_ADD"
        links.new(ao.outputs["AO"],wear.inputs[0])
        wear.inputs[1].default_value = -.12
        wear.inputs[2].default_value = .12
        mix = nodes.new("ShaderNodeMixRGB")
        links.new(wear.outputs[0],mix.inputs[0])
        links.new(base,mix.inputs[1])
        mix.inputs[2].default_value = (*linear_hex("#9E3216"),1)
        links.new(mix.outputs[0],shader.inputs["Base Color"])
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
                    {math.atan2(z,x) % math.tau for x in (-30,30) for z in (-60,60)})
    vertices = []
    for angle in angles:
        dx, dz = math.cos(angle), math.sin(angle)
        inner = min(30/abs(dx) if abs(dx)>1e-10 else math.inf,
                    60/abs(dz) if abs(dz)>1e-10 else math.inf)
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
    g.box("transport_flatbed", (9.4,.4,3), (x-1.3,1.35,z), "plate")
    g.box("transport_cab", (2.6,2.3,2.8), (x+4.7,1.85,z), "yellow")
    g.box("transport_window", (1.8,.85,.04), (x+4.7,2.35,z+1.42), "glass")
    g.box("transport_windscreen", (.04,.85,2.35), (x+6.02,2.35,z), "glass")
    g.box("transport_chassis", (12,.3,2.4), (x,1.05,z), "metal")
    for axle in (-4,-2.5,4.7):
        for side in (-1,1):
            g.cylinder("transport_wheels", (x+axle,.52,z+side*.92),
                       (x+axle,.52,z+side*1.38), .52, "rubber", 16)


def warehouses(g: Geometry) -> None:
    for i,(x,z,length,h) in enumerate(((-200,-340,120,32),(200,-400,120,34),(-340,-440,120,30))):
        node = f"decor_factory_{i}"
        g.box(node,(length,h,66),(x,h/2,z),"warehouse")
        for side in (-1,1):
            g.box(node,(.2,22,28),(x+side*(length/2+.12),11,z),"blue")
        # 压型板细脊合并在同一网格中，不为每条肋创建对象。
        for j in range(int(length)):
            g.box(node,(.09,h,.12),(x-length/2+j,h/2,z+33.06),"white")
        for dx in (-length*.26,length*.26):
            g.box(node,(26,23,.2),(x+dx,11.5,z+33.2),"blue")
            for level in range(1,12):
                g.box(node,(26,.06,.23),(x+dx,level*1.9,z+33.22),"skylight")
        for side in (-1,1):
            g.mesh(node,"white",[(x-length/2,h,z+side*33),(x+length/2,h,z+side*33),
                                  (x+length/2,h+4,z),(x-length/2,h+4,z)],[(0,1,2,3)])
            for dx in (-length*.3,0,length*.3):
                g.mesh(node,"skylight",[(x+dx-3,h+4.02,z),(x+dx+3,h+4.02,z),
                                        (x+dx+3,h+1,z+side*25),(x+dx-3,h+1,z+side*25)],[(0,1,2,3)])


def crawler(g: Geometry, index: int, x: float, z: float, length: float, angle: float) -> None:
    node = f"decor_crawler_{index}"
    for side in (-1,1):
        g.box(node,(11,1.6,1.7),(x,1,z+side*2.7),"rubber")
        for dx in range(-4,5,2):
            g.cylinder(node,(x+dx,1,z+side*3.5),(x+dx,1,z+side*3.6),.65,"metal",12)
    g.box(node,(8,2.8,4.5),(x,3.2,z),"yellow")
    g.box(node,(2.6,2.8,2),(x+3,4,z+2),"electrical")
    g.box(node,(2.3,1.7,.06),(x+3,4.3,z+3.02),"window")
    a = math.radians(angle)
    sign = -1 if x < 0 else 1
    def point(t: float,j: int) -> Vec3:
        # 三角格构断面，臂架朝场景外侧斜伸。
        cross = ((-1.5,-1),(1.5,-1),(0,1.6))[j]
        return (x+sign*t*length*math.cos(a)+cross[0]*math.sin(a),
                5+t*length*math.sin(a)-sign*cross[0]*math.cos(a),z+cross[1])
    bays = math.ceil(length/5)
    for i in range(bays):
        color = "red" if i//3%2 == 0 else "white"
        for j in range(3):
            g.cylinder(node,point(i/bays,j),point((i+1)/bays,j),.16,color,8)
            g.cylinder(node,point(i/bays,j),point(i/bays,(j+1)%3),.09,color,6)
            g.cylinder(node,point(i/bays,j),point((i+1)/bays,(j+1)%3),.075,color,6)
    tip = point(1,2)
    for dz in (-2,2):
        g.cylinder(node,(x-4,5,z+dz),tip,.055,"rope",6)
    hook = (tip[0],18,tip[2])
    g.cylinder(node,tip,hook,.045,"rope",6)
    g.box(node,(.9,1.6,.6),hook,"metal")
    g.tube(node,[(hook[0],17.3,z),(hook[0]-.45,16.8,z),(hook[0],16.3,z),(hook[0]+.5,16.7,z)],.12,"metal")


def rotate_node(g: Geometry, node: str, x: float, z: float, yaw: float) -> None:
    c,s = math.cos(yaw),math.sin(yaw)
    for (key,_,_), (vertices,_,_) in g.batches.items():
        if key == node:
            vertices[:] = [(x+(vx-x)*c-(-vy-z)*s,
                            -(z+(vx-x)*s+(-vy-z)*c),vz) for vx,vy,vz in vertices]
    g.node_transforms[node] = (x,z,yaw)


def industrial_skyline(g: Geometry) -> None:
    rng = random.Random(1904)
    for i in range(28):
        x,z = -1300+i*85,-720-rng.uniform(0,130)
        w,h,d = rng.uniform(70,90),rng.uniform(14,29),rng.uniform(65,110)
        g.box("industrial_skyline",(w,h,d),(x,h/2,z),"warehouse")
        g.mesh("industrial_skyline","roof",[(x+dx,y,z+dz) for dx in (-w/2,w/2)
               for dz,y in ((-d/2,h),(0,h+3+i%4),(d/2,h))],[(0,3,4,1),(1,4,5,2)])


def yard_details(g: Geometry, dim: Dimensions) -> None:
    crawler(g,0,-dim.length/2-100,-170,92,70)
    crawler(g,1,dim.length/2+160,-230,108,67)
    for i,(x,z,h) in enumerate(((-360,-440,80),(340,-470,94))):
        node = f"decor_chimney_{i}"
        g.cylinder(node,(x,0,z),(x,h-20,z),2.2,"white",16)
        for j in range(5):
            g.cylinder(node,(x,h-20+j*4,z),(x,h-16+j*4,z),2,"red" if j%2 == 0 else "white",16)
    for i in range(7):
        x,z = (-1 if i%2 else 1)*(dim.length/2+35+i*8),-65-i*13
        node = f"decor_stock_{i}"
        w,h,d = 10+i*2,3+i%3*2,7+i
        color = "hull" if i%2 else "plate"
        g.box(node,(w,.3,d),(x,1,z),color)
        for side in (-1,1):
            g.box(node,(w,h,.22),(x,1+h/2,z+side*d/2),color)
        for dx in (-w/2,0,w/2):
            g.bar(node,(x+dx,1,z-d/2),(x+dx,h+1,z+d/2),.22,material=color)
    for i in range(8):
        x,z = dim.length/2+85+(i%4)*13,-100-(i//4)*4
        node = f"decor_container_{i}"
        color = ("container_red","container_green","blue","electrical")[i%4]
        g.box(node,(12.2,2.6,2.44),(x,1.3,z),color)
        for j in range(30):
            g.box(node,(.07,2.5,.08),(x-6+j*.4,1.3,z+1.25),color)
    for i,worker in enumerate(worker_layout(dim)):
        x,z = worker["x"],worker["z"]
        node = f"decor_worker_{i}"
        stride = .22 if worker["walking"] else 0
        for sign in (-1,1):
            g.bar(node,(x+sign*.11,.08,z+sign*stride),(x+sign*.1,.87,z),.12,material="navy")
            g.bar(node,(x+sign*.23,1.36,z),(x+sign*.3,.96,z-sign*stride),.1,material="navy")
        g.box(node,(.4,.55,.24),(x,1.13,z),"red" if i%2 else "vest")
        g.box(node,(.41,.06,.25),(x,1.12,z),"white")
        g.cylinder(node,(x,1.43,z),(x,1.65,z),.12,"skin",10)
        g.cylinder(node,(x,1.63,z),(x,1.75,z),.16,"yellow" if i%3 else "white",12)
        rotate_node(g,node,x,z,worker["yaw"])
    for i in range(3):
        node = f"decor_vehicle_{i}"
        x,z = dim.length/2+18+i*8,35+i*8
        pickup = i == 2
        g.box(node,(5 if pickup else 2.8,.7,1.8),(x,.85,z),"electrical" if pickup else "yellow")
        g.box(node,(1.8,1.1,1.65),(x+.3,1.7,z),"window")
        g.box(node,(2,.12,1.8),(x+.3,2.3,z),"electrical" if pickup else "yellow")
        for dx in (-1,1):
            for side in (-1,1):
                g.cylinder(node,(x+dx,.45,z+side*.8),(x+dx,.45,z+side*1.05),.43,"rubber",12)
        if not pickup:
            for dz in (-.6,.6):
                g.bar(node,(x+1.5,.2,z+dz),(x+1.5,3.8,z+dz),.13,material="metal")
                g.box(node,(1.8,.13,.16),(x+2.3,.25,z+dz),"metal")
    for i in range(6):
        x,z = (-1 if i%2 else 1)*(dim.span/2+35),-90+(i//2)*90
        node = f"decor_lamp_{i}"
        g.cylinder(node,(x,0,z),(x,29.5,z),.22,"metal",10)
        g.box(node,(4,.3,1),(x,29.65,z),"metal")
        for dx in (-1.5,-.5,.5,1.5):
            g.box(node,(.7,.2,.8),(x+dx,29.9,z),"white")
    # 海面覆盖远处地面，避免增加地平线接缝。
    g.box("sea",(3500,.05,6000),(2600,.04,-4100),"water")
    for i,x in enumerate((-650,780)):
        node = f"decor_ship_{i}"
        outline = [(-100,-14),(90,-14),(115,0),(90,14),(-100,14)]
        vertices = [(x+dx*scale,y,-1250+dz*scale) for y,scale in ((.2,.85),(12,1)) for dx,dz in outline]
        g.mesh(node,"hull",vertices,[(i,(i+1)%5,(i+1)%5+5,i+5) for i in range(5)]+[(5,6,7,8,9)])
        g.box(node,(40,12,24),(x-55,18,-1250),"white")
        g.box(node,(42,2,24.2),(x-55,21,-1250),"window")
        g.cylinder(node,(x-55,24,-1250),(x-55,34,-1250),.3,"metal",8)



def analogy_reference(g: Geometry, layout: dict[str, Any]) -> None:
    x,_,z = layout["center"]
    if layout["ref"] == "building_floor":
        height = layout["height"]
        # 所有附属屋顶件都在事实高度以内，顶层按剩余层高收口。
        roof_depth = min(.8,layout["floors"][-1]*.18)
        g.box("analogy_ref",(18,height-roof_depth,14),(x,(height-roof_depth)/2,z),"wall")
        y = 0.0
        for index,level in enumerate(layout["floors"]):
            window_height = level*(.84 if index == 0 else .66)
            for side in (-1,1):
                g.box("analogy_ref",(17.6,window_height,.08),
                      (x,y+level*.5,z+side*7.06),"window")
                g.box("analogy_ref",(18.3,.14,.4),(x,y+.08,z+side*7.1),"white")
                for j in range(13):
                    dx = -9+j*1.5
                    g.box("analogy_ref",(.075,window_height,.14),
                          (x+dx,y+level*.5,z+side*7.12),"frame")
                if index == 0:
                    for dx in (-7.5,0,7.5):
                        g.box("analogy_ref",(.35,level,.5),(x+dx,level/2,z+side*7.18),"white")
            y += level
        # 屋顶向内退台，机房顶与女儿墙同高，不改变对照总高。
        g.box("analogy_ref",(6,roof_depth,5),(x,height-roof_depth/2,z),"electrical")
        for side in (-1,1):
            g.box("analogy_ref",(18,.45,.18),(x,height-.225,z+side*7),"white")
    else:
        length,width = layout["length"],layout["width"]
        for i in range(20):
            g.box("analogy_ref",(length/20,.04,width),(-length/2+(i+.5)*length/20,.04,z),"grass_a" if i%2 else "grass_b")
        def stripe(a: Vec3,b: Vec3) -> None:
            g.cylinder("analogy_ref",a,b,.06,"white",6)
        for side in (-1,1):
            stripe((-length/2,.08,z+side*width/2),(length/2,.08,z+side*width/2))
            stripe((side*length/2,.08,z-width/2),(side*length/2,.08,z+width/2))
            for depth,half in ((16.5,20.16),(5.5,9.16)):
                xx = side*(length/2-depth)
                stripe((xx,.08,z-half),(xx,.08,z+half))
                for zz in (-half,half):
                    stripe((xx,.08,z+zz),(side*length/2,.08,z+zz))
            gx = side*length/2
            g.tube("analogy_ref",[(gx,.08,z-3.66),(gx,2.44,z-3.66),(gx,2.44,z+3.66),(gx,.08,z+3.66)],.06,"white")
            for j in range(13):
                zz = z-3.66+j*7.32/12
                g.bar("analogy_ref",(gx,2.44,zz),(gx+side*2,.08,zz),.015,material="white")
        stripe((0,.08,z-width/2),(0,.08,z+width/2))
        g.tube("analogy_ref",[(9.15*math.cos(i*math.tau/64),.08,z+9.15*math.sin(i*math.tau/64)) for i in range(65)],.06,"white")


def yard(g: Geometry, dim: Dimensions) -> None:
    dock_x, half = -dim.span/2-70, 30
    left, right = dock_x-half, dock_x+half
    ground_disk(g,dock_x)
    g.box("water", (60,.05,120), (dock_x,-1.4,0), "water")
    for x in (left,right):
        g.box("dock", (.8,5.0,120), (x,-2.5,0), "concrete")
    for z in (-60,60):
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
    for x in range(-480,481,12):
        if left-.5 < x < right+.5:
            continue
        g.box("ground_seams",(.035,.002,960),(x,.002,0),"seam")
    rng = random.Random(1902)
    for i in range(24):
        x,z = rng.uniform(-70,110),rng.uniform(-100,100)
        if left-3 < x < right+3:
            continue
        radius = rng.uniform(.4,2.2)
        points = [(x+radius*math.cos(j*math.tau/16)*rng.uniform(.8,1.2),.006,
                   z+radius*.65*math.sin(j*math.tau/16)) for j in range(16)]
        g.mesh("ground_stains","stain",points,[tuple(range(16))])
    for x in (18,20,62,64):
        g.box("tire_marks",(.16,.003,22),(x,.005,38),"stain")
    industrial_skyline(g)
    ship_block(g)
    foreground(g,dim)
    warehouses(g)
    yard_details(g,dim)
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


def sky_nodes(nodes: Any, links: Any, rotation: float, look: str = "afternoon") -> tuple[Any, Any]:
    sky = nodes.new("ShaderNodeTexSky")
    for name, value in {"sky_type":"MULTIPLE_SCATTERING", "sun_elevation":math.radians(13 if look == "dusk" else 24),
                        "sun_rotation":rotation, "sun_disc":False, "sun_intensity":1.0,
                        "sun_size":math.radians(.6), "altitude":.1, "air_density":1.0,
                        "aerosol_density":2.0 if look == "dusk" else 1.2, "ozone_density":1.0}.items():
        set_attr(sky, name, value)
    tone = nodes.new("ShaderNodeHueSaturation")
    set_input(tone, "Saturation", 1.15)
    set_input(tone, "Value", .15 if look == "dusk" else 1.0)
    link_input(links, sky, "Color", tone, "Color")
    return sky, tone


def camera_sky(nodes: Any, links: Any, direction: Any, scene: Any) -> Any:
    """按视线仰角压深蓝天；云只进入相机背景，不增加透明面或阴影开销。"""
    separate = nodes.new("ShaderNodeSeparateXYZ")
    link_input(links,direction,"Vector",separate,"Vector")
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0
    ramp.color_ramp.elements[0].color = (.72,.86,1.0,1)
    ramp.color_ramp.elements[1].position = .30
    ramp.color_ramp.elements[1].color = (.035,.20,.57,1)
    midpoint = ramp.color_ramp.elements.new(.09)
    midpoint.color = (.14,.38,.75,1)
    link_input(links,separate,"Z",ramp,"Fac")
    noise = nodes.new("ShaderNodeTexNoise")
    set_input(noise,"Scale",23)
    set_input(noise,"Detail",3)
    set_input(noise,"Roughness",.65)
    link_input(links,direction,"Vector",noise,"Vector")
    coverage = nodes.new("ShaderNodeValToRGB")
    coverage.color_ramp.elements[0].position = .48
    coverage.color_ramp.elements[0].color = (0,0,0,1)
    coverage.color_ramp.elements[1].position = .60
    coverage.color_ramp.elements[1].color = (1,1,1,1)
    link_input(links,noise,"Fac",coverage,"Fac")
    # 相机坐标仰角阈值每帧由 view_frame 更新，云带锁在画面上三分之一。
    camera_vector = nodes.new("ShaderNodeVectorTransform")
    camera_vector.vector_type = 'VECTOR'
    camera_vector.convert_from, camera_vector.convert_to = 'WORLD','CAMERA'
    link_input(links,direction,"Vector",camera_vector,"Vector")
    components = nodes.new("ShaderNodeSeparateXYZ")
    link_input(links,camera_vector,"Vector",components,"Vector")
    slope = nodes.new("ShaderNodeMath"); slope.operation = 'DIVIDE'
    links.new(components.outputs['Y'],slope.inputs[0])
    negative_z = nodes.new("ShaderNodeMath"); negative_z.operation = 'MULTIPLY'
    links.new(components.outputs['Z'],negative_z.inputs[0]); negative_z.inputs[1].default_value = -1
    links.new(negative_z.outputs[0],slope.inputs[1])
    band = nodes.new("ShaderNodeMapRange"); band.name = 'cloud_band'
    set_attr(band,'clamp',True)
    set_input(band,'From Min',.08); set_input(band,'From Max',.14)
    links.new(slope.outputs[0],band.inputs['Value'])
    mask = nodes.new("ShaderNodeMath"); mask.operation = 'MULTIPLY'
    links.new(coverage.outputs['Color'],mask.inputs[0]); links.new(band.outputs['Result'],mask.inputs[1])
    cloud = nodes.new("ShaderNodeValToRGB")
    cloud.color_ramp.elements[0].position = .55
    cloud.color_ramp.elements[0].color = (.62,.65,.68,1)
    cloud.color_ramp.elements[1].position = .7
    cloud.color_ramp.elements[1].color = (1.65,1.67,1.7,1)
    link_input(links,noise,'Fac',cloud,'Fac')
    mix = nodes.new("ShaderNodeMixRGB")
    links.new(mask.outputs[0],mix.inputs[0]); links.new(ramp.outputs['Color'],mix.inputs[1]); links.new(cloud.outputs['Color'],mix.inputs[2])
    scale = nodes.new("ShaderNodeVectorMath"); scale.operation = 'SCALE'
    links.new(mix.outputs[0],scale.inputs[0])
    # 只补偿相机天空的曝光；环境光、太阳和地面照明仍参与正常测光。
    driver = scale.inputs['Scale'].driver_add('default_value').driver
    variable = driver.variables.new(); variable.name = 'exposure'
    variable.targets[0].id_type = 'SCENE'; variable.targets[0].id = scene
    variable.targets[0].data_path = 'view_settings.exposure'
    driver.expression = '1.8181818 * 2 ** (-exposure)'
    return scale


def environment(dim: Dimensions, mats: dict[str, Any], midpoint_azimuth: float = 35, look: str = "afternoon") -> list[Any]:
    scene = bpy.context.scene
    scene.world = bpy.data.worlds.new("黄昏天空" if look == "dusk" else "晴天下午天空")
    scene.world.use_nodes = True
    nodes, links = scene.world.node_tree.nodes, scene.world.node_tree.links
    elevation = math.radians(13 if look == "dusk" else 24)
    # 下午主光从相机左侧 110° 入射，黄昏保留旧侧光方向。
    azimuth = math.radians(midpoint_azimuth-(65 if look == "dusk" else 110))
    direction = Vector(to_blender((math.sin(azimuth)*math.cos(elevation), math.sin(elevation),
                                   math.cos(azimuth)*math.cos(elevation))))
    rotation = math.radians(midpoint_azimuth-(65 if look == "dusk" else 110)-90)
    sky, tone = sky_nodes(nodes, links, rotation, look)
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
    if look == "dusk":
        link_input(links,tone,"Color",nodes.get("Background"),"Color")
    else:
        visible_sky = camera_sky(nodes,links,normalized,scene)
        light_path = nodes.new("ShaderNodeLightPath")
        mix = nodes.new("ShaderNodeMixRGB")
        links.new(light_path.outputs["Is Camera Ray"],mix.inputs[0])
        links.new(tone.outputs["Color"],mix.inputs[1])
        links.new(visible_sky.outputs["Vector"],mix.inputs[2])
        links.new(mix.outputs[0],nodes.get("Background").inputs["Color"])
    set_input(nodes.get("Background"), "Strength", .7 if look == "dusk" else .55)
    # 世界只提供散射光；禁止将天空中的亮区再次提取成太阳。
    set_attr(scene.world, "sun_threshold", 1e10)
    set_attr(scene.world, "use_sun_shadow", False)
    data = bpy.data.lights.new("太阳侧光", "SUN")
    # 太阳为主光；最终曝光由门机透明背景探测图测量。
    set_attr(data, "energy", 1.6 if look == "dusk" else 5.5)
    set_attr(data, "angle", math.radians(.8))
    set_attr(data, "color", (1,.79,.60) if look == "dusk" else (1,.95,.87))
    set_attr(data, "use_shadow", True)
    set_attr(data, "use_shadow_jitter", True)
    set_attr(getattr(scene, "eevee", None), "use_shadows", True)
    sun = bpy.data.objects.new("太阳侧光", data)
    bpy.context.collection.objects.link(sun)
    sun.rotation_euler = (-direction).to_track_quat('-Z','Y').to_euler()
    set_attr(scene.view_settings, "view_transform", "AgX")
    if look == "dusk" or not set_attr(scene.view_settings, "look", "AgX - Punchy"):
        set_attr(scene.view_settings, "look", "AgX - Medium High Contrast")
    set_attr(scene.view_settings, "exposure", 0.0)
    g = Geometry(mats, {})
    yard(g, dim)
    orient_backdrop(g,midpoint_azimuth)
    objects = g.finish()
    return objects


def orient_backdrop(g: Geometry, azimuth: float) -> None:
    """远侧布景随镜头中位方位布局，保持左右两侧的格构臂架可读。"""
    angle = math.radians(azimuth)
    g.backdrop_angle = angle
    cosine,sine = math.cos(angle),math.sin(angle)
    for (node,_,_), (vertices,_,_) in g.batches.items():
        if node.startswith(("decor_factory_","decor_crawler_","decor_chimney_",
                            "decor_container_","decor_stock_","decor_ship_","industrial_skyline","sea")):
            vertices[:] = [(cosine*x-sine*y,sine*x+cosine*y,z) for x,y,z in vertices]
