"""按核验尺寸生成门机；附属构造为无品牌的工程示意。"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import bpy
from mathutils import Vector

from common import Dimensions, NODES, Vec3, set_attr, to_blender, wheel_distribution


class Geometry:
    """按节点和材质合并几何，减少场景对象和倒角修改器数量。"""
    def __init__(self, materials: dict[str, Any], parents: dict[str, Any]) -> None:
        self.materials, self.parents = materials, parents
        self.batches: dict[tuple[str, str], tuple[list, list, list]] = defaultdict(lambda: ([], [], []))

    def mesh(self, node: str, material: str, vertices: list, faces: list, smooth: bool = False) -> None:
        verts, polys, shading = self.batches[(node, material)]
        offset = len(verts)
        verts.extend(to_blender(tuple(v)) for v in vertices)
        polys.extend(tuple(offset + i for i in face) for face in faces)
        shading.extend([smooth] * len(faces))

    def box(self, node: str, size: Vec3, center: Vec3, material: str = "paint") -> None:
        vertices = [(center[0] + x * size[0] / 2, center[1] + y * size[1] / 2, center[2] + z * size[2] / 2)
                    for x, y, z in ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                                    (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1))]
        self.mesh(node, material, vertices, [(0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5)])

    def bar(self, node: str, start: Vec3, end: Vec3, width: float, depth: float | None = None,
            material: str = "paint") -> None:
        a, b = Vector(start), Vector(end)
        direction = (b - a).normalized()
        reference = Vector((0,0,1)) if abs(direction.z) < .95 else Vector((1,0,0))
        side = direction.cross(reference).normalized() * width / 2
        other = direction.cross(side).normalized() * (depth or width) / 2
        vertices = [tuple(p + s * side + t * other) for p in (a,b) for s,t in ((-1,-1),(1,-1),(1,1),(-1,1))]
        self.mesh(node, material, vertices, [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])

    def cylinder(self, node: str, start: Vec3, end: Vec3, radius: float, material: str = "metal",
                 segments: int = 20) -> None:
        a, b = Vector(start), Vector(end)
        axis = (b - a).normalized()
        reference = Vector((0,1,0)) if abs(axis.y) < .95 else Vector((1,0,0))
        u = axis.cross(reference).normalized()
        v = axis.cross(u).normalized()
        vertices = [tuple(p + radius * (math.cos(i * math.tau / segments) * u + math.sin(i * math.tau / segments) * v))
                    for p in (a,b) for i in range(segments)]
        faces = [(i, (i+1)%segments, (i+1)%segments+segments, i+segments) for i in range(segments)]
        self.mesh(node, material, vertices, faces, True)
        self.mesh(node, material, vertices, [tuple(reversed(range(segments))), tuple(range(segments,2*segments))])

    def tube(self, node: str, points: list[Vec3], radius: float, material: str = "metal", sides: int = 8) -> None:
        vertices = []
        for i, point in enumerate(points):
            tangent = Vector(points[min(i+1,len(points)-1)]) - Vector(points[max(i-1,0)])
            tangent.normalize()
            reference = Vector((0,1,0)) if abs(tangent.y) < .95 else Vector((1,0,0))
            u = tangent.cross(reference).normalized()
            v = tangent.cross(u).normalized()
            vertices.extend(tuple(Vector(point) + radius * (math.cos(j*math.tau/sides)*u + math.sin(j*math.tau/sides)*v)) for j in range(sides))
        faces = [(i*sides+j, i*sides+(j+1)%sides, (i+1)*sides+(j+1)%sides, (i+1)*sides+j)
                 for i in range(len(points)-1) for j in range(sides)]
        self.mesh(node, material, vertices, faces, True)

    def finish(self) -> list[Any]:
        objects = []
        for (node, material), (vertices, faces, shading) in self.batches.items():
            mesh = bpy.data.meshes.new(f"{node}_{material}")
            mesh.from_pydata(vertices, [], faces)
            mesh.update()
            obj = bpy.data.objects.new(mesh.name, mesh)
            bpy.context.collection.objects.link(obj)
            obj.data.materials.append(self.materials[material])
            if node in self.parents:
                obj.parent = self.parents[node]
                obj.matrix_parent_inverse = obj.parent.matrix_world.inverted()
            for polygon, smooth in zip(mesh.polygons, shading):
                polygon.use_smooth = smooth
            if material not in ("rope", "glass", "water", "seam") and node not in (
                "ground", "ground_seams", "warehouse", "distant_crane", "hull_welds", "hull_frames"
            ):
                bevel = obj.modifiers.new("边缘高光", "BEVEL")
                set_attr(bevel, "width", .035)
                set_attr(bevel, "segments", 2)
                set_attr(bevel, "limit_method", "ANGLE")
            objects.append(obj)
        return objects


def curve_hook(parent: Any, dim: Dimensions, material: Any) -> None:
    curve = bpy.data.curves.new("hook_open_curve", "CURVE")
    curve.dimensions, curve.resolution_u = "3D", 16
    curve.bevel_depth, curve.bevel_resolution = .23, 4
    spline = curve.splines.new("BEZIER")
    points = [(0,1.8,0),(0,1.15,0),(-.7,.8,0),(-.8,.15,0),(-.25,-.2,0),(.5,.05,0),(.65,.6,0)]
    spline.bezier_points.add(len(points)-1)
    for p, (x,y,z) in zip(spline.bezier_points, points):
        p.co = to_blender((x,y+dim.hook_height,z))
        p.handle_left_type = p.handle_right_type = "AUTO"
    obj = bpy.data.objects.new("hook_open_curve", curve)
    bpy.context.collection.objects.link(obj)
    obj.parent, obj.matrix_parent_inverse = parent, parent.matrix_world.inverted()
    obj.data.materials.append(material)


def build_crane(dim: Dimensions, materials: dict[str, Any]) -> dict[str, Any]:
    parents = {}
    for name in NODES:
        obj = bpy.data.objects.new(name, None)
        bpy.context.collection.objects.link(obj)
        if name != "crane":
            obj.parent = parents["trolley" if name in ("hoist_hook","rope") else "crane"]
        if name == "trolley":
            obj.location = to_blender((0,dim.girder_top,0))
        elif name == "hoist_hook":
            obj.location = to_blender((0,dim.hook_height-dim.girder_top,0))
        parents[name] = obj
    bpy.context.view_layer.update()
    parents["crane"]["尺寸依据"] = "核验参数；加劲肋、爬梯及附属设施为结构示意"
    parents["crane"]["wheel_count"] = dim.wheel_count
    parents["hoist_hook"]["range_m"] = list(dim.hoist_range)
    g = Geometry(materials, parents)
    length, top, bottom, gh = dim.length, dim.girder_top, dim.girder_bottom, dim.girder_height

    for sign in (-1,1):
        z = sign * 3.2
        g.box("girder", (length,gh,2.6), (0,top-gh/2,z))
        # 外露腹板加劲肋和上下翼缘。
        for face in (-1,1):
            for i in range(math.floor((length-.4)/2.5)+1):
                x = -length/2 + .2 + i * 2.5
                g.box("girder", (.16,gh-.18,.15), (x,top-gh/2,z+face*1.375))
        for y in (bottom+.08, top-.08):
            g.box("girder", (length,.16,2.76), (0,y,z))
        walkway_z = sign*4.9
        g.box("girder", (length,.16,.85), (0,top+.08,walkway_z), "grate")
        for y in (top+.58,top+1.13):
            g.bar("girder", (-length/2+.06,y,sign*5.25), (length/2-.06,y,sign*5.25), .085)
        for i in range(math.ceil(length/2.5)+1):
            x = -length/2+.06+i*(length-.12)/math.ceil(length/2.5)
            g.bar("girder", (x,top+.16,sign*5.25),(x,top+1.17,sign*5.25),.085)
        g.box("girder", (length,.12,.18), (0,top+.06,z), "metal")
    for i in range(max(2,math.ceil(length/8))):
        x = -length/2+1+i*(length-2)/(max(2,math.ceil(length/8))-1)
        g.box("girder", (.65,1.0,6.4),(x,top-.7,0))
    for sign in (-1,1):
        x = sign*(length/2-.6)
        g.box("girder", (1.2,gh,9),(x,top-gh/2,0),"red")
        g.box("girder", (1.22,.65,9.06),(x,bottom+.4,0),"hazard")
        for dx in (-.35,.35):
            g.bar("girder",(x+dx,bottom+.1,4.6),(x+dx,top+1.1,4.6),.08)
        for i in range(math.ceil((gh+1)/.35)):
            g.bar("girder",(x-.35,bottom+.15+i*.35,4.6),(x+.35,bottom+.15+i*.35,4.6),.07)

    wheel_counts = iter(wheel_distribution(dim.wheel_count))
    for node, x, rigid in (("leg_left",-dim.span/2,True),("leg_right",dim.span/2,False)):
        g.box(node,(2.4,1.4,22),(x,2.6,0),"red")
        for side in (-1,1):
            base, crown = (x,3.3,side*8.8),(x,bottom,side*3.2)
            g.bar(node,base,crown,2.0 if rigid else 1.15,2.0 if rigid else 1.1)
            g.bar(node,base,(x,6,side*8.4),2.02 if rigid else 1.18,2.02 if rigid else 1.13,"red")
            if not rigid:
                g.cylinder(node,(x-.95,bottom-.35,side*3.2),(x+.95,bottom-.35,side*3.2),.52)
                g.box(node,(1.8,.3,1.6),(x,bottom-.1,side*3.2),"red")
            count = next(wheel_counts)
            # 每角一列车轮沿轨道排列，车轮间距由总数适配。
            spacing = 8.4/max(1,count)
            radius = min(.62,spacing*.43)
            z_center = side*6.4
            g.box(node,(2.35,.5,9.0),(x,1.8,z_center),"red")
            g.box(node,(2.38,.35,9.02),(x,1.75,z_center),"hazard")
            for i in range(count):
                z = z_center+(i-(count-1)/2)*spacing
                y = .3+radius
                g.cylinder(node,(x-.4,y,z),(x+.4,y,z),radius,"metal",24)
                for dx in (-.42,.42):
                    g.cylinder(node,(x+dx-.055,y,z),(x+dx+.055,y,z),radius+.07,"metal",24)
                g.cylinder(node,(x-.6,y,z),(x+.6,y,z),radius*.32,"red")
                g.box(node,(1.2,.85,.16),(x,y+.46,z),"metal")
            for z in (z_center-4.6,z_center+4.6):
                g.cylinder(node,(x,1.45,z-.16),(x,1.45,z+.16),.3,"rubber")
        mid = (3.3+bottom)/2
        g.box(node,(1.3 if rigid else .8,1.0,12),(x,mid,0))
        if rigid:
            for side in (-1,1):
                g.bar(node,(x,4,side*7.8),(x,mid,-side*5.7),.55)
            g.bar(node,(x,3.3,0),(x+5,bottom,0),1.4)
            ladder_x = x+1.08
            for z in (-.42,.42):
                g.bar(node,(ladder_x,3.4,z),(ladder_x,bottom,z),.075)
            for i in range(math.ceil((bottom-3.4)/.35)):
                y = 3.4+i*.35
                g.bar(node,(ladder_x,y,-.42),(ladder_x,y,.42),.065)
            for i in range(int((bottom-5)/1.8)):
                y = 5+i*1.8
                points = [(ladder_x+.65*math.sin(j*math.pi/12),y,.65*math.cos(j*math.pi/12)) for j in range(13)]
                g.tube(node,points,.045,"paint")

    # 小车最高点严格落在整机高度；留出卷扬机与电气房的可读轮廓。
    g.box("trolley",(12,.8,9),(0,top+.55,0),"red")
    for z in (-3.2,3.2):
        for x in (-4.4,4.4):
            g.cylinder("trolley",(x,top+.38,z-.23),(x,top+.38,z+.23),.36)
    for z in (-2.7,2.7):
        g.cylinder("trolley",(-3,top+2,z),(3,top+2,z),.9,"metal",40)
        for x in (-3.1,3.1):
            g.cylinder("trolley",(x-.12,top+2,z),(x+.12,top+2,z),1.08,"red",32)
        # 连续螺旋绳槽，用细钢丝管给出真实几何高光。
        groove = [(-2.85+5.7*i/720,top+2+.915*math.cos(i*math.tau/24),z+.915*math.sin(i*math.tau/24)) for i in range(721)]
        g.tube("trolley",groove,.025,"rope",6)
        g.box("trolley",(1.4,1.2,1.4),(4,top+1.8,z),"paint")
    g.box("trolley",(7,2.1,2.6),(0,top+4.45,0),"yellow")
    g.box("trolley",(7.2,.12,2.8),(0,dim.height-.06,0),"red")
    for x in (-2.2,0,2.2):
        for i in range(9):
            g.box("trolley",(1.5,.07,.09),(x,top+3.8+i*.15,1.34),"grate")
    for z in (-1.45,1.45):
        g.box("trolley",(8,.12,.4),(0,top+3.3,z),"grate")

    h = dim.hook_height
    for z in (-1.3,1.3):
        g.box("hoist_hook",(3,2.5,.3),(0,h+2.85,z),"yellow")
        g.box("hoist_hook",(3,.55,.32),(0,h+2.0,z),"hazard")
    for x in (-.95,-.32,.32,.95):
        g.cylinder("hoist_hook",(x-.19,h+2.9,0),(x+.19,h+2.9,0),.95,"metal",32)
        for z in (-.85,.85):
            g.cylinder("rope",(x,h+3.9,z),(x,top+1,z),.042,"rope",10)
    g.cylinder("hoist_hook",(0,h+1.3,0),(0,h+2,0),.3)
    g.bar("hoist_hook",(.1,h+1,0),(.6,h+.65,0),.065,material="metal")

    cab_x, cab_y = -dim.span/2+3,bottom*.7
    g.bar("cab",(cab_x,cab_y+1.5,0),(cab_x,bottom,0),.5)
    for y in (cab_y-1.4,cab_y+1.4):
        g.box("cab",(4,.2,3),(cab_x,y,0))
    g.box("cab",(4,1.0,3),(cab_x,cab_y-.8,0),"red")
    for dx in (-1.93,0,1.93):
        for z in (-1.45,1.45):
            g.bar("cab",(cab_x+dx,cab_y-.3,z),(cab_x+dx,cab_y+1.3,z),.12)
    for z in (-1.46,1.46):
        g.box("cab",(3.8,1.5,.045),(cab_x,cab_y+.5,z),"glass")
    for dx in (-1.96,1.96):
        g.box("cab",(.045,1.5,2.8),(cab_x+dx,cab_y+.5,0),"glass")
    g.box("cab",(.7,.9,.7),(cab_x,cab_y-.05,0),"rubber")
    for node,x in (("rail_left",-dim.span/2),("rail_right",dim.span/2)):
        g.box(node,(.6,.07,120),(x,.035,0),"metal")
        g.box(node,(.12,.16,120),(x,.15,0),"metal")
        g.box(node,(.3,.07,120),(x,.265,0),"rail_top")
    g.finish()
    curve_hook(parents["hoist_hook"],dim,materials["metal"])
    bpy.context.view_layer.update()
    return parents
