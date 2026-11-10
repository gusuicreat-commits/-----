# 门机写实样片

独立离线入口，不接入视频流水线。只接受 `verified` / `confirmed` 参数，配置及尺寸规则按文件加载，无需额外依赖。根目录使用 `app.config.ROOT`，项目目录支持 `KEPU_PROJECTS_DIR`。

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

保留 `--still-at 3`，仍输出 `still_eevee.png` 或 `still_cycles.png`；与 `--stills` 互斥。两者都省略时输出 `frame_00001.png…`，6 秒共 180 帧，不含结束点。支持 `model_orbit` 和 `title`；本入口只出三维底图，不绘制标题文字。Cycles 优先 Metal，设备不可用时记录原因并回退 CPU。

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

契约坐标 `(X,Y,Z)` 映射为 `(X,-Z,Y)`。机位离地 8 m、30 mm 焦距、36 mm 水平传感器，看向 `(0,整机高×0.45,0)`；`from_deg/to_deg` 先夹到 ±30°，再缩放为中点 35° ±12°，默认 23°→47°，保留三次缓动。

每帧从实际部件计算整机外包八角点（排除轨道），二分求解满足以下条件的最近水平距离：画宽 ≤82%、画高 ≤80%、四边留白均 ≥6%。额外保留底部 6% 留白，避免车轮贴边。纯 Python 测试用独立针孔矩阵核对投影，不依赖渲染运行时。

本离线英雄镜头按任务要求覆盖合同中的通用 `elevation_deg` / `distance` 语义，旧字段可传入但不影响取景；合同文件未改，网页播放器未改。旧 `orbit` 数学函数及其回归测试保留。

`anchors.json` 中 `frames[]` 包含 `frame/time_s/file/nodes`；节点含 `x/y/visible/in_frame/center_m`。像素以左上为原点；锚点使用与实际相机一致的水平传感器及焦距（16:9 时垂直视场角约 37.299°）。`visible` 是表面射线采样近似，`in_frame` 只描述中心是否入画。

`render_<engine>.json` 记录设备、尺寸、参数缺省项、建场耗时、逐帧正式渲染耗时及 `camera_frames`：机位、目标点、方位角、宽高占比、边界与裁切状态。两个引擎用独立目录，避免覆盖 `anchors.json`。

## 自动测光

每个正式帧在相同相机、相同引擎下先渲染一次 192×108、8 采样探测图。临时隐藏门机以外的几何（包括轨道）、开启透明背景，保留灯光与世界光。随后复用线性渲染结果，经场景 AgX、对比度与候选曝光导出 16 位 RGBA PNG，按 Non-Color 读取编码像素，避免再次进行 sRGB 解码；只统计 alpha>0.5 的像素。

曝光先以 log2 关系估计，再在缓存结果上求根：第一阶段对准亮度中位数 0.42；第二阶段仅在必要时压低曝光，使 98 分位 ≤0.92。显示变换是非线性的，不能保证两次 log2 校正就收敛，因此每阶段最多做 16 次小图显示变换，**只追光一次**。若高光约束使中位数低于目标，记录 `highlight_limited=true`，不把两项目标都写成通过。

`exposure` 为最后一帧最终曝光；`metering_frames[]` 逐帧记录曝光、中位数、98 分位、有效像素数、显示变换次数与测光耗时。正式帧耗时不含探测耗时，`total_seconds` 包含两者。测光结束或异常时均恢复分辨率、透明背景、采样与物体显隐；临时图自动删除。逐帧曝光未经时间平滑，动画亮度连续性需外部验收。

## 场景与验收边界

无体积雾。天空多重散射、太阳高度 9°、气溶胶 2.0、臭氧 1.0、背景强度 0.5；天空色调节点亮度 0.15、饱和度 1.15，降低天空填充。太阳灯从中点机位左侧 65° 入射，使相机同时看到受光面和背光面，与天空太阳同向；角径 0.6°、能量 1.6，低太阳形成长投影。AgX 中高对比，曝光由探测图确定，不使用固定曝光常数。朝阳/背阳显示亮度比 ≥2.5:1 是外部图片验收目标，纯数学与节点测试不证明实际光比。

3 km 地坪从距相机 800 m 开始渐隐，1500 m 完全衔接同方向地平线天空；远景天空分支与世界天空共享参数和强度，近处地坪不自发光，保留太阳投影。地坪使用大块色斑与细颗粒两层噪声、0.7–0.9 粗糙度；仅单向 12 m 间距、宽 0.03 m、暗 10% 伸缩缝，无浅色网格。轨道基础略浅。船段沿 X 长 36 m、宽 22 m、高 14 m，中心 Z=-15 m；平底、4 m 舭圆弧、直舷侧、开口顶、0.8 m 纵骨、三道横舱壁、6 m 焊缝、六个支墩。低机位下内部骨架的可见程度受舷侧遮挡，不能等同于俯视剖视图。

远侧厂房为 #4F5965，含屋脊总高 12–25 m，配坡面天窗；一侧船坞严格为宽 60 m、长 200 m，端部由地坪封闭，不延伸到地平线；保留混凝土坞墙与两台远景门机。船段 #7A3B2A、近处地坪 #8C8984 均无自发光。涂装色板按 sRGB 转线性，避免把十六进制颜色直接当线性值导致发白；主体为 #E9E6DE，安全红 #B3261E，电气房黄 #E0A21B，加劲肋间距 2.5 m、凸出 0.15 m。附属结构及场景均为示意，不作为设备技术事实。

验证：`cd backend && uv run pytest -q`。本轮新增安全框与最近距离、显示空间亮度统计、非线性/饱和曝光求解、高光优先、探测成功/失败状态恢复、船坞边界与远景渐隐测试。测试使用模拟渲染接口，不启动图形渲染，不联网。

本轮沙箱不启动图形渲染，没有生成验收图片。两种引擎的实际光比、长投影、天空色调、船段深红褐与地面中灰仍须按上方命令在沙箱外验收。薄焊缝、纵骨和远景合批为网格，并省去其倒角修改器，以控制渲染开销。
