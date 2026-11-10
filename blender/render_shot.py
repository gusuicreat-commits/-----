"""后台渲染写实模型镜头，并导出标注锚点与屏幕外包。"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from tempfile import TemporaryDirectory
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ANCHOR_NODES, HERO_LENS_MM, HERO_SENSOR_MM, NODES, derive_dimensions, frame_times,
                    display_luminance, enclosing_corners, exposure_curve, interpolate_exposure, calibrate_sun_energy,
                    hero_azimuth, hero_fov_y, motion_state, project_point, read_facts, resolve_path, set_attr, solve_exposure, to_blender,
                    validate_safe_rect, safe_camera, graphic_camera, exploded_offsets, exploded_rope, displaced_corners, analogy_layout, analogy_camera, quality_statistics, backdrop_layout, projected_rect)


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="渲染门机写实镜头；still-at 单位为秒")
    parser.add_argument("--facts", required=True, help="核验参数文件")
    parser.add_argument("--shot-json", required=True, help="完整镜头 JSON")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--engine", choices=("eevee","cycles"), default="eevee")
    parser.add_argument("--look", choices=("afternoon", "dusk"), default="afternoon", help="晴天下午或黄昏")
    parser.add_argument("--frame-format", choices=("jpg", "png"), default="jpg")
    parser.add_argument("--skip-video", action="store_true", help="仅输出帧序列和锚点")
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration", type=float, default=6)
    stills = parser.add_mutually_exclusive_group()
    stills.add_argument("--still-at", type=float, help="单帧时刻（秒）")
    stills.add_argument("--stills", help="多个时刻，以逗号分隔（秒），例如 0.5,3,5.5")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--safe-rect", help="归一化安全框 x0,y0,x1,y1，左上原点")
    parser.add_argument("--preview", action="store_true", help="分辨率减半，实时引擎采样减半")
    args = parser.parse_args(argv)
    if min(args.samples,args.fps,args.width,args.height) <= 0:
        parser.error("采样数、帧率和分辨率必须大于零")
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error("时长必须是有限正数")
    if args.still_at is not None and (not math.isfinite(args.still_at) or not 0 <= args.still_at <= args.duration):
        parser.error("单帧时刻必须在零与镜头时长之间（单位：秒）")
    if args.stills is not None:
        try:
            args.stills = [float(value.strip()) for value in args.stills.split(',')]
        except ValueError:
            parser.error("多帧时刻必须是用逗号分隔的数字（单位：秒）")
        if any(not math.isfinite(t) or not 0 <= t <= args.duration for t in args.stills):
            parser.error("多帧时刻必须在零与镜头时长之间（单位：秒）")
        if len(set(args.stills)) != len(args.stills):
            parser.error("多帧时刻不能重复，以免覆盖图片")
    if args.safe_rect is not None:
        try:
            args.safe_rect = validate_safe_rect(tuple(float(v) for v in args.safe_rect.split(',')))
        except ValueError as exc:
            parser.error(str(exc))
    if args.preview:
        args.width, args.height = max(1,args.width//2), max(1,args.height//2)
        if args.engine == "eevee":
            args.samples = max(1,min(args.samples,24)//2)
    return args


def frame_filename(args: argparse.Namespace, index: int, time_s: float) -> str:
    if args.stills is not None:
        return f"still_{args.engine}_{str(float(time_s)).removesuffix('.0')}.png"
    return f"still_{args.engine}.png" if args.still_at is not None else f"frame_{index:05d}.{args.frame_format}"


def configure_engine(scene: Any, engine: str, samples: int) -> dict[str, Any]:
    import bpy
    result: dict[str, Any] = {"engine":engine,"samples":samples,"device":"默认图形设备","warnings":[]}
    if engine == "eevee":
        scene.render.engine = "BLENDER_EEVEE"
        eevee = getattr(scene,"eevee",None)
        set_attr(eevee, "taa_render_samples", min(samples,24))
        set_attr(eevee, "use_raytracing", False)
        set_attr(eevee, "use_fast_gi", True)
        set_attr(eevee, "fast_gi_quality", .25)
        set_attr(eevee, "fast_gi_ray_count", 2)
        set_attr(eevee, "fast_gi_step_count", 8)
        set_attr(scene.render, "use_motion_blur", False)
        result.update({"samples":min(samples,24),"raytracing":False,"fast_gi":True})
        set_attr(scene.render, "film_transparent", False)
    else:
        scene.render.engine = "CYCLES"
        set_attr(scene.cycles, "samples", samples)
        set_attr(scene.cycles, "use_denoising", True)
        set_attr(scene.cycles, "denoiser", "OPENIMAGEDENOISE")
        set_attr(scene.cycles, "use_adaptive_sampling", True)
        set_attr(scene.cycles, "max_bounces", 6)
        set_attr(scene.cycles, "transparent_max_bounces", 4)
        try:
            preferences = bpy.context.preferences.addons["cycles"].preferences
            if not set_attr(preferences, "compute_device_type", "METAL"):
                raise RuntimeError("无法启用 Metal 设备")
            preferences.refresh_devices()
            devices = [device for device in preferences.devices if device.type == "METAL"]
            if not devices:
                raise RuntimeError("没有可用的 Metal 设备")
            for device in preferences.devices:
                if not set_attr(device, "use", device.type == "METAL"):
                    raise RuntimeError("无法配置渲染设备")
            if not set_attr(scene.cycles, "device", "GPU"):
                raise RuntimeError("无法启用 GPU 渲染")
            result["device"] = "Metal GPU"
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            set_attr(scene.cycles, "device", "CPU")
            result["device"] = "CPU"
            result["warnings"].append(f"Metal 不可用，使用 CPU：{exc}")
        set_attr(scene.render, "use_persistent_data", True)
    return result


def part_objects(parent: Any) -> list[Any]:
    objects = []
    def visit(obj: Any) -> None:
        if obj != parent and obj.name in NODES:
            return
        if obj.type in ("MESH","CURVE"):
            objects.append(obj)
        for child in obj.children:
            visit(child)
    visit(parent)
    return objects


def bounds(objects: list[Any], depsgraph: Any) -> tuple[Any, Any]:
    from mathutils import Vector
    points = [evaluated.matrix_world @ Vector(corner)
              for obj in objects for evaluated in [obj.evaluated_get(depsgraph)] for corner in evaluated.bound_box]
    return (Vector(tuple(min(p[i] for p in points) for i in range(3))),
            Vector(tuple(max(p[i] for p in points) for i in range(3))))


def sunlit_ground_indices(scene: Any, sun: Any, width: int, height: int) -> list[int]:
    """按几何选出可见、未遮挡的混凝土地面，两次探针共用同一掩码。"""
    import bpy
    from mathutils import Vector
    graph = bpy.context.evaluated_depsgraph_get()
    camera = scene.camera
    corners = camera.data.view_frame(scene=scene)
    left, right = min(v.x for v in corners), max(v.x for v in corners)
    bottom, top = min(v.y for v in corners), max(v.y for v in corners)
    rotation = camera.matrix_world.to_3x3()
    origin = camera.matrix_world.translation
    light = (sun.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized()

    def cast(start: Any, direction: Any) -> tuple:
        for _ in range(32):
            hit, point, normal, face, obj, matrix = scene.ray_cast(graph, start, direction, distance=20000)
            if not hit or not obj.hide_render:
                return hit, point, normal, face, obj, matrix
            start = point + direction * .02
        raise RuntimeError("光比标定失败：射线穿过过多隐藏物体")

    indices = []
    for py in range(height):
        for px in range(width):
            direction = (rotation @ Vector((left+(right-left)*(px+.5)/width,
                bottom+(top-bottom)*(py+.5)/height, corners[0].z))).normalized()
            hit, point, normal, _, obj, _ = cast(origin, direction)
            if (not hit or obj.get('geometry_node') != 'ground' or normal.dot(light) <= .25):
                continue
            if not cast(point+normal*.025, light)[0]:
                indices.append(py*width+px)
    if len(indices) < 16:
        raise RuntimeError("光比标定失败：受光混凝土地面不足 16 个采样像素")
    return indices


def meter_sun_sky(scene: Any, target_ratio: float = 4.0) -> dict[str, Any]:
    """仅天空、仅太阳各渲染一次，在线性域校正能量，整个镜头固定主光。"""
    import bpy
    import numpy as np
    before = time.perf_counter()
    sun = next(obj for obj in scene.objects if obj.type == 'LIGHT' and obj.data.type == 'SUN')
    background = scene.world.node_tree.nodes.get('Background').inputs['Strength']
    initial_energy, initial_background = sun.data.energy, background.default_value
    saved: list[tuple[Any, str, Any]] = []

    def override(obj: Any, name: str, value: Any) -> None:
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    try:
        override(scene.render, 'resolution_x', 192)
        override(scene.render, 'resolution_y', 108)
        override(scene.render, 'resolution_percentage', 100)
        override(scene.render, 'film_transparent', False)
        # 浮点 EXR 保存场景线性值，不应用 AgX、曝光或显示编码。
        override(scene.render.image_settings, 'file_format', 'OPEN_EXR')
        override(scene.render.image_settings, 'color_mode', 'RGBA')
        override(scene.render.image_settings, 'color_depth', '32')
        if scene.render.engine == 'CYCLES':
            override(scene.cycles, 'samples', 8)
            override(scene.cycles, 'use_adaptive_sampling', False)
            override(scene.cycles, 'use_denoising', False)
        elif hasattr(scene, 'eevee'):
            override(scene.eevee, 'taa_render_samples', 8)
        bpy.context.view_layer.update()
        indices = sunlit_ground_indices(scene, sun, 192, 108)
        with TemporaryDirectory(prefix='kepu-light-') as folder:
            probe_path = Path(folder) / 'linear.exr'

            def measure(energy: float, strength: float) -> float:
                sun.data.energy, background.default_value = energy, strength
                bpy.context.view_layer.update()
                bpy.ops.render.render(write_still=False)
                result = bpy.data.images.get('Render Result')
                if result is None:
                    raise RuntimeError("光比标定失败：没有线性探针结果")
                result.save_render(str(probe_path), scene=scene)
                image = bpy.data.images.load(str(probe_path), check_existing=False)
                try:
                    if tuple(image.size) != (192, 108):
                        raise RuntimeError("光比标定失败：探针分辨率不符")
                    pixels = np.empty(192*108*4, dtype=np.float32)
                    image.pixels.foreach_get(pixels)
                    rgb = pixels.reshape(-1, 4)[indices, :3]
                    luminance = rgb @ np.array([.2126, .7152, .0722])
                    if not np.all(np.isfinite(luminance)):
                        raise RuntimeError("光比标定失败：探针包含无效亮度")
                    return float(np.median(luminance))
                finally:
                    bpy.data.images.remove(image)

            e_sky = measure(0.0, initial_background)
            e_sun = measure(initial_energy, 0.0)
        energy = calibrate_sun_energy(initial_energy, e_sun, e_sky, target_ratio)
        sun.data.energy = energy
        ratio = (e_sun * energy / initial_energy) / e_sky
        return {'sun_energy':energy, 'sun_sky_ratio':ratio,
                'target_ratio':target_ratio, 'tolerance':.5,
                'initial_sun_energy':initial_energy, 'measured_ratio_before':e_sun/e_sky,
                'e_sky':e_sky, 'e_sun_before':e_sun, 'sample_count':len(indices),
                'resolution':[192,108], 'samples':8, 'seconds':time.perf_counter()-before,
                'summary':'同机位受光地面中位线性亮度；标定后光比按能量线性换算，非第三张探针实测'}
    except Exception:
        sun.data.energy = initial_energy
        raise
    finally:
        background.default_value = initial_background
        for obj, name, value in reversed(saved):
            setattr(obj, name, value)
        bpy.context.view_layer.update()


def meter_exposure(scene: Any, subjects: list[Any], target: float = .44) -> dict[str, Any]:
    """同机位同引擎探测；缓存线性结果，只重做显示变换，不重复追光。"""
    import bpy

    before = time.perf_counter()
    saved: list[tuple[Any, str, Any]] = []
    initial_exposure = scene.view_settings.exposure

    def override(obj: Any, name: str, value: Any) -> None:
        saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    try:
        override(scene.render, "resolution_x", 192)
        override(scene.render, "resolution_y", 108)
        override(scene.render, "resolution_percentage", 100)
        override(scene.render, "film_transparent", True)
        override(scene.render.image_settings, "file_format", "PNG")
        override(scene.render.image_settings, "color_mode", "RGBA")
        override(scene.render.image_settings, "color_depth", "16")
        if scene.render.engine == "CYCLES":
            override(scene.cycles, "samples", 8)
            override(scene.cycles, "use_adaptive_sampling", False)
        elif hasattr(scene, "eevee"):
            override(scene.eevee, "taa_render_samples", 8)
        subject_ids = {obj.as_pointer() for obj in subjects}
        for obj in scene.objects:
            if obj.type not in ("LIGHT", "CAMERA", "EMPTY") and obj.as_pointer() not in subject_ids:
                override(obj, "hide_render", True)
        bpy.context.view_layer.update()
        bpy.ops.render.render(write_still=False)
        result = bpy.data.images.get("Render Result")
        if result is None:
            raise RuntimeError("测光失败：没有探测渲染结果")
        with TemporaryDirectory(prefix="kepu-meter-") as folder:
            probe_path = Path(folder) / "display.png"

            def measure(exposure: float) -> dict[str, Any]:
                scene.view_settings.exposure = exposure
                # save_render 应用场景 AgX、look 与曝光；读取时禁止再次做 sRGB 解码。
                result.save_render(str(probe_path), scene=scene)
                image = bpy.data.images.load(str(probe_path), check_existing=False)
                try:
                    image.colorspace_settings.name = "Non-Color"
                    return display_luminance(list(image.pixels[:]))
                finally:
                    bpy.data.images.remove(image)

            exposure, stats = solve_exposure(measure, initial_exposure, target)
        scene.view_settings.exposure = exposure
        return {"exposure":exposure, **stats, "resolution":[192,108], "samples":8,
                "seconds":time.perf_counter()-before,
                "summary":"仅统计门机 alpha>0.5 的 AgX 显示亮度；高光上限优先"}
    except Exception:
        scene.view_settings.exposure = initial_exposure
        raise
    finally:
        for obj, name, value in reversed(saved):
            setattr(obj, name, value)
        bpy.context.view_layer.update()


def frame_quality(scene: Any, path: Path, subjects: list[Any]) -> dict[str, Any]:
    """读取正式输出的显示像素，通过可见表面法线和太阳遮挡射线分组。"""
    import bpy
    import numpy as np
    from mathutils import Vector
    before = time.perf_counter()
    image = bpy.data.images.load(str(path),check_existing=False)
    try:
        image.colorspace_settings.name = "Non-Color"
        width,height = image.size
        pixels = np.empty(width*height*4,dtype=np.float32)
        image.pixels.foreach_get(pixels)
        pixels = pixels.reshape(height,width,4)
        graph = bpy.context.evaluated_depsgraph_get()
        subject_ids = {obj.as_pointer() for obj in subjects}
        sun = next(obj for obj in scene.objects if obj.type == 'LIGHT' and obj.data.type == 'SUN')
        light = (sun.matrix_world.to_3x3() @ Vector((0,0,1))).normalized()
        camera = scene.camera
        corners = camera.data.view_frame(scene=scene)
        left,right = min(v.x for v in corners),max(v.x for v in corners)
        bottom,top = min(v.y for v in corners),max(v.y for v in corners)
        rotation = camera.matrix_world.to_3x3()
        origin = camera.matrix_world.translation
        groups: dict[str,list[tuple[float,float,float]]] = {key:[] for key in (
            'crane','sunlit_paint','shaded_paint','ground','crane_shadow','sunlit_ground','sky')}

        def cast(start: Any, direction: Any) -> tuple:
            for _ in range(32):
                hit,point,normal,face,obj,matrix = scene.ray_cast(graph,start,direction,distance=20000)
                if not hit or not obj.hide_render:
                    return hit,point,normal,face,obj,matrix
                start = point+direction*.02
            return False,None,None,None,None,None

        for row in range(54):
            py = min(height-1,int((row+.5)*height/54))
            for column in range(96):
                px = min(width-1,int((column+.5)*width/96))
                direction = (rotation @ Vector((left+(right-left)*(px+.5)/width,
                    bottom+(top-bottom)*(py+.5)/height,corners[0].z))).normalized()
                hit,point,normal,face,obj,_ = cast(origin,direction)
                rgb = tuple(float(v) for v in pixels[py,px,:3])
                if not hit:
                    groups['sky'].append(rgb)
                    continue
                source = getattr(obj,'original',obj)
                is_crane = source.as_pointer() in subject_ids
                is_ground = obj.get('geometry_node') == 'ground'
                if is_crane:
                    groups['crane'].append(rgb)
                if not is_ground and not (is_crane and obj.get('geometry_material') in {'paint','red'}):
                    continue
                blocked,_,_,_,blocker,_ = cast(point+normal*.025,light)
                if is_ground:
                    groups['ground'].append(rgb)
                    if not blocked:
                        groups['sunlit_ground'].append(rgb)
                    elif getattr(blocker,'original',blocker).as_pointer() in subject_ids:
                        groups['crane_shadow'].append(rgb)
                elif normal.dot(light) > .25 and not blocked:
                    groups['sunlit_paint'].append(rgb)
                elif normal.dot(light) < -.15 or blocked:
                    groups['shaded_paint'].append(rgb)
        result = quality_statistics(groups)
        result.update({"sampling_grid":[96,54],"seconds":time.perf_counter()-before,
                       "source":path.name,
                       "summary":"正式帧显示色均匀采样；色相和饱和度验收仅受光涂装，明暗比仅同涂装；阴影由太阳射线命中门机确认；地面不含接缝油渍"})
        return result
    finally:
        bpy.data.images.remove(image)


def merge_distant(objects: list[Any]) -> dict[str, int]:
    """隐藏集合确定后，把 300 m 外静态布景烘焙为一个多材质网格。"""
    import bpy
    from mathutils import Vector
    distant = []
    for obj in objects:
        if obj.hide_render or obj.type != 'MESH' or not obj.get('geometry_node','').startswith(
                ('decor_','industrial_skyline','distant_crane')):
            continue
        center = obj.matrix_world @ (sum((Vector(p) for p in obj.bound_box),Vector())/8)
        if math.hypot(center.x,center.y) > 300:
            distant.append(obj)
    if not distant:
        return {"source_objects":0,"merged_objects":0}
    vertices,faces,indices,shading,materials = [],[],[],[],[]
    for obj in distant:
        offset = len(vertices)
        vertices.extend(tuple(obj.matrix_world @ v.co) for v in obj.data.vertices)
        for polygon in obj.data.polygons:
            mat = obj.data.materials[polygon.material_index]
            if mat not in materials:
                materials.append(mat)
            faces.append(tuple(offset+i for i in polygon.vertices))
            indices.append(materials.index(mat)); shading.append(polygon.use_smooth)
    mesh = bpy.data.meshes.new('远景合并网格')
    mesh.from_pydata(vertices,[],faces); mesh.update()
    for mat in materials:
        mesh.materials.append(mat)
    for polygon,index,smooth in zip(mesh.polygons,indices,shading):
        polygon.material_index = index; polygon.use_smooth = smooth
    obj = bpy.data.objects.new('远景厂区',mesh)
    bpy.context.collection.objects.link(obj)
    for source in distant:
        bpy.data.objects.remove(source,do_unlink=True)
    return {"source_objects":len(distant),"merged_objects":1}


def surface_pin(scene: Any, graph: Any, objects: list[Any]) -> Any:
    """从相机沿主体中心视线取可见表面；跳过附属件和其他节点。"""
    bodies = [obj for obj in objects if obj.type == "MESH" and obj.get("anchor_body")]
    if not bodies:
        low, high = bounds(objects, graph)
        return (low+high)/2
    # 双主梁、双腿柱分别取近侧实体，避免中心落在两实体之间的空洞。
    groups: dict[str, list[Any]] = {}
    for obj in bodies:
        groups.setdefault(obj["anchor_body"], []).append(obj)
    centers = []
    for group in groups.values():
        low, high = bounds(group, graph)
        centers.append(((low+high)/2, group))
    camera = scene.camera.matrix_world.translation
    center, group = min(centers, key=lambda item: (camera-item[0]).length)
    direction = (center-camera).normalized()
    origin = camera.copy()
    remaining = (center-camera).length
    targets = {obj.as_pointer() for obj in group}
    # 首个主体命中即为朝向相机的表面，未命中则保留主体中心。
    for _ in range(128):
        hit, location, _, _, obj, _ = scene.ray_cast(graph, origin, direction, distance=remaining)
        if not hit:
            break
        if getattr(obj, "original", obj).as_pointer() in targets:
            return location
        step = (location-origin).length + .0001
        remaining -= step
        if remaining <= 0:
            break
        origin = location + direction*.0001
    return center


def anchors(scene: Any, parents: dict[str, Any]) -> dict[str, Any]:
    """保留整部件外包，另导出主体表面 pin；visible 仍只表示中心在画幅内。"""
    import bpy
    from bpy_extras.object_utils import world_to_camera_view
    from mathutils import Vector

    graph = bpy.context.evaluated_depsgraph_get()
    result = {}
    width = scene.render.resolution_x * scene.render.resolution_percentage / 100
    height = scene.render.resolution_y * scene.render.resolution_percentage / 100
    for name in ANCHOR_NODES:
        objects = part_objects(parents[name])
        low, high = bounds(objects, graph)
        center = (low+high)/2
        pin = world_to_camera_view(scene, scene.camera, surface_pin(scene, graph, objects))
        projected = world_to_camera_view(scene, scene.camera, center)
        valid = abs(projected.z) > 1e-9
        visible = bool(valid and projected.z > 0 and 0 <= projected.x <= 1 and 0 <= projected.y <= 1)
        corners = [world_to_camera_view(scene, scene.camera, Vector(p))
                   for p in enclosing_corners([tuple(low), tuple(high)])]
        screen_box = ([min(p.x for p in corners)*width, (1-max(p.y for p in corners))*height,
                       max(p.x for p in corners)*width, (1-min(p.y for p in corners))*height]
                      if all(p.z > 1e-9 for p in corners) else None)
        result[name] = {"bbox":screen_box, "pin":{"x":pin.x*width, "y":(1-pin.y)*height},
                        "x":projected.x*width if valid else None,
                        "y":(1-projected.y)*height if valid else None,
                        "visible":visible, "in_frame":visible,
                        "center_m":(center.x,center.z,-center.y)}
    return result


def compose_video(out: Path, fps: int, count: int, frame_format: str = "png") -> dict[str, Any]:
    """仅编码本次帧数，旧目录里多余的帧不会进入成片。"""
    executable = shutil.which(os.environ.get("KEPU_FFMPEG", "ffmpeg"))
    if executable is None:
        summary = "未找到视频编码工具，已保留序列帧和锚点，可稍后合成"
        print(f"提示：{summary}", flush=True)
        return {"status":"skipped", "summary":summary}
    destination = out / "orbit.mp4"
    command = [executable, "-y", "-hide_banner", "-loglevel", "error",
               "-framerate", str(fps), "-start_number", "1", "-i", str(out/f"frame_%05d.{frame_format}"),
               "-frames:v", str(count), "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-crf", "18", "-movflags", "+faststart", str(destination)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise RuntimeError(f"无法启动视频编码工具，序列帧和锚点已保留：{exc}") from exc
    if completed.returncode != 0 or not destination.is_file():
        raise RuntimeError(f"视频合成失败，序列帧和锚点已保留：{completed.stderr.strip()}")
    return {"status":"ok", "file":destination.name, "frames":count,
            "summary":"环绕动画合成完成"}


def main(argv: list[str]) -> None:
    started = time.perf_counter()
    args = arguments(argv)
    dim = derive_dimensions(read_facts(args.facts))
    shot = json.loads(args.shot_json)
    if not isinstance(shot,dict) or shot.get("kind","model_orbit") not in ("model_orbit", "title", "motion", "exploded", "data_card", "outro", "analogy") or not isinstance(shot.get("params",{}),dict):
        raise ValueError("渲染入口只接受 model_orbit、title、motion、exploded、data_card、outro 或支持的 analogy 镜头对象")
    params = shot.get("params",{})
    kind = shot.get("kind", "model_orbit")
    comparison = analogy_layout(dim, shot.get("analogy_data", {})) if kind == "analogy" else None
    if args.safe_rect is None:
        # 与后端默认 HUD 安全框一致；直接调用脚本时也保护标题和字幕。
        args.safe_rect = (.45 if kind == "title" else .05,
                          .05 if kind == "title" else .20,
                          .74 if shot.get("text_overlays") or kind == "motion" else .95, .86)
        if kind == "analogy":
            args.safe_rect = (.08,.23,.92,.80)
        if kind in {"data_card", "outro"}:
            args.safe_rect = (.46,.05,.95,.86) if kind == "data_card" else (.40,.30,.95,.80)
    hero_azimuth(params,0,args.duration)  # 建模前校验。
    if kind == "motion":
        motion_state(dim,params,0,args.duration)
    out = resolve_path(args.out)
    out.mkdir(parents=True,exist_ok=True)
    import bpy
    from mathutils import Vector
    from crane import build_crane
    from scene import environment, materials
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.resolution_x,scene.render.resolution_y = args.width,args.height
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
    scene.render.fps = args.fps
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    info = configure_engine(scene,args.engine,args.samples)
    mats = materials()
    parents = build_crane(dim,mats)
    graph = bpy.context.evaluated_depsgraph_get()
    meshes = [obj for name in NODES for obj in part_objects(parents[name])]
    lo,hi = bounds(meshes,graph)
    actual_bbox = (hi.x-lo.x,hi.z-lo.z,hi.y-lo.y)
    if any(abs(a-b) > .02 for a,b in zip(actual_bbox,dim.bbox)):
        raise ValueError(f"门机外包尺寸与参数化模型不一致：{actual_bbox}，预期 {dim.bbox}")
    # 整机外包八角点取景，排除轨道；保留实际倒角后的外轮廓余量。
    silhouette = []
    part_boxes = {}
    subjects = []
    for name in NODES:
        if name in ("rail_left", "rail_right"):
            continue
        objects = part_objects(parents[name])
        if objects:
            part_low, part_high = bounds(objects, graph)
            part_boxes[name] = ((part_low.x, part_low.z, -part_high.y),
                                (part_high.x, part_high.z, -part_low.y))
        for obj in objects:
            subjects.append(obj)
            evaluated = obj.evaluated_get(graph)
            for corner in evaluated.bound_box:
                p = evaluated.matrix_world @ Vector(corner)
                silhouette.append((p.x,p.z,-p.y))
    silhouette = enclosing_corners(silhouette)
    # 最大分离外包也包含装配端点；所有位移在同一进度上单调变化。
    if kind == "exploded":
        peak = exploded_offsets(params.get("parts", []), float(params.get("spread_m", 12)),
                                args.duration/2, args.duration, part_boxes)
        silhouette = enclosing_corners(displaced_corners(part_boxes, peak) + displaced_corners(part_boxes, {}))
    elif kind == "motion" and params.get("axis") != "gantry":
        sweep = []
        for time_s in (0.0, args.duration):
            state = motion_state(dim, params, time_s, args.duration)
            offsets = {"trolley": (state["trolley_x"], 0, 0),
                       "hoist_hook": (state["trolley_x"], state["hook_height"]-dim.hook_height, 0)}
            sweep.extend(displaced_corners(part_boxes, offsets))
        silhouette = enclosing_corners(sweep)
    environment_azimuth = (6 if kind == "analogy" else 50 if kind == "outro" else
                           23 if kind in {"title","data_card"} else 24 if kind == "motion" else
                           13 if kind == "exploded" else hero_azimuth(params,args.duration/2,args.duration))
    decor = environment(dim,mats,environment_azimuth,args.look)
    if comparison:
        from scene import analogy_reference
        from crane import Geometry
        geometry = Geometry(mats,{})
        analogy_reference(geometry,comparison)
        geometry.finish()
        # 参照场地不与原有板垛、运输车重叠。
        for obj in decor:
            if obj.name.startswith(("steel_plates","plate_rust","transport_","parking_line","rail_extension","safety_lines")):
                obj.hide_render = True
    decor_groups: dict[str,list[Any]] = {}
    for obj in decor:
        if obj.name.startswith("decor_"):
            # 同一附属物的所有材质批次作为整体进行投影避让。
            key = obj.name.rsplit("_",1)[0]
            # 材质名可能含下划线，采用建模时保存的节点名。
            key = obj.get("geometry_node",key)
            decor_groups.setdefault(key,[]).append(obj)
    bpy.context.view_layer.update()
    decor_boxes = {key: bounds(objects,bpy.context.evaluated_depsgraph_get()) for key,objects in decor_groups.items()}

    # 轨道属于环境，大车移动时保持世界坐标不变。
    for name in ("rail_left", "rail_right"):
        matrix = parents[name].matrix_world.copy()
        parents[name].parent = None
        parents[name].matrix_world = matrix
    camera_data = bpy.data.cameras.new("camera")
    camera_data.sensor_fit = "AUTO"
    camera_data.sensor_width = HERO_SENSOR_MM
    camera_data.lens = HERO_LENS_MM
    camera_data.clip_start,camera_data.clip_end = .01,20000
    camera = bpy.data.objects.new("camera",camera_data)
    bpy.context.collection.objects.link(camera)
    scene.camera = camera
    scene.render.use_file_extension = True
    times = args.stills if args.stills is not None else (
        [args.still_at] if args.still_at is not None else frame_times(args.duration,args.fps))
    payload: dict[str, Any] = {"version":1,"width":args.width,"height":args.height,"fps":args.fps,
        "duration_s":args.duration,"coordinate_system":"像素坐标，左上为原点",
        "visibility":"部件包围盒中心投影；visible/in_frame 表示中心在画幅内且位于相机正面，不判断遮挡",
        "pin_definition":"主体网格朝向相机的表面投影；未命中时用主体中心，不含梯子、扶手与悬挂杆",
        "frames":[]}
    info.update({"bbox_m":dict(zip("xyz",actual_bbox)),"assumed":dim.assumed,
                 "wheel_count":dim.wheel_count,"hoist_range_m":dim.hoist_range,
                 "summary":"参数化结构示意样片；附属结构与场景不作为设备技术事实",
                 "resolution":[args.width,args.height],"fov_y_deg":hero_fov_y(args.width,args.height),
                 "lens_mm":HERO_LENS_MM,"sensor_width_mm":HERO_SENSOR_MM,
                 "shot_kind":kind,"look":args.look,"camera_height_m":(20 if comparison["ref"] == "building_floor" else 120) if comparison else 8 if kind != "title" else None,
                 "safe_rect":args.safe_rect,
                 "max_width_ratio":args.safe_rect[2]-args.safe_rect[0],
                 "max_height_ratio":args.safe_rect[3]-args.safe_rect[1],
                 "bottom_ratio":args.safe_rect[3],"preview":args.preview,"sensor_fit":"AUTO",
                 "min_margin_ratio":min(args.safe_rect[0],args.safe_rect[1],1-args.safe_rect[2],1-args.safe_rect[3]),"frame_seconds":[],"camera_frames":[],"metering_frames":[],"quality_frames":[],"render_seconds":[]})
    for warning in info["warnings"]:
        print(f"提示：{warning}",flush=True)
    fixed_pose = (safe_camera(silhouette, 13, args.safe_rect, args.width, args.height)
                  if kind == "exploded" else None)
    hidden_decor: set[str] = set()
    decor_finalized = False
    base_locations = {name: tuple(parents[name].location) for name in ANCHOR_NODES}

    def set_camera(time_s: float) -> tuple[tuple, tuple]:
        if comparison:
            position,target,shift,fov = analogy_camera(dim,comparison,time_s,args.width,args.height,args.safe_rect)
            camera_data.lens = HERO_SENSOR_MM*args.height/max(args.width,args.height)/(2*math.tan(math.radians(fov)/2))
            info["fov_y_deg"],info["lens_mm"] = fov,camera_data.lens
        elif kind == "title":
            position,target,shift = safe_camera(silhouette, 23, args.safe_rect, args.width, args.height,
                                                center=(.70,.56), elevation_deg=12)
            # 最近距离留给推进末端，整个六秒推进都不越过左侧文字边界。
            factor = (1-.06*max(0.0,min(1.0,time_s/6)))/.94
            position = tuple(b+(a-b)*factor for a,b in zip(position,target))
            pts = [project_point(p,position,target,args.width,args.height,hero_fov_y(args.width,args.height)) for p in silhouette]
            shift = (.70-(min(p["x"] for p in pts)+max(p["x"] for p in pts))/2/args.width,
                     .56-(min(p["y"] for p in pts)+max(p["y"] for p in pts))/2/args.height)
        elif kind in {"data_card", "outro"}:
            position,target,shift = graphic_camera(silhouette,kind,time_s,args.duration,args.safe_rect,args.width,args.height)
        elif kind == "motion":
            state = motion_state(dim,params,time_s,args.duration)
            parents["crane"].location = to_blender(state["crane"])
            parents["trolley"].location = to_blender((state["trolley_x"],dim.girder_top,0))
            parents["hoist_hook"].location = to_blender((0,state["hook_height"]-dim.girder_top,0))
            parents["rope"].scale.z = state["rope_scale"]
            parents["rope"].location.z = state["rope_offset"]
            position,target,shift = safe_camera(silhouette,24,args.safe_rect,args.width,args.height,target_x=10)
            position = tuple(p+d for p,d in zip(position,state["crane"]))
            target = tuple(p+d for p,d in zip(target,state["crane"]))
        elif kind == "exploded":
            offsets = exploded_offsets(params.get("parts", []), float(params.get("spread_m",12)),
                                       time_s,args.duration,part_boxes)
            for name in ANCHOR_NODES:
                delta = offsets.get(name, (0,0,0))
                if name == "hoist_hook":
                    delta = tuple(a-b for a,b in zip(delta,offsets.get("trolley",(0,0,0))))
                parents[name].location = tuple(a+b for a,b in zip(base_locations[name],to_blender(delta)))
            parents["rope"].scale.z, parents["rope"].location.z = exploded_rope(dim, offsets)
            position,target,shift = fixed_pose
        else:
            position,target,shift = safe_camera(silhouette,hero_azimuth(params,time_s,args.duration),
                                                args.safe_rect,args.width,args.height)
        camera_data.shift_x = -shift[0]*args.width/max(args.width,args.height)
        camera_data.shift_y = shift[1]*args.height/max(args.width,args.height)
        camera.location = to_blender(position)
        camera.rotation_euler = (Vector(to_blender(target))-camera.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.view_layer.update()
        if getattr(scene,"world",None):
            band = scene.world.node_tree.nodes.get('cloud_band')
            if band is not None:
                view = camera.data.view_frame(scene=scene)
                low,high = min(p.y/-p.z for p in view),max(p.y/-p.z for p in view)
                band.inputs['From Min'].default_value = low+(high-low)*.65
                band.inputs['From Max'].default_value = low+(high-low)*.72
        # 全镜头预扫后固定可见集合，防止移动相机时附属物跳显。
        if decor_groups and not decor_finalized:
            def rect(points: list[tuple]) -> tuple[float,float,float,float]:
                pts = [project_point(p,position,target,args.width,args.height,info["fov_y_deg"]) for p in points]
                return (min(p["x"] for p in pts),min(p["y"] for p in pts),
                        max(p["x"] for p in pts),max(p["y"] for p in pts))
            delta = motion_state(dim,params,time_s,args.duration)["crane"] if kind == "motion" and params["axis"] == "gantry" else (0,0,0)
            protected = [rect([tuple(a+b for a,b in zip(p,delta)) for p in silhouette])]
            if comparison:
                protected.append(rect(enclosing_corners(comparison["bounds"])))
            for key,box in decor_boxes.items():
                if key.startswith(("decor_factory_","decor_chimney_","decor_worker_")):
                    continue
                candidate = rect([(p[0],p[2],-p[1]) for p in enclosing_corners([tuple(v) for v in box])])
                if any(candidate[0] < r[2]+10 and candidate[2] > r[0]-10 and
                       candidate[1] < r[3]+10 and candidate[3] > r[1]-10 for r in protected):
                    hidden_decor.add(key)
        return position,target

    if decor_groups:
        from mathutils import Matrix
        scan_times = sorted(set([args.duration*i/8 for i in range(9)]+(times if len(times) < 10 else [])))
        poses = []
        for time_s in scan_times:
            position,target = set_camera(time_s)
            poses.append({"position":position,"target":target,"fov":info["fov_y_deg"],
                          "shift":(-camera_data.shift_x*max(args.width,args.height)/args.width,
                                   camera_data.shift_y*max(args.width,args.height)/args.height)})
        protected = [enclosing_corners(box) for box in part_boxes.values()]
        if comparison:
            protected.append(enclosing_corners(comparison['bounds']))
        hull_objects = [obj for obj in decor if obj.get('geometry_node') == 'hull']
        if hull_objects:
            low,high = bounds(hull_objects,bpy.context.evaluated_depsgraph_get())
            protected.append([(p[0],p[2],-p[1]) for p in enclosing_corners([tuple(low),tuple(high)])])
        factory_layout = backdrop_layout(poses,protected,args.width,args.height)
        info['factory_layout'] = [{k:v for k,v in item.items() if k != 'points'} for item in factory_layout]
        for i,layout in enumerate(factory_layout):
            key = f'decor_factory_{i}'
            objects = decor_groups[key]
            low,high = bounds(objects,bpy.context.evaluated_depsgraph_get())
            center = Vector(((low.x+high.x)/2,(low.y+high.y)/2,0))
            destination = Vector(to_blender(layout['center']))
            initial_yaw = math.radians(environment_azimuth)
            delta = (Matrix.Translation(destination) @ Matrix.Rotation(layout['yaw']-initial_yaw,4,'Z')
                     @ Matrix.Translation(-center))
            for obj in objects:
                obj.matrix_world = delta @ obj.matrix_world
            if i < 2:
                chimney = decor_groups[f'decor_chimney_{i}']
                low,high = bounds(chimney,bpy.context.evaluated_depsgraph_get())
                old = Vector(((low.x+high.x)/2,(low.y+high.y)/2,0))
                # 厂房侧后方的烟囱与厂房形成连续轮廓。
                location = destination+Vector((math.cos(layout['yaw'])*48,math.sin(layout['yaw'])*48+18,0))
                for obj in chimney:
                    obj.matrix_world = Matrix.Translation(location-old) @ obj.matrix_world
        if not all(any(item['visible'][i] for item in factory_layout) for i in range(len(poses))):
            info['warnings'].append('部分机位没有满足完整轮廓与主体避让的厂房位置，请复看背景构图')
        bpy.context.view_layer.update()
    if decor_groups:
        for time_s in sorted(set(times+[args.duration*i/4 for i in range(5)])):
            set_camera(time_s)
        for key,objects in decor_groups.items():
            for obj in objects:
                obj.hide_render = key in hidden_decor
        decor_finalized = True
    info["hidden_decor"] = sorted(hidden_decor)
    info["distant_merge"] = merge_distant(decor) if decor else {"source_objects":0,"merged_objects":0}
    if decor:
        info["mesh_instances"] = sum(max(0,mesh.users-1) for mesh in bpy.data.meshes)
        bpy.context.view_layer.update()
    info["setup_seconds"] = time.perf_counter()-started
    set_camera(args.duration/2)
    lighting = meter_sun_sky(scene, 2.5 if args.look == 'dusk' else 4.0)
    info['light_calibration'] = {'time_s':args.duration/2, **lighting}
    info['sun_sky_ratio'], info['sun_energy'] = lighting['sun_sky_ratio'], lighting['sun_energy']
    print(f"光比标定：太阳/天空 {lighting['sun_sky_ratio']:.3f}，"
          f"太阳能量 {lighting['sun_energy']:.3f}", flush=True)
    for time_s in (args.duration*i/4 for i in range(5)):
        set_camera(time_s)
        metering = meter_exposure(scene,subjects,.42 if args.look == "dusk" else .44)
        info["metering_frames"].append({"time_s":time_s, **metering})
        print(f"自动测光：时刻 {time_s:.3f} 秒，曝光 {metering['exposure']:.3f} EV，"
              f"门机中位亮度 {metering['median']:.3f}，98 分位 {metering['p98']:.3f}",flush=True)
    curve = exposure_curve([(m["time_s"],m["exposure"]) for m in info["metering_frames"]],args.fps)
    for metering, (_,exposure) in zip(info["metering_frames"],curve):
        metering["smoothed_exposure"] = exposure
    info["exposure_interpolation"] = "五点分段线性插值；只降低过亮点以限制相邻帧变化不超过 0.02 EV"
    for index,time_s in enumerate(times,1):
        scene.frame_set(index)
        position,target = set_camera(time_s)
        scene.view_settings.exposure = interpolate_exposure(curve,time_s)
        info["exposure"] = scene.view_settings.exposure
        filename = frame_filename(args,index,time_s)
        scene.render.filepath = str(out/filename)
        frame_anchors = anchors(scene,parents)
        before = time.perf_counter()
        scene.render.image_settings.file_format = "JPEG" if filename.endswith(".jpg") else "PNG"
        scene.render.image_settings.quality = 92
        bpy.ops.render.render(write_still=True)
        elapsed = time.perf_counter()-before
        if not (out/filename).is_file():
            raise RuntimeError("渲染结束但没有生成背景帧")
        info["render_seconds"].append(elapsed)
        quality = frame_quality(scene,out/filename,subjects)
        quality['time_s'] = time_s
        info['quality_frames'].append(quality)
        info['frame_seconds'].append(time.perf_counter()-before)
        for warning in quality['warnings']:
            print(f"画面验收警告：{time_s:.3f} 秒，{warning}",flush=True)
        if info['frame_seconds'][-1] > 5 and args.engine == 'eevee':
            warning = f"{time_s:.3f} 秒单帧耗时 {info['frame_seconds'][-1]:.2f} 秒，超过 5 秒目标"
            info['warnings'].append(warning)
            print(f"性能警告：{warning}",flush=True)
        offset = (motion_state(dim,params,time_s,args.duration)["crane"]
                  if kind == "motion" and params["axis"] == "gantry" else (0,0,0))
        projected = [project_point(tuple(v+d for v,d in zip(p,offset)),position,target,
                                   args.width,args.height,info["fov_y_deg"]) for p in silhouette]
        for point in projected:
            point["x"] -= camera_data.shift_x*max(args.width,args.height)
            point["y"] += camera_data.shift_y*max(args.width,args.height)
        edges = {"left":min(p["x"] for p in projected),"right":max(p["x"] for p in projected),
                 "top":min(p["y"] for p in projected),"bottom":max(p["y"] for p in projected)}
        x0,y0,x1,y1 = args.safe_rect
        cropped = (edges["left"] < x0*args.width-1e-5 or edges["right"] > x1*args.width+1e-5
                   or edges["top"] < y0*args.height-1e-5 or edges["bottom"] > y1*args.height+1e-5)
        info["camera_frames"].append({"time_s":time_s,"position_m":position,"target_m":target,
            "exposure":scene.view_settings.exposure,"azimuth_deg":6 if comparison else 50 if kind == "outro" else 23 if kind in {"title", "data_card"} else 24 if kind == "motion" else 13 if kind == "exploded" else hero_azimuth(params,time_s,args.duration),
            "projected_width_ratio":(edges["right"]-edges["left"])/args.width,
            "width_below_preferred":(edges["right"]-edges["left"])/args.width < .7,
            "projected_height_ratio":(edges["bottom"]-edges["top"])/args.height,
            "projected_bounds_px":edges,"cropped":cropped})
        if cropped:
            raise RuntimeError(f"构图失败：{time_s:g} 秒门机外包角点超出安全画幅")
        dimension_anchors = {}
        if comparison:
            from bpy_extras.object_utils import world_to_camera_view
            for name,point in comparison["dims"].items():
                projected_point = world_to_camera_view(scene,camera,Vector(to_blender(point)))
                dimension_anchors[name] = {"x":projected_point.x*args.width,"y":(1-projected_point.y)*args.height}
        payload["frames"].append({"frame":index,"time_s":time_s,"file":filename,
                                  "exposure":scene.view_settings.exposure,"nodes":frame_anchors,"dims":dimension_anchors})
        if index % 10 == 0 or index == len(times):
            remaining = sum(info["frame_seconds"])/index*(len(times)-index)
            print(f"已完成第 {index}/{len(times)} 帧，单帧耗时 {info['frame_seconds'][-1]:.2f} 秒，"
                  f"预计剩余 {remaining:.1f} 秒",flush=True)
    if kind == "model_orbit" and any(frame["width_below_preferred"] for frame in info["camera_frames"]):
        warning = "部分时刻画宽低于 70%；固定机位高度、焦距和环绕方位下，优先保证 HUD 安全框内完整呈现"
        info["warnings"].append(warning)
        print(f"提示：{warning}",flush=True)
    (out/"anchors.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    try:
        if args.still_at is None and args.stills is None and not args.skip_video:
            info["video"] = compose_video(out,args.fps,len(times),args.frame_format)
    except RuntimeError as exc:
        info["video"] = {"status":"error", "summary":str(exc)}
        raise
    finally:
        info["total_seconds"] = time.perf_counter()-started
        (out/f"render_{args.engine}.json").write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"样片渲染完成，输出目录：{out}",flush=True)


if __name__ == "__main__":
    try:
        main(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else sys.argv[1:])
    except Exception as exc:
        print(f"渲染失败：{exc}",file=sys.stderr,flush=True)
        raise SystemExit(1) from exc
