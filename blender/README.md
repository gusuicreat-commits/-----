# 门机样片与环绕动画

支持离线出图及视频流水线写实背景。只接受 `verified` / `confirmed` 参数，配置及尺寸规则按文件加载，无需额外依赖。根目录使用 `app.config.ROOT`，项目目录支持 `KEPU_PROJECTS_DIR`。

## 出图

在项目根目录运行，两种引擎分别输出三张图：

```sh
KEPU_BLENDER="${KEPU_BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"
for engine in eevee cycles; do
  "$KEPU_BLENDER" -b --factory-startup -P blender/render_shot.py -- \
    --facts blender/samples/facts.json \
    --shot-json '{"kind":"model_orbit","params":{"from_deg":-30,"to_deg":30}}' \
    --out "blender/samples/t14d/$engine" --engine "$engine" --stills 0.5,3,5.5
done
```

默认 1920×1080、64 采样、6 秒、30 fps。`--stills` 输出 `still_<engine>_0.5.png`、`still_<engine>_3.png`、`still_<engine>_5.5.png`，每帧均写锚点和渲染耗时。时刻单位是秒，不是进度。拒绝非有限、越界、重复时刻。

保留 `--still-at 3`，仍输出 `still_eevee.png` 或 `still_cycles.png`；与 `--stills` 互斥。两者都省略时输出 `frame_00001.jpg…`，6 秒共 180 帧，不含结束点，并在同目录合成 `orbit.mp4`（H.264、yuv420p、CRF 18）。编码工具由 `KEPU_FFMPEG` 指定，默认 `ffmpeg`；缺失时中文提示并保留序列帧，不报错。编码失败则报错，同时保留帧、锚点和失败报告。显式限制编码帧数，目录内旧的尾帧不会进入成片。支持 `model_orbit`、`title` 和 `motion`；本入口只出三维底图，不绘制标题文字。Cycles 优先 Metal，设备不可用时记录原因并回退 CPU。

动画预览：在以上命令中去掉 `--stills 0.5,3,5.5` 并加 `--preview`，默认得到 960×540、32 采样的 6 秒动画。预览将指定分辨率减半，只将实时引擎采样减半。每 10 帧打印中文帧号、单帧耗时和预计剩余时间。

`samples/` 被忽略，不提交生成图。缺少样例参数时可按示例资料第 2 页重建：

```sh
python3 - <<'PY'
import json
from pathlib import Path
values = {'F_girder_length': (104, '主梁总长', 'm'),
          'F_overall_height': (51, '整机高度', 'm'),
          'F_span': (88, '跨度', 'm'), 'F_lift_height': (45, '起升高度', 'm'),
          'F_girder_height': (6.5, '主梁截面高度', 'm'),
          'F_wheel_count': (64, '大车车轮总数', '个')}
data = {'facts': [{'id': key, 'name': name, 'value': value, 'unit': unit,
                  'status': 'confirmed', 'source': {'doc': '示例技术参数表.md',
                  'page': 2, 'quote': f'{name} | {value} {unit}'}}
                 for key, (value, name, unit) in values.items()]}
p = Path('blender/samples/facts.json')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
PY
```

## 相机与锚点

契约坐标 `(X,Y,Z)` 映射为 `(X,-Z,Y)`。机位离地 8 m、30 mm 焦距、36 mm 传感器、方形像素，`sensor_fit=AUTO`。`from_deg/to_deg` 沿用既有映射：先夹到 ±30°，再缩放为中点 35° ±12°，默认 23°→47°，保留三次缓动。

每帧从实际部件计算整机外包八角点（排除轨道），按最低投影角求俯仰，使下沿位于画高 84%；再二分求最近距离，确保上沿与左右留白 ≥6%、画宽 ≤82%。竖直构图优先。**已知约束冲突**：保留既有环绕方位时，样例轮廓在 0、3、6 秒的画宽约 72.8%、64.5%、56.1%，不能同时满足画宽 ≥70%。报告逐帧记录 `width_below_preferred`，并给出中文提示；未改设备比例或擅自缩小环绕角度。

本离线英雄镜头沿用既有特例，按任务要求覆盖合同中的通用 `elevation_deg` / `distance` 语义，旧字段可传入但不影响取景；合同文件未改，标准模式的相机行为不变。旧 `orbit` 数学函数及其回归测试保留。

`anchors.json` 中 `frames[]` 包含 `frame/time_s/file/exposure/nodes`；节点含 `x/y/visible/in_frame/center_m`。像素以左上为原点，按 `bpy_extras.object_utils.world_to_camera_view` 投影部件包围盒中心，小车排除吊钩与绳索。`visible` 与 `in_frame` 都表示中心在画幅内且位于相机正面，不判断遮挡；深度近零时坐标为 `null`。纯 Python 针孔数学保留相同 AUTO 传感器适配，覆盖横幅、竖幅及已知点。

`render_<engine>.json` 记录设备、尺寸、参数缺省项、建场耗时、逐帧正式渲染耗时及 `camera_frames`：机位、目标点、方位角、曝光、宽高占比、边界与裁切状态。`video` 记录合成结果。两个引擎使用独立目录，避免覆盖锚点和视频。

## 自动测光

在 t=0、25%、50%、75%、100% 五个时刻，以各自相机姿态、相同引擎各渲染一次 192×108、8 采样探测图。临时隐藏门机以外的几何（包括轨道）、开启透明背景，保留灯光与世界光。随后复用线性渲染结果，经场景 AgX、对比度与候选曝光导出 16 位 RGBA PNG，按 Non-Color 读取编码像素，避免再次进行 sRGB 解码；只统计 alpha>0.5 的像素。

曝光先以 log2 关系估计，再在缓存结果上求根：第一阶段对准亮度中位数 0.42；第二阶段仅在必要时压低曝光，使 98 分位 ≤0.92。显示变换是非线性的，不能保证两次 log2 校正就收敛，因此每阶段最多做 16 次小图显示变换，**只追光一次**。若高光约束使中位数低于目标，记录 `highlight_limited=true`，不把两项目标都写成通过。

五个曝光值采用分段线性插值，无过冲。若原始点斜率超过 0.02 EV/帧，先用保守限速包络降低过亮点，不抬高暗点；正式帧相邻曝光差 ≤0.02 EV。此时亮度中位数可能低于 0.42，五个测光点之间的实际高光仍需画面验收。

`exposure` 为最后一帧最终曝光；`metering_frames[]` 恰好记录五个原始曝光、中位数、98 分位、有效像素数、显示变换次数、测光耗时及 `smoothed_exposure`。静帧模式也使用同一条曲线，便于与动画对照。正式帧耗时不含探测耗时，`total_seconds` 包含探测与编码。测光结束或异常时均恢复分辨率、透明背景、采样与物体显隐；临时图自动删除。

## 场景与验收边界

无体积雾。天空多重散射、太阳高度 13°、气溶胶 2.0、臭氧 1.0、背景强度 0.7；天空色调节点亮度 0.15、饱和度 1.15。太阳灯从中点机位左侧 65° 入射，与天空太阳同向；角径 0.6°、能量 1.6。AgX 中高对比，曝光由门机测光确定。

地面为半径 8 km 圆盘，保留 60×120 m 船坞开口。按到相机的距离，从 500 m 开始混入零仰角天空，3 km 完全融合；采用与世界天空同方向、同参数、同强度的采样，避免固定暖灰在不同曝光下产生色差。世界天空负仰角方向钳到地平线，避免圆盘外露出暗下半球。近处地面基色 #9A968F，保留受光、投影及两层噪声。相机远裁切 20 km，覆盖圆盘。

两条轨道顶面粗糙度 0.25、金属度 1；浅色基础宽 1.2 m，近侧延伸至画面下方。两侧 0.15 m 宽的 #D9A400 安全通道线及一道停车线带噪声磨损。近侧放置三垛 12×3×1.2 m 深灰钢板，分层并有锈边；另一侧放置 12 m 长的黄色车头、深灰平板运输车。无人物。新增轨道延长段属于环境，不改变契约门机节点或外包尺寸。

厂房在 250–600 m 范围内分两排，含屋顶总高 12–28 m；固定随机种子使颜色与尺寸逐帧稳定。立面颜色 #4F5965 附近 ±8%，后排混入暖灰提高亮度；人字坡屋顶与锯齿采光屋顶交替，立面加横向窗带。保留既有船段、船坞和远景门机。附属结构、参照物及场景均为示意，不作为设备技术事实。

验证：`cd backend && uv run pytest -q`。测试涵盖独立针孔矩阵构图、传感器 AUTO 投影、曝光限速、缺失编码器与编码失败、五次测光及 180 帧完整输出调度、预览与静帧模式；图形接口及编码进程在单测中替换，不联网。

本轮沙箱不启动图形渲染，不能据此确认地平线无暗缝、前景实际遮挡、阴影闪烁或像素级锚点对位。验收方需按上方命令输出三张静帧，再去掉 `--stills` 输出完整动画，叠加 `anchors.json` 核对。

## 流水线写实模式

工作台「画面风格」选择写实后，从渲染阶段重跑。项目设置接口为 `PATCH /api/projects/{pid}/settings`，请求 `{"render_mode":"photoreal"}`；默认值为 `standard`。项目详情返回 `render_mode` 和 `blender_available`。

可执行文件依次取 `KEPU_BLENDER`、应用目录、系统搜索路径；显式指定无效路径时回退网页三维。`KEPU_BLENDER_ENGINE=eevee|cycles` 选择引擎，`KEPU_BLENDER_PREVIEW=1` 使用 960×540，`KEPU_BLENDER_TIMEOUT_S` 为每镜头超时秒数，默认 1800。超时或失败只回退当前镜头。

序列默认 JPEG、质量 92，`--frame-format png` 可改为 PNG。`--duration` 使用时间线实际时长，`--fps` 使用时间线帧率；五点测光仍按时长比例分布。流水线传入 `--skip-video`，仅保留背景帧和锚点，最终视频统一由播放器叠加 HTML 后合成。

`title` 相对英雄基准方位偏 −12°，初始投影宽 50%，中心位于 (0.70,0.56)，六秒内距离减少 6%，之后保持。`motion` 用三次缓动插值，小车沿 X、吊钩使用世界高度且绳索顶部固定、大车沿 Z；大车镜头相机同步平移，轨道和环境保持静止。运动机位固定方位 24°、离地 8 m，视点沿主梁偏 +10 m。

缓存位于 `projects/<pid>/renders/blender/<shot_id>-<key12>/`，完整成功后写 `done.json`。键包括脚本、相关已核验参数、镜头参数、实际时长、帧率、引擎及分辨率；时间线增加 `bg`，分镜文件不变。播放器将预览锚点缩放到 1920×1080，逐帧等待解码，再叠加原有 HTML。

离线检查：`cd web && node --test tests/background.check.mjs`。浏览器夹具测试：`cd web && npx playwright test --project=player --grep T16`，需在支持浏览器的验收环境运行。三张 16×9 纯色 JPEG 可由 `backend/.venv/bin/python web/tests/fixtures/background/generate.py` 重新生成。
