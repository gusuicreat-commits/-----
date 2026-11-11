# 模块间契约（所有任务必须遵守）

本文件是各模块共同依赖的数据格式与接口约定。改动需先改本文件。

## 0. 总体

- 产品：**基于真实工业资料约束的超大起重机科普视频智能体**。输入创意需求 + 技术文档（PDF）+ 三维模型（STEP 或无）+ 实拍素材，输出 30–60 秒科普视频（1920×1080，30fps）+ 溯源报告。
- 核心原则：设备结构只来自真实模型/参数化模型/实拍；数字只来自参数表（带页码出处）；类比由程序计算；AI 创意镜头不得出现设备本体；每个镜头标注来源；人工可复核。
- 语言：界面、日志、报告、字幕全部中文。
- 单位：长度米（m），坐标系 **Y 轴向上，X 轴沿主梁（小车运行方向），Z 轴沿轨道（大车运行方向）**，原点在两轨道中心连线中点的地面。

## 1. 目录

```
backend/                 Python 3.11+，uv 管理（backend/pyproject.toml）
  app/main.py            FastAPI 入口：python -m app.main 或 uvicorn app.main:app，默认端口 8031
  app/storage.py         项目目录读写
  app/llm.py             大模型适配层（Opus 5.5）
  app/ingest/            文档解析、参数提取与核验
  app/model3d/           参数化模型、STEP 导入、运动配置
  app/agent/             规划、类比、校验、编排
  app/media/             配音、合成
  tests/                 pytest
web/                     Node 20+（web/package.json）
  player/                时间线播放器（预览与渲染共用）
  app/                   操作界面
  render/render.mjs      逐帧渲染
  tests/                 Playwright
samples/                 示例资料（示例参数表 PDF 生成脚本、示例素材及其许可证）
projects/<pid>/          运行时数据（gitignore）
```

## 2. 项目目录 `projects/<pid>/`

六步创建入口 `/create.html` 的扩展契约见 [T27 工作流接口](T27-工作流接口.md)：`production_engine` 与 `director_recipe` 分开保存；`workflow.json`/`preview-timeline.json` 记录方案预览，`deliverables.json` 将成片、报告和项目包绑定到制作版本及文件摘要。模型输入变化时重新构建参数化 GLB/rig，禁止旧几何通过新预览；服务中断后允许重新预览恢复。旧高级工作室继续适用下面的数据约定。

```
project.json        {id, name, brief, created_at, model:{kind:"step"|"parametric", glb, step?, dims_check?}}
docs/<file>.pdf     上传的原始文档
facts.json          参数表（见 §3）
assets.json         素材库（见 §4）  assets/<file>
model/crane.glb     三维模型；model/rig.json 运动配置（见 §5）
shotlist.json       分镜（见 §6）
issues.json         校验问题（见 §7）
tts/<shot>.mp3, tts/<shot>.words.json
timeline.json       最终时间线（见 §8）
renders/video_noaudio.mp4, renders/final.mp4, renders/frames_qa/<shot>.png
report.json, report.html   溯源报告
events.jsonl        工具调用事件流（见 §9）
llm/<n>_<task>.json 每次大模型调用的输入摘要与输出（便于溯源）
```

## 3. 参数表 facts.json

```json
{"facts":[{
  "id":"F_girder_length",          // F_ 开头，小写下划线
  "name":"主梁长度", "value":104, "unit":"m",
  "source":{"doc":"示例技术参数表.pdf","page":2,"quote":"主梁总长 104 m"},
  "status":"verified"               // verified | needs_review | confirmed | rejected
}]}
```
- `verified`：程序核验通过（quote 在该页原文中逐字出现，数值和单位经全半角、千分位及单位别名规范化后与 quote 中相邻量值匹配）。这仅验证抽取一致性，不证明原始资料的真实性。
- `needs_review`：核验未通过或模型不确定，需人工确认。`confirmed`：人工确认。`rejected`：人工否决，不可引用。
- 可引用状态：verified、confirmed。引用时仍检查摘录一致性；人工修改数值而保留旧摘录会报 `QUOTE_MISMATCH`，需核对原文。
- 可选 `type: "quantitative"|"qualitative"`；默认数值。qualitative 的 `value` 为原文文字、`unit` 必须为空，支持用途、结构等非数字陈述。不可用数值参数支撑无关文字结论。
- 可选 `claim_type: "ranking"`：有明确排名/首台认证依据的事实；最高级只能由同句占位引用的 verified ranking 事实且摘录包含对应宣称放行。该标签不等于第三方认证真实性证明。
- verified/confirmed 事实同 id、key 或 name 且量值不同（等值单位换算除外）为冲突，引用任一条即 block；交人工裁定，不自动挑选。
- 规范 id（规划与模型生成会用到，提取时尽量对齐）：
  `F_rated_load`(t) `F_girder_length`(m) `F_overall_height`(m) `F_span`(m) `F_lift_height`(m)
  `F_hoist_speed`(m/min) `F_trolley_speed`(m/min) `F_gantry_speed`(m/min) `F_leg_height`(m) `F_girder_height`(m)
  `F_weld_tolerance`(mm) `F_total_mass`(t) `F_wheel_count`(个)

## 4. 素材库 assets.json

```json
{"assets":[{
  "id":"IMG_01", "kind":"image"|"video", "file":"assets/port.jpg",
  "provenance":"own"|"reference",   // own=本设备实拍；reference=参考实拍（非本设备）
  "title":"", "tags":["门式起重机","焊接"], "credit":"作者 / 许可证 / 来源链接（reference 必填）",
  "duration_s": null
}]}
```

## 5. 三维模型与运动配置

GLB 节点命名（参数化模型必须全部提供；STEP 导入时尽量映射，缺失则只做整体镜头）：
`crane`(根) `girder` `leg_left` `leg_right` `trolley` `hoist_hook` `rope` `rail_left` `rail_right` `cab`
`trolley` 是 `crane` 的子节点；`hoist_hook` 与 `rope` 是 `trolley` 的子节点。

rig.json：
```json
{"axes":{
  "gantry":  {"node":"crane","axis":"z","range_m":[-40,40],"speed_fact":"F_gantry_speed"},
  "trolley": {"node":"trolley","axis":"x","range_m":[-44,44],"speed_fact":"F_trolley_speed"},
  "hoist":   {"node":"hoist_hook","axis":"y","range_m":[2,47],"speed_fact":"F_hoist_speed"}
 },
 "bbox_m":{"x":104,"y":51,"z":20},
 "derived_from":["F_girder_length","F_overall_height","F_span","F_lift_height"]
}
```
`range_m` 为节点相对其初始位置在该轴上的绝对坐标范围；`hoist` 的 y 指吊钩离地高度。

## 6. 分镜 shotlist.json

```json
{"version":1,"title":"","fps":30,"width":1920,"height":1080,
 "shots":[{
  "id":"S1",
  "kind":"title|model_orbit|analogy|motion|exploded|data_card|real_media|ai_broll|weld_macro|outro",
  "source":"model|real|ai|graphic",
  "duration_s":6.0,
  "narration":"它的主梁长{{F_girder_length}}，{{A_girder_length_football}}。",
  "fact_refs":["F_girder_length"], "analogy_refs":["A_girder_length_football"], "asset_refs":[],
  "claims":[{"text":"它的主梁长{{F_girder_length}}", "support":"F_girder_length"}, {"text":"{{A_girder_length_football}}", "support":"F_girder_length"}],
  "params":{},
  "review":{"status":"pending","note":""}
 }],
 "analogies":[{"id":"A_girder_length_football","fact":"F_girder_length","ref":"football_field","axis":"length",
               "ratio":0.99,"text":"差不多是一个标准足球场的长度"}]
}
```
- 台词中的数字一律用占位：`{{F_xxx}}` 解析为「数值+单位」（如「104米」），`{{A_xxx}}` 解析为类比 text。
- `analogies[].ratio/text` 由 `app/agent/analogy.py` 计算并写入，大模型只选 `ref` 和 `axis`。
- 每镜可选 `claims: [{text, support}]`，support 为事实 ID、素材 ID 或 `"generic"`。每个台词分句均需登记；事实/素材必须存在且语句可与其内容对齐，存在一个 ID 本身不能证明任意陈述。generic 不得夹带型号、客户、年份、排名等具体事实；词表不能穷尽全部实体。
- 旧数据缺 claims 报 info `CLAIMS_MISSING`，技能交付按 warn；这不是准确度验收通过。`human_edited: true` 或 review.status=approved 的台词修改时逐字保留。
- 类比真实比值与措辞容差：约≤10%；接近/相当于≤5%；超过必须真实比值大于措辞数值；几乎要求措辞数值略大于真实值且偏差≤5%。由 compute 生成，`ratio/text/ref_size` 被篡改报 block。
- 各 kind 的 params：
  - `title`/`outro`：`{"title":"","subtitle":""}`
  - `model_orbit`：`{"from_deg":-30,"to_deg":30,"elevation_deg":15,"distance":1.6,"highlight":["girder"]}`（distance 为相对包围盒对角线的倍数）
  - `analogy`：`{"analogy":"A_xxx"}` —— 播放器按真实比例并排绘制设备与参照物
  - `motion`：`{"axis":"trolley|hoist|gantry","from_m":-30,"to_m":30}` —— 校验器写入 `speedup`（倍速，≥1），播放器显示「×N 倍速」
  - `exploded`：`{"parts":["girder","leg_left","leg_right","trolley"],"spread_m":12}`
  - `data_card`：`{"facts":["F_rated_load","F_span"]}` —— 每个数值下方显示「来源：文档名 第N页」
  - `real_media`：`{"asset":"IMG_01","effect":"kenburns|none","caption":""}`
  - `ai_broll`：`{"recipe":"sunrise_port|night_factory|blueprint_grid|particles","palette":"warm|cool|steel","prompt":"画面描述"}` —— 不得出现设备本体
  - `weld_macro`：`{"fact":"F_weld_tolerance","analogy":"A_xxx"}`
- 来源角标文字：model→「三维模型渲染 · 依据STEP」或「三维模型渲染 · 参数化重建」；real/own→「实拍」；real/reference→「参考实拍 · 非本机」；ai→「AI 创意画面」；graphic→「信息图」。

## 7. 校验问题 issues.json

```json
{"issues":[{"id":"I1","shot":"S3","severity":"block|warn|info","code":"UNSOURCED_NUMBER",
            "message":"台词出现无出处的数字「三十米」","hint":"改用 {{F_xxx}} 占位或删除"}]}
```
校验永不整体失败：只标出问题条目。`block` 级问题未处理时，编排在 validate 后暂停等人工（可强制继续，报告中注明）。

新增规则：`EXAGGERATION`、`FACT_CONFLICT`、`QUOTE_MISMATCH`、`ANALOGY_ROUNDING`、`UNSUPPORTED_CLAIM` 为 block；`ABSOLUTE_CLAIM`、`UNIT_SUSPECT`、`QUOTE_ABSENT` 为 warn；`CLAIMS_MISSING` 为 info。校验错误 `CHECK_ERROR` 不代表通过，评测不得计为准确。

离线评测可溯源率独立按台词分句计分母，不能以作者自报 claims 数作分母；需证据原文对齐及无相关错误才计支撑。generic 仅对保守识别的提问、阅读引导、明确类比计通过，未取证常识仍保留未支撑。此指标是保守规则覆盖，不能作为开放域语义真实性证明。

## 8. 时间线 timeline.json（播放器唯一输入）

```json
{"fps":30,"width":1920,"height":1080,"duration_s":48.2,
 "model":{"glb":"/files/<pid>/model/crane.glb","kind":"parametric","rig":{...rig.json...}},
 "facts":{"F_span":{"name":"跨度","value":88,"unit":"m","source":{"doc":"..","page":2}}},
 "shots":[{"id":"S1","kind":"title","source":"graphic","badge":"信息图","start":0,"end":5.2,"params":{},
           "text_overlays":[{"text":"104米","fact":"F_girder_length"}]}],
 "analogies":{"A_x":{"fact":"F_girder_length","ref":"football_field","axis":"length","ratio":0.99,"text":"…","ref_size_m":105}},
 "assets":{"IMG_01":{"url":"/files/<pid>/assets/port.jpg","kind":"image","provenance":"reference","credit":"…"}},
 "captions":[{"start":0.3,"end":2.1,"text":"这是一台……"}],
 "audio":"/files/<pid>/renders/narration.wav"
}
```
URL 以 `/files/<pid>/` 开头时由后端静态服务 `projects/<pid>/`；播放器也接受相对/绝对 URL。

## 9. 事件流 events.jsonl（界面「智能体正在调用的工具」）

每行：`{"ts":"ISO8601","run":"r1","stage":"ingest|model|plan|validate|tts|render|compose|qa|report","tool":"pdf.extract","status":"start|ok|warn|error","summary":"中文一句话","detail":{}}`
工具名约定：`pdf.extract` `llm.opus.extract_facts` `verify.facts` `model.parametric` `model.step_to_glb` `model.dims_check` `llm.opus.plan` `analogy.compute` `validate.shotlist` `tts.edge` `render.player` `ffmpeg.compose` `llm.opus.visual_qa` `report.provenance`

## 10. 播放器接口（web/player/index.html）

- `index.html?timeline=<url>&mode=render|preview`
- 暴露 `window.__player = { ready: Promise<void>, duration: number, seek(t: number): Promise<void> }`
- render 模式：不得有任何依赖真实时间的动画；画面只由 `seek(t)` 决定（确定性）。preview 模式：带音频播放、可拖动。
- 字幕、来源角标、数据卡片、倍速提示都由播放器绘制（DOM 叠加在 WebGL 画布上）。

## 11. 后端 HTTP API（前缀 /api）

- `POST /projects` `{name, brief}` → project.json；`GET /projects`；`GET /projects/{pid}`
- `PATCH /projects/{pid}/settings` 局部更新 `{render_mode?, director_recipe?, target_s?}`；`render_mode=standard|photoreal|scale_film`，`director_recipe=off|auto|scale|motion|structure`。不合法组合原子拒绝。
- `POST /projects/{pid}/docs`（multipart file）→ 解析并提取参数，返回 facts.json
- `GET /projects/{pid}/facts`；`PATCH /projects/{pid}/facts/{fid}` `{value?, unit?, status?}`
- `POST /projects/{pid}/model/step`（multipart）；`POST /projects/{pid}/model/parametric`
- `POST /projects/{pid}/assets`（multipart file + provenance + title + tags + credit）；`GET /projects/{pid}/assets`
- `POST /projects/{pid}/run` `{from_stage?: string, force?: bool}` → `{run}`；`GET /projects/{pid}/events`（SSE，先回放已有事件再推新事件）
- `GET /projects/{pid}/shotlist`；`PATCH /projects/{pid}/shots/{sid}` `{narration?, params?, review?}`
- `GET /projects/{pid}/issues`；`GET /projects/{pid}/report`
- 静态：`/files/<pid>/...` → `projects/<pid>/...`；`/` → web/app；`/player/` → web/player；`/vendor/three/` → web/node_modules/three

## 12. 尺度短片模式（T25）

`scale_film` 是15–30秒、30fps的主梁长度专用模板，允许scale/auto配方；目标与各镜边界对齐帧网格。使用有出处的确认主梁长度、整机高度和参数化模型；m/mm归一化，出处与原值保留，其他默认几何逐项记录assumed。STEP、其他主题及不相容几何明确拒绝，不换题或暗中回退。

三镜角色detail/hero/compare与4/5/6权重来自Skill中的render profile；该分支不调用LLM编写分镜。每次从plan重跑同步重建参数化模型。专用Blender输出画面，由后期生成当前参数/来源标题与真实TTS；超时长停止，不裁音或静默延长。普通播放器预览不代表该模式成片；UI直接播放最终MP4，QA从最终MP4抽帧。

GET project的`scale_film_ready`依据本次成功合成、当前事实/分镜/模型/音轨/算法来源hash及final字节hash判定。参数或台词改变、新运行未完成或失败时均false；界面隐藏过期播放与下载入口。仅重跑qa/report不能把前次失败或旧片改为完成。台词/params人工修改标为human_edited；固定模板无法兼容时停止而不覆盖。

既有通用校验的30–60秒提示保留，尺度模板15–30秒合法性由专用边界检查；photoreal硬性要求未放宽。详见[T25应用说明](T25-应用尺度短片.md)。
