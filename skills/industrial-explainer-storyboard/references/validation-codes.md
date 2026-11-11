# 校验码与具体修法

severity 沿用后端；block 阻断交付，warn 逐项处理，info 记录人工或输入状态。
CHECK_ERROR 虽为 info，代表检查未完成，脚本 passed=false，必须修复输入后重跑。
UNVERIFIED_FACT / REFERENCE_ASSET_CLAIM 虽为 warn，创作约束仍禁止引用未确认参数或冒认实拍。

| code | severity | 含义与典型触发 | 字段与具体修法 |
|---|---|---|---|
| QUOTE_MISMATCH | block | 引用值、单位或文字事实不在 source.quote 中；规范化全角、千分位、小数及单位同义词后比较，不能子串误认。交人工核对原文，不改摘录迁就参数。 |
| QUOTE_ABSENT | warn | 被引用事实无 quote；补齐原文摘录后重新核验。 |
| ANALOGY_ROUNDING | block | ratio、参照尺寸或比较词违背真实比值/容差；重新运行 compute_analogy。 |
| UNSUPPORTED_CLAIM | block | support 不存在、不可引用，generic 含具体信息，或已登记 claims 遗漏台词分句；补齐出处。 |
| CLAIMS_MISSING | info | 兼容旧分镜；skill 在 delivery_warnings 复制为 warn，交付前补齐每句陈述。 |
| MOTION_SPEEDUP_MISMATCH | block | 运动超过资料速度但声明的 speedup 小于所需倍速；使用程序计算的标注。 |
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

缺 project 时 MODEL_DIMS_MISMATCH / MODEL_ASSUMED 跳过；缺 rig 时运动轴、范围、速度与倍速检查跳过，报告 skipped 写明原因。
传入空 rig.axes 与不传 rig 不同：空轴表是已知没有轴，会报 MOTION_AXIS_UNAVAILABLE。
不传 assets 等于空素材库，引用实拍仍报 ASSET_MISSING，不跳过。
模式通过 --mode photoreal 或 project.render_mode 指定；不指定时为标准模式。
几何尺寸仅消费已有 dims_check，不重新计算几何；实际图像、配音、渲染验收不在此报告覆盖范围。
每条问题含 code、severity、shot、field、message、fix，保留 id/hint 以便和后端比对。
同一镜头多个错误引用或裸数字逐项报告；同一参数在同镜头多处引用按后端规则去重。
schema 格式问题另列 input_errors，不创造后端没有的真实性 code；任何格式错误都会使 passed=false。
人工确认项单列 manual_review，包含未被引用的未确认/否决参数，避免用户点名参数被静默忽略。

## 宣称、冲突与量纲

| code | 严重度 | 触发与修法 |
|---|---|---|
| EXAGGERATION | block | 台词、caption、标题/副标题（含顶层 title）中出现无同句排名证据的最高级；例如「国内最大」改为「起重量 {{F_rated_load}}」。 |
| ABSOLUTE_CLAIM | warn | 零误差、绝对安全、完美、永不等承诺；改成带出处的精度参数及条件。 |
| FACT_CONFLICT | block | verified/confirmed 事实同名、同 id 或同 key 但数值不同，任一条被直接/间接引用；交人工确认，不自行选择。等值的常用单位换算不算冲突。 |
| UNIT_SUSPECT | warn | 参数名称或规范 ID 与单位量纲不符；核实原文的数值与单位，不自动修单位。 |

词表和简单量纲表的唯一数据源为 [claim-rules.json](claim-rules.json)，后端和独立脚本都读取它；增词后须跑两端 parity。

facts 支持可选字段 `claim_type: "ranking"`，缺省为普通参数。排名事实仍保持数值 value：例如 `{"id":"F_domestic_first","name":"国内首台认证序位","value":1,"unit":"","claim_type":"ranking","status":"verified","source":{"doc":"认证证书.pdf","page":1,"quote":"经认证为国内首台，认证序位1"}}`。这是格式示例，不是真实证书。

豁免例句：「证书确认国内首台，认证序位{{F_domestic_first}}。」只有 verified、出处完整且对应宣称在 quote 中、同句显式占位引用才可豁免；confirmed、只列 fact_refs、隔句/跨字段引用均不可豁免。不得把地方证书范围扩展为全球排名，也不得拿起重量等普通事实冒充排名。ABSOLUTE_CLAIM 不因排名事实豁免。

发现冲突即列入人工确认项，暂不引用冲突两方；即使不引用而没有 block，也必须在报告说明需求中未完成的内容。不要删改原始 facts 或将另一条降级来通过校验。

## 陈述与量化指标

每镜头可选 claims 数组，条目含 text 与 support（事实 ID、素材 ID 或 generic）。后端旧数据缺失记 info；技能交付时列为 warn，不得省略。具体用途和结构形式同样需要文字事实支撑：`{"id":"F_structure","name":"结构形式","type":"qualitative","value":"采用箱形主梁","unit":"","status":"verified","source":{"doc":"说明.pdf","page":1,"quote":"采用箱形主梁"}}`。此处仅为格式示例。

规则词表与正则见 claim-rules.json 的 specific_claim_terms / specific_claim_patterns；涵盖型号、客户、项目、地名、年份、认证及排名，规则不能穷举所有专名。support 存在不等于语义蕴含；端到端可溯源率进一步保守核对原句与证据，无法对齐的文字改写不算通过。

误报豁免：「一根头发丝」「第一步」「唯一要做的」及有已确认引用的「最高可达 {{F_x}}」。后一项仅表示参数上限，不允许扩展为国内/全球排名。

变异召回统计指定问题码命中的 block/warn；无关警告不计命中。正确样本的任何 block/warn、CHECK_ERROR 或 schema 错误都算误报。可溯源率分母独立从全部台词分句提取，不使用模型登记的 claims 数量；缺失、空产物、失败不会成为100%。
