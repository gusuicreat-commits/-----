"""后台渲染开场环绕镜头，并导出可供叠加标注使用的锚点。"""
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
                    display_luminance, enclosing_corners, exposure_curve, interpolate_exposure,
                    hero_azimuth, hero_camera, hero_fov_y, title_camera, motion_camera, motion_state, project_point, read_facts, resolve_path, set_attr, solve_exposure, to_blender)


def arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="渲染门机环绕镜头；still-at 单位为秒")
    parser.add_argument("--facts", required=True, help="核验参数文件")
    parser.add_argument("--shot-json", required=True, help="完整镜头 JSON")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--engine", choices=("eevee","cycles"), default="eevee")
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
    if args.preview:
        args.width, args.height = max(1,args.width//2), max(1,args.height//2)
        if args.engine == "eevee":
            args.samples = max(1,args.samples//2)
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
        set_attr(eevee, "taa_render_samples", samples)
        set_attr(eevee, "use_raytracing", True)
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


def meter_exposure(scene: Any, subjects: list[Any]) -> dict[str, Any]:
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

            exposure, stats = solve_exposure(measure, initial_exposure)
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


def anchors(scene: Any, parents: dict[str, Any]) -> dict[str, Any]:
    """求部件外包中心；可见仅表示在画幅内且位于相机正面，不判断遮挡。"""
    import bpy
    from bpy_extras.object_utils import world_to_camera_view

    graph = bpy.context.evaluated_depsgraph_get()
    result = {}
    width = scene.render.resolution_x * scene.render.resolution_percentage / 100
    height = scene.render.resolution_y * scene.render.resolution_percentage / 100
    for name in ANCHOR_NODES:
        low, high = bounds(part_objects(parents[name]), graph)
        center = (low+high)/2
        projected = world_to_camera_view(scene, scene.camera, center)
        valid = abs(projected.z) > 1e-9
        visible = bool(valid and projected.z > 0 and 0 <= projected.x <= 1 and 0 <= projected.y <= 1)
        result[name] = {"x":projected.x*width if valid else None,
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
    if not isinstance(shot,dict) or shot.get("kind","model_orbit") not in ("model_orbit", "title", "motion") or not isinstance(shot.get("params",{}),dict):
        raise ValueError("渲染入口只接受 model_orbit、title 或 motion 镜头对象")
    params = shot.get("params",{})
    kind = shot.get("kind", "model_orbit")
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
    subjects = []
    for name in NODES:
        if name in ("rail_left", "rail_right"):
            continue
        for obj in part_objects(parents[name]):
            subjects.append(obj)
            evaluated = obj.evaluated_get(graph)
            for corner in evaluated.bound_box:
                p = evaluated.matrix_world @ Vector(corner)
                silhouette.append((p.x,p.z,-p.y))
    silhouette = enclosing_corners(silhouette)
    environment(dim,mats,23 if kind == "title" else 24 if kind == "motion" else hero_azimuth(params,args.duration/2,args.duration))
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
        "frames":[]}
    info.update({"bbox_m":dict(zip("xyz",actual_bbox)),"assumed":dim.assumed,
                 "wheel_count":dim.wheel_count,"hoist_range_m":dim.hoist_range,
                 "summary":"参数化结构示意样片；附属结构与场景不作为设备技术事实",
                 "resolution":[args.width,args.height],"fov_y_deg":hero_fov_y(args.width,args.height),
                 "lens_mm":HERO_LENS_MM,"sensor_width_mm":HERO_SENSOR_MM,
                 "shot_kind":kind,"camera_height_m":8 if kind != "title" else None,
                 "max_width_ratio":.82 if kind == "model_orbit" else None,
                 "max_height_ratio":.78 if kind == "model_orbit" else None,
                 "bottom_ratio":.84 if kind == "model_orbit" else None,"preview":args.preview,"sensor_fit":"AUTO",
                 "min_margin_ratio":.06,"frame_seconds":[],"camera_frames":[],"metering_frames":[]})
    for warning in info["warnings"]:
        print(f"提示：{warning}",flush=True)
    def set_camera(time_s: float) -> tuple[tuple, tuple]:
        camera_data.shift_x = camera_data.shift_y = 0
        if kind == "title":
            position,target,shift = title_camera(dim,time_s,args.width,args.height,silhouette)
            camera_data.shift_x = -shift[0]
            camera_data.shift_y = shift[1]*args.height/max(args.width,args.height)
        elif kind == "motion":
            state = motion_state(dim,params,time_s,args.duration)
            parents["crane"].location = to_blender(state["crane"])
            parents["trolley"].location = to_blender((state["trolley_x"],dim.girder_top,0))
            parents["hoist_hook"].location = to_blender((0,state["hook_height"]-dim.girder_top,0))
            parents["rope"].scale.z = state["rope_scale"]
            parents["rope"].location.z = state["rope_offset"]
            position,target = motion_camera(dim,state["crane"],args.width,args.height,silhouette)
        else:
            position,target = hero_camera(dim,params,time_s,args.duration,args.width,args.height,silhouette)
        camera.location = to_blender(position)
        camera.rotation_euler = (Vector(to_blender(target))-camera.location).to_track_quat('-Z','Y').to_euler()
        bpy.context.view_layer.update()
        return position,target

    info["setup_seconds"] = time.perf_counter()-started
    for time_s in (args.duration*i/4 for i in range(5)):
        set_camera(time_s)
        metering = meter_exposure(scene,subjects)
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
        info["frame_seconds"].append(elapsed)
        projected = [project_point(p,position,target,args.width,args.height,info["fov_y_deg"]) for p in silhouette]
        if kind == "title":
            for point in projected:
                point["x"] -= camera_data.shift_x*args.width
                point["y"] += camera_data.shift_y*max(args.width,args.height)
        elif kind == "motion" and params["axis"] == "gantry":
            offset = motion_state(dim,params,time_s,args.duration)["crane"]
            projected = [project_point(tuple(v+d for v,d in zip(p,offset)),position,target,
                                       args.width,args.height,info["fov_y_deg"]) for p in silhouette]
        edges = {"left":min(p["x"] for p in projected),"right":max(p["x"] for p in projected),
                 "top":min(p["y"] for p in projected),"bottom":max(p["y"] for p in projected)}
        cropped = edges["left"] < 0 or edges["right"] > args.width or edges["top"] < 0 or edges["bottom"] > args.height
        info["camera_frames"].append({"time_s":time_s,"position_m":position,"target_m":target,
            "exposure":scene.view_settings.exposure,"azimuth_deg":23 if kind == "title" else 24 if kind == "motion" else hero_azimuth(params,time_s,args.duration),
            "projected_width_ratio":(edges["right"]-edges["left"])/args.width,
            "width_below_preferred":(edges["right"]-edges["left"])/args.width < .7,
            "projected_height_ratio":(edges["bottom"]-edges["top"])/args.height,
            "projected_bounds_px":edges,"cropped":cropped})
        if cropped:
            raise RuntimeError(f"构图失败：{time_s:g} 秒门机外包角点超出安全画幅")
        payload["frames"].append({"frame":index,"time_s":time_s,"file":filename,
                                  "exposure":scene.view_settings.exposure,"nodes":frame_anchors})
        if index % 10 == 0 or index == len(times):
            remaining = sum(info["frame_seconds"])/index*(len(times)-index)
            print(f"已完成第 {index}/{len(times)} 帧，单帧耗时 {elapsed:.2f} 秒，"
                  f"预计剩余 {remaining:.1f} 秒",flush=True)
    if kind == "model_orbit" and any(frame["width_below_preferred"] for frame in info["camera_frames"]):
        warning = "部分时刻画宽低于 70%；固定机位高度、焦距和环绕方位下，优先保证上沿留白及下沿 84%"
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
