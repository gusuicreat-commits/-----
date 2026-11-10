# 校验码与具体修法

severity 沿用后端；block 阻断交付，warn 逐项处理，info 记录人工或输入状态。
CHECK_ERROR 虽为 info，代表检查未完成，脚本 passed=false，必须修复输入后重跑。
UNVERIFIED_FACT / REFERENCE_ASSET_CLAIM 虽为 warn，创作约束仍禁止引用未确认参数或冒认实拍。

| code | severity | 含义与典型触发 | 字段与具体修法 |
|---|---|---|---|
| UNKNOWN_FACT | block | {{F_missing}} | `fact_refs/narration/params`：删除不存在的参数引用，并在 narration、fact_refs、params.facts、params.fact 及相关类比中改用同一已确认参数 ID |
| REJECTED_FACT | block | 引用 status=rejected 的 F_span | `fact_refs/narration/params`：移除被否决参数的台词、画面字段及关联类比；需要恢复时先让人工核实原始文档 |
| UNVERIFIED_FACT | warn | 引用 status=extracted/needs_review 的 F_span | `fact_refs/narration/params`：暂时移除该参数的所有引用，将缺失内容列入人工确认项；不得自行改写 facts.status |
| UNSOURCED_NUMBER | block | 台词写 104米 或 三十米 | `narration`：将 message 指出的数字替换为已确认参数的 {{F_id}} 或计算后的 {{A_id}}；无对应参数则删去该数值断言 |
| ANALOGY_MISSING | block | 台词引用未登记 {{A_missing}} | `analogy_refs/narration`：为指出的 A_id 登记 fact/ref/axis 请求，运行 compute_analogy.py，将结果写入 analogies 并对齐 analogy_refs 与台词占位符 |
| ANALOGY_PARAM | block | params.analogy 不在 analogies | `params.analogy`：从已计算的 analogies[].id 中选择 ID 填入 params.analogy；没有可用参数时改为非类比镜头 |
| AI_SHOWS_EQUIPMENT | block | ai_broll.prompt 写“主梁特写” | `params.prompt/params.caption`：逐项移除 prompt 和 caption 内的设备本体词，改写为光影或环境；需展示设备时改用 model_orbit/source=model 或 real_media/source=real |
| SOURCE_MISMATCH | block | real_media.source=model | `kind/source`：按 kind 修正 source：ai_broll=ai、real_media=real；无模型的 title/outro/data_card=graphic，其余为 model |
| MOTION_AXIS_UNAVAILABLE | block | rig 无 hoist，params.axis=hoist | `params.axis`：从提供的 rig.axes 键中选择轴；没有合适轴时改为静态 model_orbit 并重写 params |
| MOTION_SPEED_UNSOURCED | warn | 速度未确认、非 m/min 或 <=0 | `params.speedup/rig.axes`：核实所选轴 speed_fact 对应事实，要求 verified/confirmed、unit=m/min、value>0；重跑校验计算倍速，不手填速度 |
| MOTION_OUT_OF_RANGE | block | 行程 [-30,30] 但 from_m=-31 | `params.from_m/params.to_m/duration_s`：将 from_m、to_m 改到所选 rig.axes[axis].range_m 内，duration_s 改为有限正数，再重跑以计算 speedup |
| ASSET_MISSING | block | params.asset=IMG_missing | `asset_refs/params.asset`：把不存在的素材 ID 替换为 assets[].id 的有效值，并同步 asset_refs 与 real_media.params.asset |
| REFERENCE_ASSET_CLAIM | warn | reference 素材配“这台” | `narration`：将台词里的「这台」「本机」「我们的」逐一改为「像这样的造船门机」等泛指；保留参考实拍来源标签 |
| DUPLICATE_PHRASE | block | 相当于{{A_x}} 展开后重复相当于 | `narration`：按 message 删除重复词；若来自类比占位符，只保留 {{A_id}}，删除它前后的「相当于/大约/那么高」等重复修饰 |
| NARRATION_TOO_LONG | warn | len(展开台词)/4.5 > duration_s+1 | `narration/duration_s`：缩短该镜头展开后的台词，或把 duration_s 调至展开字数/4.5+0.8 秒；同时保持全片目标时长 |
| DURATION_OUT_OF_RANGE | warn | 总时长 20 秒或 61 秒 | `shots[].duration_s`：调整各镜头 duration_s，使总时长落在 30–60 秒内，并满足需求时长 |
| NOT_REVIEWED | info | 任意镜头 review.status=pending | `shots[].review.status`：请人工逐镜头复核台词、画面来源和出处；仅人工确认后更新 review.status，自动检查不代替人工批准 |
| MODEL_DIMS_MISMATCH | warn | model.dims_check[].ok=false | `project.model.dims_check`：请模型负责人核实尺寸单位、坐标轴和来源文档，修正模型并重新生成 dims_check；不要手改 ok 消除问题 |
| MODEL_ASSUMED | info | parametric 模型 assumed 非空 | `project.model.assumed`：请人工补充并确认列出的缺失参数，再重建模型；保持默认值标记直到重建完成 |
| PHOTOREAL_OPENING | warn | 写实首镜头 title 或无 girder 高亮 | `shots[0].kind/params.highlight`：把首镜头设为 model_orbit、source=model，并在 params.highlight 包含 girder |
| PHOTOREAL_REAL_MEDIA_ORDER | warn | 有 real_media 但第二镜头不是它 | `shots`：将首个 real_media 移至第二镜头，保留原镜头 id 和人工台词 |
| PHOTOREAL_MISSING_EXPLODED | warn | 写实片没有 exploded | `shots[].kind`：增加或改设一个 exploded/source=model 镜头，params.parts 仅用已知节点，并重新分配时长 |
| PHOTOREAL_MISSING_MOTION | warn | 写实片没有 motion | `shots[].kind`：取得真实 rig 后增加一个 motion/source=model 镜头；设置有效 axis/from_m/to_m；缺 rig 时交人工确认，不编造行程 |
| PHOTOREAL_MODEL_COUNT | warn | 环绕/分解/运动/title 合计不到三个 | `shots[].kind`：使 model_orbit、exploded、motion、title 合计至少三个，并保持全片目标时长 |
| PHOTOREAL_ANALOGY_COUNT | warn | 写实片安排两个 analogy | `shots[].kind`：仅保留一个最直观的 analogy，将其余类比镜头改为结构或参数展示并清理不再使用的引用 |
| CHECK_ERROR | info | params=null 或 duration_s 缺失导致局部检查异常 | `input`：按 message 定位检查阶段，修正相关字段类型及缺失字段，重跑校验；不得把此条 info 当作已检查通过 |

## 输入范围和报告解释

缺 project 时 MODEL_DIMS_MISMATCH / MODEL_ASSUMED 跳过；缺 rig 时三个 MOTION_* 跳过，报告 skipped 写明原因。
传入空 rig.axes 与不传 rig 不同：空轴表是已知没有轴，会报 MOTION_AXIS_UNAVAILABLE。
不传 assets 等于空素材库，引用实拍仍报 ASSET_MISSING，不跳过。
模式通过 --mode photoreal 或 project.render_mode 指定；不指定时为标准模式。
几何尺寸仅消费已有 dims_check，不重新计算几何；实际图像、配音、渲染验收不在此报告覆盖范围。
每条问题含 code、severity、shot、field、message、fix，保留 id/hint 以便和后端比对。
同一镜头多个错误引用或裸数字逐项报告；同一参数在同镜头多处引用按后端规则去重。
schema 格式问题另列 input_errors，不创造后端没有的真实性 code；任何格式错误都会使 passed=false。
人工确认项单列 manual_review，包含未被引用的未确认/否决参数，避免用户点名参数被静默忽略。
