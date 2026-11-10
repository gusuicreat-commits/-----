---
name: industrial-explainer-storyboard
description: 该技能依据已确认参数表，为起重机、门机、桥机和工业装备编写科普视频、宣传片、展会视频及投标视频的分镜、脚本与台词，程序计算类比并执行参数核对、真实性校验，交付可接入渲染流水线的 shotlist.json。用户要求规划、修改、审查工业视频分镜或核验台词数字、素材来源时应主动使用；仅处理分镜与校验，不执行渲染、配音或合成。
---

# 工业装备分镜与真实性校验

## 适用范围与输入输出

将需求与已确认参数转为可追溯分镜；支持首次规划、局部修改和现有 shotlist 审查。
脚本仅需 Python ≥3.11 标准库，可复制整个技能目录独立运行，不依赖项目后端。

必需输入：`facts.json`（顶层 `facts` 数组）和需求（用途、目标时长、语气、必讲内容）。
参数包含 `id/name/value/unit/source:{doc,page,quote}/status`；只使用 `verified/confirmed`。
`extracted` 虽不是交付契约内的标准状态，也按未确认处理，不能引用。
可选输入：`assets.json`、已有 `shotlist.json`、`project.json`（模型元数据和 render_mode）、`rig.json`（真实运动轴、行程、速度参数引用）。
缺少素材库视为空库；缺少模型元数据时 title/outro/data_card 用 `source=graphic`；不凭空声称已有模型。
有运动需求但缺 rig 时列人工确认项，不猜行程；写实需求不得为了通过而删除所需运动镜头。
输出：`shotlist.json`、`validation-report.json`、中文校验摘要；附 `resolved-text.json` 便于人工听读。

## 可复制的步骤清单

- [ ] 1. 读取需求和输入。列出可用参数 ID、出处页码、未确认参数及需求缺失项；只引用 verified/confirmed，保留人工修改的台词与镜头 id。
- [ ] 2. 读 [narrative-arcs.md](references/narrative-arcs.md)，选择科普、展会或投标叙事弧与时长配比；默认 45 秒、6–9 镜头，全片 30–60 秒。
- [ ] 3. 读 [shot-kinds.md](references/shot-kinds.md) 和 [narration-rules.md](references/narration-rules.md)，按 [shotlist.schema.json](scripts/shotlist.schema.json) 起草 `draft.json`。需要类比时读 [analogy-library.md](references/analogy-library.md)，只登记请求，不心算 ratio/text。
- [ ] 4. 执行下面的类比计算与台词展开命令。检查展开后的语句、重复用词和时长；按实际字数调整台词或分配时长，不能用未展开占位符长度估计。
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

1. 只引用已确认参数且保留文档页码，因为每个设备数字必须可追溯。
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
报告问题保留后端 code/severity/shot，增加 field/message/fix；格式错误在 `input_errors`，缺输入检查在 `skipped`。
中文摘要应说明：通过与否、block/warn/info 数量、逐问题修法、未确认参数/缺失 rig 等人工确认项。
后端的 UNVERIFIED_FACT 和 REFERENCE_ASSET_CLAIM 为 warn；严重度保持一致不等于允许违反上述创作约束。
此技能检查引用及规则，不重新核验 PDF 原文、不检查模型几何或实际渲染画面；这些应交对应负责人验收。
