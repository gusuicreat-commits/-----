> 历史来源记录：以下为原 T21c worktree 的交付文字与当时验证，不是 2026-11-10 接续验收。当前修补、合同及验证见 `docs/T21-接续实施.md`。

# T21c 交付说明

已补齐原文数值/单位核对、类比容差和逐句陈述审计。后端与独立技能保持规则一致；旧分镜缺 claims 的后端诊断为 info，技能交付单独列 warn。文字事实支持 qualitative 类型、带出处的字符串 value，并贯通抽取、手工修订及台词展开。

## 实际验证

- 后端全量：`cd backend && UV_CACHE_DIR=/private/tmp/kepu-uv-cache uv run pytest -q`：1256 passed，1 skipped，6 warnings，16.19 秒。缓存位置调整仅因默认缓存目录不在沙箱可写范围。
- 相关回归：同环境运行 `uv run pytest -q tests/test_accuracy.py tests/test_validator.py tests/test_skill_parity.py tests/test_storyboard_evals.py tests/test_planner.py tests/test_facts.py tests/test_claim_rules.py --tb=short`：818 passed。
- 变异评测：`python3 skills/industrial-explainer-storyboard/evals/mutation/score_mutation.py`：180/180 命中，正确样本误报0/24。
- `git diff --check`：通过。没有调用真实模型或联网服务；没有安装依赖、修改合同/依赖清单或提交 git。

## 召回率表

| 错误类别 | 命中/样本 | 召回率 |
|---|---:|---:|
| 裸数字 | 12/12 | 100.0% |
| 数值改一位 | 12/12 | 100.0% |
| 替换单位 | 12/12 | 100.0% |
| 未确认、驳回或不存在参数 | 12/12 | 100.0% |
| 冲突参数 | 12/12 | 100.0% |
| 参考实拍冒认本机 | 12/12 | 100.0% |
| 创意画面出现设备 | 12/12 | 100.0% |
| 无证据最高级 | 12/12 | 100.0% |
| 绝对承诺 | 12/12 | 100.0% |
| 类比比较词错误 | 12/12 | 100.0% |
| 类比参数错误 | 12/12 | 100.0% |
| 不存在素材 | 12/12 | 100.0% |
| 不存在运动轴 | 12/12 | 100.0% |
| 超速但标成真实速度 | 12/12 | 100.0% |
| 具体陈述无支撑 | 12/12 | 100.0% |

四份基线及20个人工易误报正确样本全部通过。每类门槛≥95%、总召回≥99%、误报0；本轮每类与总计均100%。召回统计预期问题码的 block/warn，不用无关警告充数；正常且正确标注的倍速演示不是超速错误。

## 已知不足与合同扩展

- 跳过项为需要实际渲染的 slow 集成测试；本任务没有前端或渲染器改动，未启动浏览器。
- 真实模型端到端评测未运行。run_evals.py 已输出逐分句 traceability、traceability_rate、traceability_passed；benchmark.md/json 与 HTML 报告已增加可溯源率。验收方运行真实模型后才能判断其是否达到100%。
- 可溯源率是保守的规则对齐：数字、参数名称与文字事实必须有依据；无法对齐的改写不计支持。专名词表和正则不能穷举所有实体，素材条目存在也不能证明实际图像内容。离线100%不代表开放域语义真实性或生产验收。
- 按本轮规格对合同§3增加可选 type=qualitative（value 可为文字、unit为空），对§6增加可选 claims；这是本轮要求的兼容扩展，CONTRACTS.md 未修改。引用原句仍需人工/PDF原文复核，QUOTE_MISMATCH 不自动修改事实。
- 六份新回放沿用既有人工编写的测试响应，只迁移新提示、schema及问题序列的输入哈希；各文件 note 记录原文件名，不是真实模型新生成结果。

## 改动文件清单

- `backend/app/agent/accuracy_rules.py`
- `backend/app/agent/analogy.py`
- `backend/app/agent/claim_rules.py`
- `backend/app/agent/planner.py`
- `backend/app/agent/text.py`
- `backend/app/agent/validator.py`
- `backend/app/ingest/facts.py`
- `backend/tests/cassettes/extract_facts_daeba9072b4df4eb.json`
- `backend/tests/cassettes/plan_3cc9e4f9a9e3f36e.json`
- `backend/tests/cassettes/plan_d229cf1fce152623.json`
- `backend/tests/cassettes/repair_1669a03262587121.json`
- `backend/tests/cassettes/repair_7efe55a1539764ae.json`
- `backend/tests/cassettes/revise_219af0aefd7fa370.json`
- `backend/tests/test_accuracy.py`
- `backend/tests/test_planner.py`
- `backend/tests/test_skill_parity.py`
- `backend/tests/test_storyboard_evals.py`
- `backend/tests/test_validator.py`
- `skills/industrial-explainer-storyboard/SKILL.md`
- `skills/industrial-explainer-storyboard/evals/eval_support.py`
- `skills/industrial-explainer-storyboard/evals/mutation/baselines/bridge_crane.json`
- `skills/industrial-explainer-storyboard/evals/mutation/baselines/english_facts.json`
- `skills/industrial-explainer-storyboard/evals/mutation/baselines/reference_only.json`
- `skills/industrial-explainer-storyboard/evals/mutation/baselines/standard.json`
- `skills/industrial-explainer-storyboard/evals/mutation/delivery.md`
- `skills/industrial-explainer-storyboard/evals/mutation/mutate.py`
- `skills/industrial-explainer-storyboard/evals/mutation/report.md`
- `skills/industrial-explainer-storyboard/evals/mutation/score_mutation.py`
- `skills/industrial-explainer-storyboard/evals/report.py`
- `skills/industrial-explainer-storyboard/evals/run_evals.py`
- `skills/industrial-explainer-storyboard/references/analogy-library.md`
- `skills/industrial-explainer-storyboard/references/claim-rules.json`
- `skills/industrial-explainer-storyboard/references/validation-codes.md`
- `skills/industrial-explainer-storyboard/scripts/accuracy_rules.py`
- `skills/industrial-explainer-storyboard/scripts/claim_rules.py`
- `skills/industrial-explainer-storyboard/scripts/compute_analogy.py`
- `skills/industrial-explainer-storyboard/scripts/facts.schema.json`
- `skills/industrial-explainer-storyboard/scripts/resolve_text.py`
- `skills/industrial-explainer-storyboard/scripts/shotlist.schema.json`
- `skills/industrial-explainer-storyboard/scripts/validate_shotlist.py`
