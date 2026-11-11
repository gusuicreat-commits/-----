---
name: industrial-explainer-storyboard
description: 该技能依据已确认参数表，为起重机、门机、桥机和工业装备编写科普视频、宣传片、展会视频及投标视频的分镜、脚本与台词，程序计算类比并执行参数核对、真实性校验，交付可接入渲染流水线的 shotlist.json。用户要求规划、修改、审查工业视频分镜或核验台词数字、素材来源时应主动使用；仅处理分镜与校验，不执行渲染、配音或合成；普通原理问答和非视频投标技术方案不触发。
---

# 工业装备分镜与真实性校验

## 适用范围与输入输出

将需求与已确认参数转为可追溯分镜；支持首次规划、局部修改和现有 shotlist 审查。
脚本仅需 Python ≥3.11 标准库，可复制整个技能目录独立运行，不依赖项目后端。

必需输入：`facts.json`（顶层 `facts` 数组）和需求（用途、目标时长、语气、必讲内容）。
参数包含 `id/name/value/unit/source:{doc,page,quote}/status`；只使用 `verified/confirmed`。文字事实用 `type: "qualitative"`、字符串 value（如「采用箱形主梁」）、空 unit，必须带原文出处；参见 `scripts/facts.schema.json`。
`extracted` 虽不是交付契约内的标准状态，也按未确认处理，不能引用。
可选输入：`assets.json`、已有 `shotlist.json`、`project.json`（模型元数据和 render_mode）、`rig.json`（真实运动轴、行程、速度参数引用）。
缺少素材库视为空库；缺少模型元数据时 title/outro/data_card 用 `source=graphic`；不凭空声称已有模型。
有运动需求但缺 rig 时列人工确认项，不猜行程；写实需求不得为了通过而删除所需运动镜头。
输出：`shotlist.json`、`validation-report.json`、中文校验摘要；附 `resolved-text.json` 便于人工听读。

## 可复制的步骤清单

- [ ] 1. 读取需求和输入。列出可用参数 ID、出处页码、未确认参数及需求缺失项；只引用 verified/confirmed，保留 review.status=approved 或 human_edited=true 的镜头全部原始字段（台词逐字、id、复核状态及其时长等），压缩需求只改其他镜头；无法满足则报告原因。先排查同名/同 key 的事实冲突，交人工确认，不能自行选值。
- [ ] 2. 读 [narrative-arcs.md](references/narrative-arcs.md)，选择科普、展会或投标叙事弧与时长配比；默认 45 秒、6–9 镜头；明确要求 15 秒时用 3–4 镜头，聚焦一个观众问题，不强塞全部主题，并在报告解释契约默认 30–60 秒的时长警告。按下方讲解配方入口选择尺度、运动或结构之一，只有需要时加载相应配方。
  用户要求加长、多角度或更多转场时，读 [cinematography.md](references/cinematography.md)：按每镜的信息功能设计景别、轴线和过渡，先交关键帧验收方案。30–45 秒是此类需求的可选创作范围，镜数服从内容，不固定八镜；不得把独立导演方案冒称为应用已支持的渲染 profile。
- [ ] 3. 读 [shot-kinds.md](references/shot-kinds.md) 和 [narration-rules.md](references/narration-rules.md)，按 [shotlist.schema.json](scripts/shotlist.schema.json) 起草 `draft.json`。需要类比时读 [analogy-library.md](references/analogy-library.md)，只登记请求，不心算 ratio/text，比较词也只能由 compute_analogy 生成。
  起草台词前读 [copywriting.md](references/copywriting.md)，按用途选择钩子、语气和节奏，不照搬无事实支持的示范。
- [ ] 4. 为每句台词列出 `claims: [{"text": "台词原句", "support": "F_id 或素材 ID 或 generic"}]`，不可遗漏分句。用途、结构形式用 qualitative 事实支撑；generic 仅适用于不含型号、客户、项目、地名、年份、认证和排名的通用表达。未登记 claims 的旧分镜后端记 info，技能交付按 warn，交付前必须补齐。执行下面的类比计算与台词展开命令。自查开场 3 秒有没有钩子、每镜是否一个信息点，再检查展开后的语句、重复用词和时长；按实际字数调整台词或分配时长，不能用未展开占位符长度估计。
- [ ] 5. 执行校验命令。按 [validation-codes.md](references/validation-codes.md) 修复所有 block 后重跑，最多进行两轮“修复→复验”；仍有 block 或检查失败则停止，将剩余问题交人工复核，不降级问题、不删事实约束。warn 逐项解释：未确认参数和实拍冒认必须修；写实需求必须消除 PHOTOREAL_*。仅修有问题的字段，保留其余人工台词。
- [ ] 6. 只有校验通过、交付格式完整、需求约束满足才交付最终 `shotlist.json`。有缺输入导致的未检查项时明确交人工，不能声称完整验收通过；失败产物标为待复核草稿。报告写清问题、修法、人工确认项和跳过项。

初次使用或不确定如何组织分镜时，读 [examples.md](references/examples.md)，含示例资料派生的合格分镜及六处错误批注。

### 执行脚本

先把 `SKILL_DIR` 设为本技能目录的绝对路径；以下命令在输入文件所在目录执行，路径也可以使用绝对路径。
没有类比时仍创建 `requests.json` 为 `{"requests":[]}`。
有类比时请求格式：

```json
{"requests":[{"id":"A_girder_length_football_field","fact":"F_girder_length","ref":"football_field","axis":"length"}]}
```

```sh
python3 "$SKILL_DIR/scripts/compute_analogy.py" --facts facts.json --requests requests.json --out analogies.json
python3 "$SKILL_DIR/scripts/resolve_text.py" --facts facts.json --shotlist draft.json --analogies analogies.json --out resolved-text.json --shotlist-out shotlist.json
python3 "$SKILL_DIR/scripts/validate_shotlist.py" --facts facts.json --shotlist shotlist.json --assets assets.json --out validation-report.json --shotlist-out shotlist.json
```

有模型元数据或运动配置时，校验命令加 `--project project.json --rig rig.json`；写实加 `--mode photoreal`。
无素材库则删去 `--assets assets.json`。校验不隐式修改输入；指定 `--shotlist-out` 才保存展开台词与倍速，不覆盖原始 `narration`。
参数或类比请求改变后重新运行三个脚本；仅改台词时重跑展开与校验。
退出码：`0` 成功，`1` 未通过/仍有占位符，`2` 文件或命令错误；必须检查 JSON 内 `passed/input_errors/skipped/manual_review`。

## 硬约束摘要

1. 只引用已确认且无冲突的参数；最高级须有同句 verified 的 claim_type=ranking 证据，具体词表与豁免见 validation-codes；拒绝需求里无出处的漂亮数字并说明原因。
2. 台词数字使用 `{{F_id}}/{{A_id}}`，因为裸数字绕开出处与参数更新机制。
3. 类比 ratio/text 只由脚本生成，因为模型心算和自由措辞不能保证比例一致。
4. 设备结构只用真实模型或实拍，因为创意画面不具备设备真实性证据。
5. 参考实拍不能说「这台/本机/我们的」，因为画面不是本设备。
6. motion 只用实际 rig 的轴和行程，因为默认行程不能代表真实设备运动能力。
7. 没有已确认焊缝精度就不安排 weld_macro，因为该镜头必须由精度参数支撑。
8. 展开后按每秒 4.5 字加 0.8 秒留量，因为占位符长度不代表实际朗读时长。
9. block 未消除不交付、最多修复两轮，因为反复猜测不能替代缺失证据的人工核实。
10. 保留人工修改、仅修问题字段，因为自动校验不授予重写用户创作或批准复核的权限。

## 交付格式

最终分镜必须符合 schema，`version=1/fps=30/width=1920/height=1080`，包含 `shots` 和计算后的 `analogies`。
镜头包含 id、kind、source、duration_s、占位台词、三类 refs、params、review；保留 `review.status=pending`，除非确实已人工批准。
报告问题保留后端 code/severity/shot，增加 field/message/fix；CLAIMS_MISSING 另列 delivery_warnings（warn），delivery_passed=false，不能以 passed=true 冒充完成交付；格式错误在 `input_errors`，缺输入检查在 `skipped`。
中文摘要应说明：通过与否、block/warn/info 数量、逐问题修法、未确认参数/缺失 rig 等人工确认项。
后端的 UNVERIFIED_FACT 和 REFERENCE_ASSET_CLAIM 为 warn；严重度保持一致不等于允许违反上述创作约束。
此技能检查引用及规则，不重新核验 PDF 原文、不检查模型几何或实际渲染画面；这些应交对应负责人验收。

## 准确度验收

执行 `python3 evals/mutation/score_mutation.py` 可离线重建变异报告；它只调用校验器，不调用模型。真实模型评测由验收方运行 `evals/run_evals.py`，grading.json 逐分句记录可溯源率，benchmark 汇总；目标 100%。该分数是保守的规则匹配，不代替原始资料真实性核验。

## 讲解配方入口（尺度 / 运动 / 结构）

配方单一来源为 [director-recipes.json](references/director-recipes.json)，每份包含观众问题、所需事实/rig/节点、镜头顺序与可执行参数、禁用条件、观察验收及失败对应返工。不要将三份全文同时塞进提示词。先运行选择器，仅阅读输出中选中的配方；需要调整创作时再查 JSON 的对应 key。

`context.json` 格式：`{"brief":"想讲清设备究竟有多大", "facts":[...], "model":{"nodes":["girder"], "rig":{"axes":{...}}}}`。facts 是事实数组，保留 source/doc/page/quote/status；model.nodes 来自实际模型，不能根据默认清单填写。应用 planner 与独立技能运行同一个选择器，选择器不调用模型、不计算类比 ratio。

```sh
python3 "$SKILL_DIR/scripts/select_director.py" --context context.json --recipe auto --target-s 15 --out director.json
```

`--recipe` 为 auto/scale/motion/structure；显式指定后缺证据不得换题假装满足。auto 按需求关键词确定要讲的主题；命中主题缺证据时退出码 1、status=needs_evidence，不悄悄换题。没有明确主题关键词时才按可用证据选一份。尺度画面只匹配主梁总长或整机高度（m/mm），跨度、起升高度、臂长或其他部件尺寸需不同几何画面，当前不能借用；ID/key/name 有冲突含义也拒绝。selected 输出是创作约束与参数建议，不是最终 shotlist：补 id/source/narration/claims/review 后仍须执行原有计算、展开与校验。sequence.duration_s 总和等于目标；15 秒用三个镜头。台词展开字数超预算就精简信息，不能加速塞满。

15 秒和已选配方的镜头预算优先于 narrative-arcs 的长片数量建议，不强制实拍/焊缝/多参数卡全部出现；用户明确必讲的缺项仍须报告。photoreal 的既有硬性验收要求不会因短片自动放宽，无法兼顾时说明冲突交人工，不擅自切模式。结构拆解只是图示，节点存在不证明受力或传动原理。

observe_and_rework 是人工观看成片的验收与修订指导，当前没有自动审美评判或审美返工闭环。保留已批准或 human_edited 的全部原始镜头字段；自动修复跳过锁定镜头并报告剩余问题，只有用户明确点名改写该镜头时才允许重新创作并回到 pending。


`render_mode=scale_film` 是应用的专用确定性三镜模板：读取 scale 配方的 `render_profiles.scale_film`（detail/hero/compare，4/5/6 权重），不改变默认配方的 3/7/5。只支持 15–30 秒、确认主梁总长与整机高度、参数化模型；auto 必须实际选中长度尺度，不能把运动/高度必讲需求改成长度。应用直接编译占位台词、claims 和程序类比，不调用语言模型；其他几何默认值披露为 assumed，仍须原 validator 校验和人工观看成片。人工镜头若不能完整保留则停止，不以模板覆盖。

多角度加长片属于独立导演指导：可复用事实、模型与校验脚本，但本技能不渲染、配音或合成。现有选择器返回的 sequence 不是多角度摄影方案；没有对应执行能力的机位、轨迹与转场写在单独导演说明中，保留实际 shotlist schema，不虚构 kind/params 或宣称应用会执行。
