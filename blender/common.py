"""尺寸、坐标及取景数学；可在普通 Python 中运行。"""
from __future__ import annotations

import importlib.util
import json
import math
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping

def _load_file(name: str, path: Path) -> ModuleType:
    """只加载标准库模块文件，不执行后端包的初始化。"""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载配置或尺寸规则：{path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = _load_file("_render_config", Path(__file__).resolve().parents[1] / "backend/app/config.py")
_dimensions = _load_file("_render_rig", config.ROOT / "backend/app/model3d/rig.py")._dimensions

ROOT = config.ROOT
FOV_DEG = 40.0
HERO_LENS_MM = 30.0
HERO_SENSOR_MM = 36.0
NODES = ("crane", "girder", "leg_left", "leg_right", "trolley", "hoist_hook", "rope", "rail_left", "rail_right", "cab")
ANCHOR_NODES = ("girder", "leg_left", "leg_right", "trolley", "hoist_hook", "cab")
Vec3 = tuple[float, float, float]


def set_attr(obj: Any, name: str, value: Any) -> bool:
    """可选属性交给运行时校验，兼容动态枚举与不同版本。"""
    try:
        if not hasattr(obj, name):
            raise AttributeError(name)
        setattr(obj, name, value)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        print(f"警告：跳过可选属性 {name}，属性不可用或不支持该值 {value!r}", flush=True)
        return False
    return True


def set_input(node: Any, name: str, value: Any) -> bool:
    try:
        socket = node.inputs.get(name)
        if socket is None:
            raise AttributeError(name)
        socket.default_value = value
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        print(f"警告：跳过节点输入 {name}，输入不可用或不支持该值 {value!r}", flush=True)
        return False
    return True


def link_input(links: Any, source: Any, output: str, target: Any, name: str) -> bool:
    """缺少可选着色插槽时保留节点默认值。"""
    try:
        start, end = source.outputs.get(output), target.inputs.get(name)
        if start is None or end is None:
            raise AttributeError(name)
        links.new(start, end)
    except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
        print(f"警告：跳过节点连线 {output} → {name}，插槽不可用或类型不兼容", flush=True)
        return False
    return True


def resolve_path(path: str | Path) -> Path:
    """相对路径以项目根为基准，projects/ 支持测试目录覆盖。"""
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "projects":
        return config.projects_dir().joinpath(*path.parts[1:])
    return ROOT / path


def read_facts(path: str | Path) -> dict[str, Any]:
    return json.loads(resolve_path(path).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Dimensions:
    length: float
    height: float
    span: float
    lift_height: float
    girder_height: float
    wheel_count: int
    assumed: tuple[str, ...]

    @property
    def girder_top(self) -> float:
        return self.height - 5.5

    @property
    def girder_bottom(self) -> float:
        return self.girder_top - self.girder_height

    @property
    def hook_height(self) -> float:
        return self.height * 0.6

    @property
    def hoist_range(self) -> tuple[float, float]:
        return (2.0, min(self.lift_height, self.girder_bottom - 3))

    @property
    def bbox(self) -> Vec3:
        # 与参数化模型一致：轨道端点为 ±60，地面到小车顶为整机高度。
        return (self.length, self.height, 120.0)

    @property
    def center(self) -> Vec3:
        return (0.0, self.height / 2, 0.0)


def derive_dimensions(document: Mapping[str, Any]) -> Dimensions:
    accepted = {item["id"]: item["value"] for item in document.get("facts", [])
                if item.get("status") in ("verified", "confirmed")}
    used = _dimensions(accepted)
    length, height = used["F_girder_length"], used["F_overall_height"]
    span, gh = used["F_span"], used["F_girder_height"]
    if span < 12 or span + 2.4 > length or height - 5.5 - gh <= 5 or height * 0.6 + 4.1 >= height - 5.5:
        raise ValueError("参数无法容纳支腿、小车或吊钩，请检查跨度、主梁及整机高度")
    # 原模型每侧八个车轮占位，共十六个；有核验参数时严格采用参数总数。
    wheels = float(accepted.get("F_wheel_count", 16))
    if not math.isfinite(wheels) or not wheels.is_integer() or wheels < 4:
        raise ValueError("车轮总数必须是至少四个的整数")
    keys = (*used, "F_wheel_count")
    return Dimensions(length, height, span, used["F_lift_height"], gh, int(wheels),
                      tuple(key for key in keys if key not in accepted))


def wheel_distribution(count: int) -> tuple[int, int, int, int]:
    if isinstance(count, bool) or not isinstance(count, int) or count < 4:
        raise ValueError("车轮总数必须是至少四个的整数")
    q, r = divmod(count, 4)
    return tuple(q + (i < r) for i in range(4))


def to_blender(point: Vec3) -> Vec3:
    x, y, z = point
    return (x, -z, y)


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 4 * t**3 if t < 0.5 else 1 - (-2 * t + 2)**3 / 2


def orbit(dim: Dimensions, params: Mapping[str, Any], time_s: float, duration: float) -> tuple[Vec3, Vec3]:
    values = [float(params.get(key, default)) for key, default in
              (("from_deg", -30), ("to_deg", 30), ("elevation_deg", 15), ("distance", 1.6))]
    if not all(math.isfinite(v) for v in (*values, time_s, duration)) or duration <= 0 or values[3] <= 0:
        raise ValueError("镜头参数必须有限，距离和时长必须大于零")
    start, end, elevation, distance = values
    if not -89 < elevation < 89:
        raise ValueError("相机仰角必须在 -89° 与 89° 之间")
    a, e = math.radians(start + (end - start) * ease(time_s / duration)), math.radians(elevation)
    radius = math.sqrt(sum(v * v for v in dim.bbox)) * distance
    cx, cy, cz = dim.center
    return ((cx + math.sin(a) * math.cos(e) * radius, cy + math.sin(e) * radius,
             cz + math.cos(a) * math.cos(e) * radius), dim.center)


def frame_times(duration: float, fps: int) -> list[float]:
    if not math.isfinite(duration) or duration <= 0 or fps <= 0:
        raise ValueError("时长与帧率必须大于零")
    return [i / fps for i in range(math.ceil(duration * fps))]


def project_point(point: Vec3, camera: Vec3, target: Vec3, width: int, height: int,
                  fov_y_deg: float = FOV_DEG) -> dict[str, Any]:
    """契约坐标下的针孔投影；只判断画幅和相机正面。"""
    def unit(v: Vec3) -> Vec3:
        length = math.sqrt(sum(x * x for x in v))
        return tuple(x / length for x in v)
    forward = unit(tuple(b - a for a, b in zip(camera, target)))
    right = unit((-forward[2], 0.0, forward[0]))
    up = (right[1] * forward[2] - right[2] * forward[1],
          right[2] * forward[0] - right[0] * forward[2],
          right[0] * forward[1] - right[1] * forward[0])
    relative = tuple(p - c for p, c in zip(point, camera))
    dot = lambda axis: sum(a * b for a, b in zip(relative, axis))
    depth = dot(forward)
    if abs(depth) < 1e-9:
        return {"x": None, "y": None, "in_frame": False, "depth_m": depth}
    scale = height / (2 * math.tan(math.radians(fov_y_deg / 2)))
    x, y = width / 2 + dot(right) * scale / depth, height / 2 - dot(up) * scale / depth
    return {"x": x, "y": y, "in_frame": depth > 0 and 0 <= x <= width and 0 <= y <= height, "depth_m": depth}


def hero_fov_y(width: int, height: int) -> float:
    """方形像素、sensor_fit AUTO；竖幅按传感器宽度适配画高。"""
    if width <= 0 or height <= 0:
        raise ValueError("分辨率必须大于零")
    return math.degrees(2 * math.atan(HERO_SENSOR_MM / (2 * HERO_LENS_MM) * height / max(width, height)))


def hero_azimuth(params: Mapping[str, Any], time_s: float, duration: float) -> float:
    start, end = float(params.get("from_deg", -30)), float(params.get("to_deg", 30))
    if not all(math.isfinite(v) for v in (start, end, time_s, duration)) or duration <= 0:
        raise ValueError("镜头角度与时刻必须有限，时长必须大于零")
    start, end = (max(-30.0, min(30.0, v)) * .4 for v in (start, end))
    return 35 + start + (end - start) * ease(time_s / duration)


def framing_points(dim: Dimensions) -> list[Vec3]:
    """主体轮廓，不把两条 120 m 轨道计入取景宽度。"""
    boxes = [((-dim.length/2, dim.girder_bottom, -5.3),
              (dim.length/2, dim.girder_top+1.2, 5.3)),
             ((-6, dim.girder_top, -4.5), (6, dim.height, 4.5))]
    for x in (-dim.span/2, dim.span/2):
        boxes.append(((x-1.2, .3, -11.3), (x+1.2, 3.3, 11.3)))
    return enclosing_corners([p for box in boxes for p in box])


def enclosing_corners(points: list[Vec3]) -> list[Vec3]:
    """保守整机外包八角点，包含部件之间的空隙。"""
    low = tuple(min(p[i] for p in points) for i in range(3))
    high = tuple(max(p[i] for p in points) for i in range(3))
    return [(x,y,z) for x in (low[0],high[0]) for y in (low[1],high[1])
            for z in (low[2],high[2])]


def hero_camera(dim: Dimensions, params: Mapping[str, Any], time_s: float, duration: float,
                width: int = 1920, height: int = 1080,
                points: list[Vec3] | None = None) -> tuple[Vec3, Vec3]:
    """固定下沿 84%，联合求解俯仰与距离；上沿和侧边至少留白 6%。"""
    angle = math.radians(hero_azimuth(params, time_s, duration))
    points = framing_points(dim) if points is None else points
    if not points or not all(math.isfinite(v) for p in points for v in p):
        raise ValueError("取景轮廓必须包含有限坐标")
    points = enclosing_corners(points)
    fov = hero_fov_y(width, height)
    bottom_angle = math.atan(.68 * math.tan(math.radians(fov / 2)))

    def pose(distance: float) -> tuple[Vec3, Vec3]:
        camera = (math.sin(angle)*distance, 8.0, math.cos(angle)*distance)
        # 局部垂直平面中的俯仰角；最低投影角点决定下沿。
        pitch = min(math.atan2(p[1]-8, distance-p[0]*math.sin(angle)-p[2]*math.cos(angle))
                    for p in points) + bottom_angle
        return camera, (0.0, 8 + distance*math.tan(pitch), 0.0)

    def coverage(distance: float) -> float:
        camera, target = pose(distance)
        projected = [project_point(p, camera, target, width, height, fov) for p in points]
        if any(p["depth_m"] <= .01 for p in projected):
            return math.inf
        xs = [p["x"]/width for p in projected]
        ys = [p["y"]/height for p in projected]
        return max((max(xs)-min(xs))/.82,
                   (.5-min(xs))/.44, (max(xs)-.5)/.44, (.84-min(ys))/.78)

    low = max(p[0]*math.sin(angle)+p[2]*math.cos(angle) for p in points) + .02
    low = max(.02, low)
    high = max(low*2, dim.length, dim.height)
    for _ in range(32):
        if coverage(high) <= 1:
            break
        high *= 2
    else:
        raise ValueError("无法求解门机取景距离")
    for _ in range(48):
        mid = (low+high)/2
        if coverage(mid) > 1:
            low = mid
        else:
            high = mid
    return pose(high)


def exposure_curve(samples: list[tuple[float, float]], fps: int,
                   max_step: float = .02) -> list[tuple[float, float]]:
    """五点曝光的保守限速包络；只降低过亮点，保持高光约束。"""
    if fps <= 0 or max_step <= 0 or len(samples) < 2:
        raise ValueError("曝光曲线需要至少两个点及正帧率、步长")
    if any(not math.isfinite(v) for sample in samples for v in sample):
        raise ValueError("测光时刻和曝光必须有限")
    if any(b[0] <= a[0] for a,b in zip(samples,samples[1:])):
        raise ValueError("测光时刻必须严格递增")
    rate = max_step*fps
    return [(t, min(ev+rate*abs(t-ts) for ts,ev in samples)) for t,_ in samples]


def interpolate_exposure(samples: list[tuple[float, float]], time_s: float) -> float:
    """分段线性插值，无过冲；动画末帧也使用同一曲线。"""
    if time_s <= samples[0][0]:
        return samples[0][1]
    for (a, x), (b, y) in zip(samples, samples[1:]):
        if time_s <= b:
            return x+(y-x)*(time_s-a)/(b-a)
    return samples[-1][1]


def display_luminance(pixels: list[float]) -> dict[str, float | int]:
    """RGBA 必须是已通过显示变换的编码值；透明背景不参与测光。"""
    values = sorted(.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2]
                    for i in range(0,len(pixels),4) if pixels[i+3] > .5)
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError("测光失败：门机像素为空或亮度无效")
    def percentile(q: float) -> float:
        index = (len(values)-1)*q
        lo = int(index)
        return values[lo]+(values[min(lo+1,len(values)-1)]-values[lo])*(index-lo)
    return {"median":percentile(.5), "p98":percentile(.98), "pixel_count":len(values)}


def solve_exposure(measure: Any, initial: float = 0.0) -> tuple[float, dict[str, Any]]:
    """缓存探测图上求显示曝光；先匹配中位数，再约束高光。"""
    evaluations = 0
    def sample(exposure: float) -> dict[str, Any]:
        nonlocal evaluations
        evaluations += 1
        return measure(exposure)
    stats = sample(initial)
    # log2 给初始方向；显示变换非线性且可能已饱和，再用有界求根收敛。
    guess = initial + math.log2(.42/max(float(stats["median"]),1e-6))
    low, high = -24.0, 24.0
    guess = max(low, min(high, guess))
    for _ in range(16):
        stats = sample(guess)
        if stats["median"] > .42:
            high = guess
        else:
            low = guess
        guess = (low+high)/2
    exposure = low
    stats = sample(exposure)
    highlight_limited = stats["p98"] > .92
    if highlight_limited:
        low, high = -24.0, exposure
        for _ in range(16):
            mid = (low+high)/2
            if sample(mid)["p98"] > .92:
                high = mid
            else:
                low = mid
        exposure = low
        stats = sample(exposure)
    if stats["p98"] > .921 or stats["median"] <= 0:
        raise ValueError("测光失败：曝光范围内无法保留门机高光")
    return exposure, {**stats, "highlight_limited":highlight_limited,
                      "display_evaluations":evaluations}
