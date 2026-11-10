# 重器科普 · 资料约束视频智能体

基于真实工业资料约束的 AI 科普视频生成智能体（卫华 AI 黑客松 10 号场景：超大起重机科普可视化）。

- 输入：创意需求 + 技术参数文档（PDF）+ 三维模型（STEP，可选；缺省时按参数化重建）+ 实拍/参考素材
- 输出：30–60 秒 1080p 科普视频（配音、字幕、来源角标、配乐）+ 镜头溯源报告

## 核心原则
1. **参数有出处**：数值只从文档抽取，程序核验「原文摘录在页内、数值在摘录内」，界面显示「第 N 页」。
2. **类比由程序计算**：大模型只挑参照物（足球场、楼层、头发丝……），倍数由代码算出并给出算式。
3. **台词不写裸数字**：台词用 `{{F_x}}`/`{{A_x}}` 占位，校验器拦截无出处数字、重复修饰、设备出现在 AI 画面等问题，阻断项自动交给大模型改写。
4. **设备只来自模型或实拍**：AI 创意画面只做氛围，不出现设备；参考实拍标注「非本机」。
5. **渲染后看图质检**：抽帧交给大模型检查字幕、标注、穿模等问题，写回问题列表。
6. **人工复核**：每个镜头可改台词、通过/打回、让智能体按指令改写，再从任意阶段重跑。

## 流水线
资料入库 → 三维模型 → 分镜规划（Opus 5.5）→ 真实性校验（+自动修正）→ 配音（edge-tts）→ 逐帧渲染（Three.js 播放器 + 浏览器逐帧截取）→ 合成（ffmpeg，配乐闪避与响度统一）→ 画面质检（Opus 5.5 看图）→ 溯源报告

## 运行
```sh
cd backend && uv sync && cd ../web && npm install
# 浏览器：使用本机 Chrome（或 npx playwright install chromium）
export KEPU_CHROMIUM_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
cd backend && uv run python -m app.main      # http://127.0.0.1:8031
```
打开 http://127.0.0.1:8031 → 「载入示例项目」→「生成视频」。

大模型：设置 `ANTHROPIC_API_KEY` 时走 SDK，否则调用本机 `claude` 命令行（模型 `claude-opus-5-5`）。
环境变量：`KEPU_PORT` 端口；`KEPU_PROJECTS_DIR` 项目目录；`KEPU_LLM_MODE=replay` 离线回放；`KEPU_TTS_ENGINE=fake` 静音配音；`KEPU_RENDER_MAX_S` 截断渲染时长（测试用）。

## 测试
```sh
cd backend && uv run pytest -q            # 单元与接口测试（离线回放，不调用真实模型）
cd backend && uv run pytest -q -m slow    # 真实渲染集成测试
cd web && npx playwright test             # 播放器与界面测试
```

## 素材与版权
示例参考图片来自 Wikimedia Commons，配乐为 CC BY 4.0，署名见 `samples/*/CREDITS.json`。示例技术参数表第 1 页说明了哪些数值来自场景描述、哪些为演示值。

接口与数据约定见 `docs/CONTRACTS.md`。
