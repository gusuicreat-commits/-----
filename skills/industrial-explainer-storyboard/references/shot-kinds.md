# 十种镜头

下表的“写实渲染”指项目已接入的原生三维离线背景渲染路径；最终文字仍由播放器叠加。
脚本不执行任何渲染。写实路径不可用时由下游处理回退，此技能不保证画面验收。

| kind | 用途与选择 | 写实渲染 |
|---|---|---|
| title | 开场主题；适合标准模式短钩子；写实首镜头改用环绕 | 模型存在时是，否则否 |
| outro | 收束主题；简短回扣，不添加新事实或保证 | 模型存在时是，否则否 |
| model_orbit | 整机尺度与主梁轮廓；展示整体；缺实际模型时仅作为待渲染草稿 | 是 |
| analogy | 以真实比例对比尺寸；仅有已确认可换算参数时用；不可心算比例 | 仅 building_floor / football_field；其余使用网页画面 |
| motion | 小车、起升或大车运动；必须有实际 rig 轴、行程；缺 rig 不编造 | 是 |
| exploded | 拆解主梁、支腿、小车关系；已知模型节点才使用；不是设备真实拆装过程 | 是 |
| data_card | 集中展示参数和页码；选择 2–4 个已确认参数；不能用缺失参数填满版面 | 模型存在时是，否则否 |
| real_media | 设备应用与环境实拍；必须使用素材库 ID；reference 不是本机 | 否 |
| ai_broll | 光影、环境、抽象转场；不得在 prompt/caption 出现设备或结构词 | 否 |
| weld_macro | 焊缝错边量与微观尺度；必须有已确认焊缝精度；缺精度禁用 | 否，网页微距画面 |

## params 默认值
默认值来自规划器；是字段初值，不代表已确认的设备参数。motion 的起终点必须按实际 rig 重写。

- `title`：`{"title": "", "subtitle": ""}`
- `outro`：`{"title": "", "subtitle": ""}`
- `model_orbit`：`{"from_deg": -30, "to_deg": 30, "elevation_deg": 15, "distance": 1.6, "highlight": ["girder"]}`
- `analogy`：`{"analogy": ""}`
- `motion`：`{"axis": "trolley", "from_m": -30, "to_m": 30}`
- `exploded`：`{"parts": ["girder", "leg_left", "leg_right", "trolley"], "spread_m": 12}`
- `data_card`：`{"facts": ["F_rated_load", "F_span"]}`
- `real_media`：`{"asset": "IMG_01", "effect": "kenburns", "caption": ""}`
- `ai_broll`：`{"recipe": "sunrise_port", "palette": "warm", "prompt": ""}`
- `weld_macro`：`{"fact": "F_weld_tolerance", "analogy": ""}`

## 字段与来源

- title/outro/data_card：有模型 source=model，无模型 source=graphic；其他模型镜头为 model，real_media=real，ai_broll=ai。
- model_orbit：角度为度，distance 是包围盒对角线倍数；highlight 只用模型已有节点。
- analogy：params.analogy 必须存在于计算后的 analogies；以 ratio 展示真实比例，不能为视觉效果修改。
- motion：axis 为 trolley/hoist/gantry，分别沿 X/Y/Z；from_m/to_m 是轴上绝对坐标，不是相对位移；起升 Y 表示吊钩离地高度。
- speedup 由校验器计算：ceil(实际行程耗时/镜头时长)，最小 1；实际耗时=距离/(速度/60)，速度单位 m/min；不要自行填写倍速。
- exploded：parts 可用 girder、leg_left、leg_right、trolley 等已知节点，spread_m 单位米；不要把分解位移当设备工作行程。
- data_card：params.facts 与 fact_refs 对齐，显示 source.doc 和 source.page。
- real_media：effect=kenburns/none；asset 与 asset_refs 一致，caption 对参考素材写“参考实拍 · 非本机”。
- ai_broll：recipe=sunrise_port/night_factory/blueprint_grid/particles，palette=warm/cool/steel；prompt 和可选 caption 都不能画设备本体。
- weld_macro：params.fact 指已确认错边量；params.analogy 指 hair/thickness 的计算类比；单位换算由脚本处理。
- review 默认 {"status":"pending","note":""}；自动校验不能代替人工批准。

## 模型节点与输入缺失

契约节点：crane、girder、leg_left、leg_right、trolley、hoist_hook、rope、rail_left、rail_right、cab。
Y 向上，X 沿主梁，Z 沿轨道；trolley 属于 crane，hoist_hook/rope 属于 trolley。
缺少模型节点信息时，不声称节点已核实；缺少 rig 时跳过运动校验并列人工确认。
缺焊缝参数时删除该镜头规划，改讲已有证据；用户明确必讲的缺参数不能悄悄省略，须报告缺项。
