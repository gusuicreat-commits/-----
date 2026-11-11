# 类比库

固定参照物用于便于理解的近似比较，不是本机测量事实。参照物数值及文案必须由脚本产生。

| ref | 参照物 | size/unit | axis | 依据 |
|---|---|---|---|---|
| football_field | 标准足球场 | 105 m | length | 国际足联推荐比赛场地长105米 |
| building_floor | 层住宅楼 | 3.0 m | height | 住宅层高约3米 |
| boeing747 | 个波音747的翼展 | 64.4 m | length | 波音747-400翼展约64.4米 |
| bus | 辆12米长的公交车 | 12 m | length | 城市公交车长约12米 |
| person | 个成年人 | 1.75 m | height | 成年人身高约1.75米 |
| car | 辆小轿车 | 1.5 t | mass | 家用轿车约1.5吨 |
| elephant | 头成年非洲象 | 6 t | mass | 成年非洲象约6吨 |
| hair | 根头发丝 | 0.07 mm | thickness | 头发丝直径约0.07毫米 |

## 换算与取整

支持参数单位 m、mm、t；m 与 mm 按 1m=1000mm 转换，t 只能与质量参照物比较。其他单位拒绝，不自动猜单位。
参数值必须为有限非负数；工作流仅接受 verified/confirmed。ratio=换算到参照物单位的 value/size。
存储 ratio 使用 round(ratio,3)；文案使用未取整比值判断，不能从存储的三位小数倒推文案。
round 遵循运行环境标准的就近偶数取整，不能替换成传统四舍五入。

## 比较词与容差

N 为展开文案中的倍数，ratio 始终用未取整真实比值。模型不得自写比较词，必须直接使用 compute_analogy 输出。

| 比较词 | 合法条件 |
|---|---|
| 约 / 大约 / 大约只有 | abs(N-ratio)/ratio ≤ 10% |
| 接近 / 相当于 / 差不多 | abs(N-ratio)/ratio ≤ 5% |
| 超过 | ratio > N，等于不允许 |
| 几乎 | N > ratio 且 abs(N-ratio)/ratio ≤ 5% |
| 还不到 | ratio < N |

ratio=0 时只允许「约0/相当于0」等零误差表达；「还不到一根」仍按严格小于判断。浮点比较容差为 1e-12。

## 文案模板

- football_field / boeing747：仅当 abs(1-ratio)/ratio ≤5% 才生成原来的一倍比喻「差不多就是一个标准足球场那么长」「差不多和波音747的翼展一样宽」。
- building_floor：「相当于{N}层楼那么高」。
- car / elephant：「相当于{N}{参照物名称}的重量」。
- hair 小于1：「还不到一根头发丝粗」；否则「大约只有{N}根头发丝并排那么宽」。
- 其他情况：「相当于{N}{参照物名称}」。
- 首选旧版整数/一位小数；超出相应容差就使用12位有效数字，不再强行凑整。
- 审计也识别 `约/接近/超过/几乎 + N + 参照物名称`，但这是校验兼容输入，模型仍不得自行挑选措辞。
- 比较词、倍数和参照物后缀必须完整匹配模板；拒绝夹带「不」「至少」或其他更强断言。
- 输出 ref_size、ref_unit、ref_size_m（质量为 null）、basis、formula，全部保留以便渲染及溯源。ratio、参照尺寸及文案都会重新计算核对，异常报 ANALOGY_ROUNDING。

## 请求示例

```json
{"requests":[{"fact":"F_overall_height","ref":"building_floor","axis":"height"},{"fact":"F_weld_tolerance","ref":"hair","axis":"thickness"}]}
```

可省略 id，脚本生成 A_{fact去掉F_}_{ref}。同 ID 不允许重复；不能把用户输入的 ratio/text 原样当计算结果。
长度参照只选 length，高度参照只选 height；不要用 football_field/height 或 hair/length。
取整比较不是设备技术指标，不把“约”等措辞删掉来制造精确结论。
