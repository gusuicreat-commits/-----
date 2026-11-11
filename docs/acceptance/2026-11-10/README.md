# Aster 接续与独立验收记录

日期：2026-11-10。当前 Aster 会话统筹、审查和独立验收，具体实现由两个 GPT-6.1 Sol（high）子 Agent 执行。工作目录为主项目，原 worktree 仅作为只读输入；本轮未提交 Git。

## 准确度部分：离线验收通过

已集成 T21b/T21c 的规则、文采指导、12 场景评测工具，并补齐 CONTRACTS。主控重点审查了 support 与陈述对齐、可溯源率分母、generic 自报证据、故障注入样本去重以及离线回放来源。

主控自己运行：

- `cd backend && .venv/bin/python -m pytest -q`：1271 passed，1 skipped，6 warnings，18.86 秒。完整输出见 `aster-backend-pytest.txt`；跳过为原有 slow 渲染集成。
- `python3 skills/industrial-explainer-storyboard/evals/mutation/score_mutation.py`：180/180，正确样本误报 0/24。固定合成故障族的覆盖率，不是开放域准确率。
- 独立构造的 6 个绕过/正常对照用例：全部符合预期，详见 `aster-adversarial-checks.json`。无关事实、无关素材、错误量纲和具体陈述伪装 generic 均被拦截。
- `git diff --check` 通过。

文字同义改写的保守对齐仍可能需人工核对；generic 词表无法穷举所有事实。未取证的常识不会仅因作者自标 generic 就算有来源。迁移的 cassette 明确是旧人工响应适配新输入哈希，不是真实模型新样本。

## 原真实模型评测：未完成

已读取原评测 benchmark 与模型原始输出：12 场景 × 2 组 × 3 次 = 72 次生成，仅 2 次完成、70 次遇 Claude 5-hour limit；无有效文采盲评配对。触发评测日志仅完成 1/40。详情及原文件路径在 `previous-evaluation-audit.json`。

这些历史结果属于 T21b，不能证明当前技能的真实模型收益、T21c 可溯源率或文采提升。本轮未更改应用内模型配置或把实施模型与产品运行模型混同。

## 画面部分：原门槛复验与用户决定

主控已拒绝一轮虽通过数值门槛但阴影死黑、天空灰暗、地面棋盘感强的候选，最终候选移除全局压暗曲线、改善蓝天、地面与阴影，并固定整镜厂房可见集合。

主控独立执行硬件 Playwright（Apple M4）：9 passed、1 skipped、1 failed，15.3秒。跳过的是已由实施 Agent 在相同最终代码上跑过的全片；唯一失败为朝阳/背阳 sRGB 比 1.449805 < 3。同图同几何 mask 的线性亮度比为 2.448393，也未达到3，不能仅换口径宣布通过。完整独立结果见 `aster-hardware-look.txt`。

其他指标：原逐镜 mask 差最小0.042587>0.04；投影/同位置受光地面比0.416848≤0.55；天空B−R=131≥25。该次复验保留了原全部阈值。Node测试由主控复跑31/31。geometry18/18由实施Agent运行，主控未重复；后端model3d测试已包含在主控全套复跑中。

最终候选全片由实施Agent执行：50秒、1500帧、总157.625秒；主控以ffprobe独立确认1920×1080、30fps、1500帧、50.000000秒，并亲自查看title/orbit/exploded截图与Blender参考。视频：`../../../web/test-results/T22-final/standard-full.mp4`。该片是渲染测试夹具演示，不是业务真实资料端到端生成验收。

原门槛复验结论：准确度离线通过；自然光候选未通过原3:1门槛。上述失败记录保留，不追溯改写为通过。

2026-11-10 用户明确选择：“保留自然光候选，3∶1改为诊断值，按画面观感验收（推荐）”。因此替代原 `/Users/mac/worktrees/kepu-tasks/t22c-light.md` 中的3:1硬门槛：朝背阳gamma/linear比继续记录，用于观感审阅；仍检查几何mask样本量、硬件GPU和读数有效性。原mask差>0.04、投影比≤0.55、蓝天、4:1照度校准、确定性、回退与性能要求继续适用。

这次决策只修改测试口径与文档，保留最终自然光渲染代码和候选视频。按新口径的独立复验结果如下。真实模型评测缺口仍独立保留，不能称业务端到端全部完成。


### 用户确认后的最终独立验收

Aster 重新执行 `KEPU_CHROMIUM_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' npx playwright test -c tests/look.config.mjs --output=test-results/aster-look-approved`：**10 passed、1 skipped，14.7秒，退出码0**。完整输出 `aster-hardware-approved.txt`。跳过仅为本轮无需重复的50秒整片测试；此前同一运行代码的整片验证通过，产物保留。朝背阳仍记录1.449805（gamma）和2.448393（linear），不是达到3。

主控再次检查最终环绕画面：橙色设备、蓝天、灰色分块地面与可辨的柔和阴影符合本轮自然光方向，文字可读。结合前轮逐镜检查和本轮确定性/建筑/回退/色彩/性能检查，**T22 自然光版本按用户确认口径验收通过**。准确度离线验收仍通过；真实模型生成、文采收益和触发评测仍未完成，不包含在本次通过结论内。测试与记录已更新，运行代码未改；Git未提交。
