# T26 独立 Skill 进度审计

核对日期：2026-11-11。结论：独立 Skill 的分镜、事实约束与离线校验工具已经可用；真实模型的完整对照评测还没完成。应用另有一条已本地验收的三镜尺度渲染路径。本次增加多角度导演指导，不等于应用已经能自动生成加长版，也不以一个百分比混合这三种进度。

## 已完成

| 交付 | 实际证据与范围 |
|---|---|
| 独立分镜 Skill | `skills/industrial-explainer-storyboard/` 包含入口、事实/分镜 schema、类比计算、台词展开和真实性校验；脚本仅用 Python 标准库，不依赖后端。支持首次规划、修改、保留人工锁定镜头和既有分镜核查；不负责渲染、配音、合成。 |
| 规则与离线回归 | T21 接续记录：后端 1271 passed、1 skipped；故障注入报告：15 类共 180/180 命中、正确样本 0/24 误报。这是固定合成故障族的规则覆盖，不是模型准确率或开放域事实真实性。 |
| 讲解配方 | scale / motion / structure 共用配方 JSON 与选择器。T24 在实际 GLB 的122个具名节点证据下复验 auto 选中 scale；没有重新测量网格，也不是制造商实物核验。 |
| 应用 T25 尺度短片 | 真实 HTTP plan 入口跑完15秒、1080p、30fps、450帧成片，使用 Blender 与 Edge TTS；媒体检查和本地 UI 验收有记录。当前源码仍限制 scale_film 为 detail/hero/compare 三镜、15–30秒。 |
| 本次导演指导 | 新增 `references/cinematography.md`，含镜头信息功能、景别、轴线/运动方向、真实比例、结构示意边界、转场选择及先关键帧后整片。36秒八镜只是本次独立导演示例，不是全局硬规则。 |

## 可用但未充分验证

- Skill 能执行计算、展开、校验，并有 T24 独立正向试跑，但原 A/B fixture 缺实际模型节点：程序的 delivery_passed 不能覆盖该缺口。B 把104改80后比例/台词更新，不代表模型同步变成80米。
- 当前 claims 对齐、generic 识别等仍为保守启发式；来源摘录匹配不证明原始资料为真。模型几何、投影与画面必须单独验收。
- T25 有本地实际成片，并有132米合成参数静帧/配音回归；132米不是第二支完整片。T25 验收使用 LLM replay，视觉模型 QA 没有匹配录制，保留 VISUAL_QA 警告；不能称真实模型自动质检已通过。
- 本次多角度指导已完成文字与脚本兼容性检查，尚无新的模型生成对照评测或用户盲评证明其审美收益。T26 成片、关键帧和观看结论由本轮主控另行记录，本审计不代替它们。

## 待做

- 补齐真实模型 with-skill / without-skill 对照、每场景多次生成、逐分句可溯源评分、文采盲评及完整触发评测。最近保留的原评测审计是 T21b：12场景×2组×3次共72次生成，仅2次完成，70次触发 Claude 五小时限额；无有效盲评配对，触发仅完成1/40。不能据此判断当前 Skill 的收益或 T21c 实际准确率。
- 若要求在应用中一键制作30–45秒多角度短片，还需单独实现该能力，并验证模型/镜头/转场/音画与输入变更失效机制。当前三镜模板不能通过修改文档就视作完成；motion、structure 也尚无与 T25 同等完整电影化渲染验收。
- 自动审美搜索、自动观看返工和部署均没有本次完成证据。此处只陈述当前项目内交付，未据此声称已在所有会话全局安装。

## 本次实际修改与验证

仅修改 Skill 入口并新增摄影参考及本文档；保留全部原有工作区修改，未提交 Git。没有修改 director-recipes.json、执行脚本、应用源码或 T25 成片。未启动外部模型、配音或渲染。

实际命令的完整绝对路径、返回码和 stdout/stderr 见 [commands.json](../outputs/T26-multiangle/skill-check/commands.json)，结果与保护文件哈希见 [result.json](../outputs/T26-multiangle/skill-check/result.json)。

| 本次检查 | 结果 |
|---|---|
| `backend/.venv/bin/python /Users/mac/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/industrial-explainer-storyboard` | 退出0，Skill is valid。仅证明格式检查通过。 |
| `select_director.py --context outputs/T24-scale-film/skill-forward/post-fix/context.json --recipe auto --target-s 36 --out outputs/T26-multiangle/skill-check/director-36-selector.json` | 退出0，scale，仍为三镜7.2/16.8/12秒；实证现有选择器不会产生八镜摄影方案。不是对36秒应用渲染的测试。 |
| `compute_analogy.py` → `resolve_text.py` → `validate_shotlist.py` | 使用原T24 A输入，输出写入本轮 skill-check；三条均退出0，0 block、1时长warn、1待人工复核info。原 fixture 的缺模型证据问题仍在，不能称本轮多角度分镜完整验收。 |
| `git diff --check -- skills/industrial-explainer-storyboard/SKILL.md` | 退出0。 |

本次没有改运行逻辑，因此未重跑历史全量后端或昂贵真实模型评测。历史结果按历史来源列示。

## 核对来源

- [T21接续实施](T21-接续实施.md)、[准确度故障注入报告](../skills/industrial-explainer-storyboard/evals/mutation/report.md)。
- [原真实评测审计 JSON](acceptance/2026-11-10/previous-evaluation-audit.json)及[主控说明](acceptance/2026-11-10/README.md)。这是保留的历史审计，未伪称本轮重新访问限额服务后得到新评测。
- [T24主控验收](T24-主控验收.md)、[原A/B证据缺口](../outputs/T24-scale-film/skill-forward/comparison.json)、[修复后实际节点证据](../outputs/T24-scale-film/skill-forward/post-fix.md)。
- [T25主控验收](T25-主控验收.md)、[实际媒体结果](../outputs/T25-scale-film/acceptance/final-check.json)；当前边界核对源码 `backend/app/agent/scale_film.py` 的15–30秒检查及 `backend/app/media/scale_film.py` 的三镜与角色检查。

## T27 与声音反馈的后续补充（2026-11-11）

以上为 T26 首轮审计，不是后续应用开发状态。六步应用已在 `/create.html` 接入独立引擎/内容选择、导演方案预览、定向修改及版本绑定制作，真实验证范围见 `T27-主控验收.md`。它加载多角度摄影及 copywriting 指导，30秒以上按6–9镜规划；不等于原三镜选择器具备T26的独立近景轨迹。

针对“旁白机械、台词死板”，copywriting.md 增加整片连续讲解、避免逐镜报幕、事实与观察分句、声音留白及试听边界。新流程配音改为 Yunxi 正常语速；T26独立成片增加四段旁白试听版，主控实际复跑媒体校验，Astra核对台词与镜头时序。新版保留全部原视频流，23.784秒旁白与12.216秒段间/首尾留白；未人工听音，不声称自然度或Skill收益已通过盲评。

真实Claude工作流曾在两轮自动修复后仍误把普通提问挂到参数出处；主控通过明确修改指令纠正，不能据此称全自动分镜验证通过。首次完整制作又按实测语音时长正确停止，主控缩短两句并在40秒总长内重新分配镜头后继续。校验规则未放宽、没有加速裁音。
