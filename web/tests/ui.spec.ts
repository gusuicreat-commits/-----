import {test,expect,type Page} from '@playwright/test';
import {mkdir,readFile,rm} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {mergeEvents,esc,fileURL,generationProgress,costSummary,readCallLogs,displayIssue,toolSummary} from '../app/common.js';
import {narrationHTML,createStudio} from '../app/studio.js';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const testRoot=process.env.KEPU_UI_TEST_ROOT!;

// 仅在测试临时目录建立与当前真实资料匹配的离线请求索引。
// 复用人工编写的录制响应，不联网，也不向真实项目预写分镜和事件。
function prepareReplay(pid:string) {
 execFileSync(path.join(root,'backend/.venv/bin/python'),['-c',String.raw`
import json, os, shutil, sys, tempfile
from pathlib import Path
from app import config, llm, storage
from app.agent import orchestrator, planner, validator
pid, test_root = sys.argv[1], Path(sys.argv[2])
os.environ['KEPU_LLM_MODE'] = 'replay'
os.environ['KEPU_LLM_CASSETTES'] = str(test_root / 'cassettes')
with tempfile.TemporaryDirectory(prefix='request-context-', dir=test_root) as temporary:
    os.environ['KEPU_PROJECTS_DIR'] = temporary
    shutil.copytree(test_root / 'projects' / pid, Path(temporary) / pid)
    orchestrator.prepare_model(pid, 'fixture')
    context = planner._context(pid)
    target = llm.cassette_path('plan', planner.PLANNER_SYSTEM.replace('{target_s}', '45'), planner._prompt(context), planner.PLAN_SCHEMA)
    response = json.loads((config.ROOT / 'backend/tests/cassettes/plan_143d086f77995a49.json').read_text())
    response['note'] = '界面测试离线响应；请求索引根据本次示例资料计算，未调用真实模型'
    target.write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')
    shots = planner.plan(pid, 'fixture')
    blocks = [i for i in validator.validate(pid, 'fixture')['issues'] if i['severity'] == 'block' and i.get('shot')]
    if blocks:
        selected = list(dict.fromkeys(i['shot'] for i in blocks))
        extra = dict(issues=blocks, instruction='修正所有阻断问题，保留原有叙事意图。', analogies=shots.get('analogies', []), shots=[s for s in shots['shots'] if s['id'] in selected])
        duration = sum(s['duration_s'] for s in shots['shots'])
        target = llm.cassette_path('repair', planner.PLANNER_SYSTEM.replace('{target_s}', f'{duration:g}'), planner._prompt(context, **extra), planner.REPAIR_SCHEMA)
        source = json.loads((config.ROOT / 'backend/tests/cassettes/repair_c518e10bf9713dd7.json').read_text())
        target.write_text(json.dumps(source, ensure_ascii=False), encoding='utf-8')
`,pid,testRoot],{cwd:path.join(root,'backend'),env:process.env,timeout:30000});
}

async function noHorizontalOverflow(page:Page) {
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const boxes=await page.locator('.workspace > .panel').evaluateAll(elements=>elements.map(el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};}));
 expect(boxes).toHaveLength(3);
 expect(boxes[0].right).toBeLessThanOrEqual(boxes[1].left);
 expect(boxes[1].right).toBeLessThanOrEqual(boxes[2].left);
 for(const box of boxes) expect(box.bottom).toBeLessThanOrEqual(page.viewportSize()!.height);
}

async function compactFacts(page:Page) {
 const sizes=await page.locator('.fact-row').evaluateAll(elements=>elements.map(el=>el.getBoundingClientRect().height));
 expect(sizes.length).toBeGreaterThan(0);
 for(const height of sizes) expect(height).toBeLessThanOrEqual(72);
 await expect(page.locator('.fact-page').first()).toHaveText(/第\d+页/);
}

test.describe('真实后端操作流程',()=>{
 test.describe.configure({mode:'serial'});
 let page:Page, pid:string, confirmedFact:string, shotlist:any;
 const errors:string[]=[];
 test.beforeAll(async({browser})=>{
  await mkdir('test-results/ui',{recursive:true});
  page=await browser.newPage({viewport:{width:1920,height:1080},baseURL:'http://127.0.0.1:8032'});
  page.on('pageerror',error=>errors.push(error.message));
 });
 test.afterAll(async()=>{await page?.close(); if(pid) await rm(path.join(testRoot,'projects',pid),{recursive:true,force:true});});
 test('载入示例，素材五张、文档一份与空状态',async()=>{
  await page.goto('/');
  await expect(page.locator('#open-film')).toBeDisabled();
  await expect(page.getByRole('heading',{name:'让重器的每一处细节，有据可循'})).toBeVisible();
  await noHorizontalOverflow(page);
  await page.screenshot({path:'test-results/ui/01-empty.png'});
  await page.locator('.topbar [data-action="seed"]').click();
  await expect.poll(()=>page.locator('#project-select').inputValue()).not.toBe('');
  pid=await page.locator('#project-select').inputValue();
  await page.getByRole('tab',{name:'素材',exact:true}).click();
  await expect(page.locator('.asset-card')).toHaveCount(5);
  await expect(page.locator('.source-badge.reference')).toHaveCount(5);
  await page.getByRole('tab',{name:'文档',exact:true}).click();
  await expect(page.locator('.doc-card')).toHaveCount(1);
  await expect(page.locator('.doc-card')).toContainText('示例技术参数表.pdf');
 });
 test('提取文档参数并人工确认',async()=>{
  await page.getByRole('button',{name:'提取参数',exact:true}).click();
  await expect(page.locator('#event-stream')).toContainText('verify.facts');
  await page.getByRole('tab',{name:'参数表',exact:true}).click();
  await expect(page.locator('.fact-row.attention').first()).toBeVisible();
  const row=page.locator('.fact-row.attention').first(); confirmedFact=(await row.getAttribute('data-fact'))!;
  await row.getByRole('button',{name:'确认',exact:true}).click();
  await expect(page.locator(`[data-fact="${confirmedFact}"]`)).toContainText('人工确认');
  const response=await page.request.get(`/api/projects/${pid}/facts`);
  const facts=(await response.json()).facts;
  expect(facts.find((f:any)=>f.id===confirmedFact).status).toBe('confirmed');
  await compactFacts(page);
  const first=facts[0];
  await expect(page.locator(`[data-fact="${first.id}"] summary`)).toHaveAttribute('title',new RegExp(first.source.quote.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
 });
 test('完整生成，展示工具协作并提供成片',async()=>{
  test.setTimeout(360000);
  prepareReplay(pid);
  await page.locator('#generate').click();
  await expect(page.locator('#run-status')).toContainText('运行中');
  await expect(page.locator('#open-film')).toBeDisabled();
  await expect(page.locator('.preview-running')).toContainText('正在生成：');
  await expect(page.locator('#preview [data-action="seed"]')).toHaveCount(0);
  await page.screenshot({path:'test-results/ui/02-running.png'});
  await expect.poll(async()=>{
   const response=await page.request.get(`/api/projects/${pid}/run`), run=await response.json();
   if(run.state==='error') throw new Error(run.error);
   if(run.state==='paused') { await expect(page.locator('#block-banner')).toBeVisible(); await page.locator('#block-banner [data-action="force"]').click(); }
   return run.state;
  },{timeout:300000,intervals:[1000,2000]}).toBe('done');
  await expect(page.getByRole('link',{name:'下载成片',exact:false})).toBeVisible();
  const tools=['llm.opus.extract_facts','model.parametric','llm.opus.plan','validate.shotlist','tts.edge','render.player','ffmpeg.compose','report.provenance'];
  for(const tool of tools) await expect(page.locator('#event-stream')).toContainText(tool);
  const eventText=await (await page.request.get(`/files/${pid}/events.jsonl`)).text();
  const events=eventText.trim().split('\n').map(line=>JSON.parse(line));
  let previous=-1;
  for(const tool of tools) { const index=events.findIndex(e=>e.tool===tool); expect(index).toBeGreaterThan(previous); previous=index; }
  await expect(page.locator('#player-frame')).toHaveAttribute('data-ready','1');
  const frame=page.frameLocator('#player-frame');
  await expect.poll(()=>frame.locator('body').evaluate(()=> (window as any).__player?.duration || 0)).toBeGreaterThan(0);
  await frame.locator('body').evaluate(()=> (window as any).__player.ready);
  await expect(frame.locator('#error')).toBeHidden();
  expect((await page.request.get(`/files/${pid}/renders/final.mp4`)).ok()).toBe(true);
  shotlist=await (await page.request.get(`/api/projects/${pid}/shotlist`)).json();
  const logs=await readFile(path.join(testRoot,'projects',pid,'report.json'),'utf8');
  expect(JSON.parse(logs).llm.calls).toBeGreaterThan(0);
  await expect(page.locator('#outputs')).toContainText('回放模式 · 不产生费用');
  await expect(page.locator('#tool-count')).toContainText(/大模型 \d+ 次 · 程序工具 \d+ 次 · 总耗时 [\d.]+ 秒/);
  await expect(page.locator('#tool-count')).toContainText('回放模式 · 不产生费用');
  await expect(page.locator('#issues [data-severity="warn"]').filter({hasText:'缺少录制'})).toHaveCount(0);
  await expect(page.locator('#issues [data-severity="info"]')).toContainText('回放模式未录制画面质检');
  await expect(page.locator('#open-film')).toBeEnabled();
  const opened=page.waitForEvent('popup');
  await page.locator('#open-film').click();
  const film=await opened;
  await expect(film).toHaveURL(new RegExp(`/files/${pid}/renders/final\\.mp4$`));
  await film.close();
  await expect(page.locator('#event-stream')).not.toContainText('耗时 0.0 秒');
  const timeline=await (await page.request.get(`/api/projects/${pid}/timeline`)).json();
  expect(timeline.shots.map((s:any)=>s.id)).toEqual(shotlist.shots.map((s:any)=>s.id));
  expect(timeline.duration_s).toBeGreaterThan(4);
  expect(timeline.captions.some((c:any)=>c.start>4)).toBe(true);
  const probe=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-show_format','-of','json',path.join(testRoot,'projects',pid,'renders/final.mp4')],{encoding:'utf8'}));
  expect(Math.abs(Number(probe.format.duration)-4)).toBeLessThan(.1);
  expect(probe.streams.map((s:any)=>s.codec_type).sort()).toEqual(['audio','video']);
  for(const stream of probe.streams) expect(Math.abs(Number(stream.duration)-4)).toBeLessThan(.1);
  expect(Math.abs(timeline.rendered_duration_s-4)).toBeLessThan(.1);
  expect(Math.abs(JSON.parse(logs).duration_s-4)).toBeLessThan(.1);
  await noHorizontalOverflow(page);
  await page.screenshot({path:'test-results/ui/03-completed.png'});
 });
 test('时间轴定位、出处胶囊与播放器同步',async()=>{
  await expect(page.locator('#player-frame')).toHaveAttribute('data-ready','1');
  await expect(page.locator('.shot-card')).toHaveCount(shotlist.shots.length);
  await page.locator('.shot-card').nth(2).click();
  await expect(page.locator('#shot-detail')).toContainText(shotlist.shots[2].narration);
  await expect(page.frameLocator('#player-frame').locator('#shot-info')).toContainText(shotlist.shots[2].id);
  const withFact=shotlist.shots.findIndex((s:any)=>/\{\{F_/.test(s.narration) && /\{\{A_/.test(s.narration));
  expect(withFact).toBeGreaterThanOrEqual(0);
  await page.locator('.shot-card').nth(withFact).click();
  const citation=page.locator('.citation.fact').first();
  await citation.hover();
  await expect(page.locator('.citation-wrap').filter({has:citation}).getByRole('tooltip')).toBeVisible();
  await expect(page.locator('.citation-wrap').filter({has:citation}).getByRole('tooltip')).toContainText(/第\d+页/);
  const analogy=shotlist.analogies.find((a:any)=>shotlist.shots[withFact].narration.includes(`{{${a.id}}}`));
  await expect(page.locator('.analogy-calculation').first()).toContainText(analogy.formula);
  await page.locator('.analogy-calculation').first().scrollIntoViewIfNeeded();
  await page.locator('.citation.analogy').first().hover();
  await page.screenshot({path:'test-results/ui/04-shot-detail.png'});
  await expect(page.locator('#player-frame')).toHaveAttribute('data-ready','1');
  await page.frameLocator('#player-frame').locator('body').evaluate(()=> (window as any).__player.seek(0));
  await expect(page.locator('.shot-card').first()).toHaveAttribute('aria-pressed','true');
 });
 test('保存台词、通过复核并默认从校验重跑',async()=>{
  await page.locator('.shot-card').nth(2).click();
  const narration='主梁与支腿构成骨架，小车沿主梁移动，协同完成吊装。';
  await page.getByRole('button',{name:'编辑台词',exact:true}).click();
  await page.getByRole('textbox',{name:'台词编辑',exact:true}).fill(narration);
  await page.getByRole('button',{name:'保存台词',exact:true}).click();
  await expect(page.locator('#narration-view')).toHaveText(narration);
  await expect(page.locator('#rerun-stage')).toHaveValue('validate');
  const updated=await (await page.request.get(`/api/projects/${pid}/shotlist`)).json();
  expect(updated.shots[2].narration).toBe(narration);
  await page.getByRole('textbox',{name:'复核备注',exact:true}).fill('已核对结构说明与原始资料。');
  await page.getByRole('button',{name:'通过',exact:false}).click();
  await expect(page.locator('.shot-card').nth(2).locator('.review-dot')).toHaveClass(/approved/);
  const approved=await (await page.request.get(`/api/projects/${pid}/shotlist`)).json();
  expect(approved.shots[2].review.status).toBe('approved');
  expect(approved.shots[2].review.note).toBe('已核对结构说明与原始资料。');
 });
 test('刷新恢复项目，窄桌面布局与截图',async()=>{
  await page.reload();
  await expect(page.locator('#project-select')).toHaveValue(pid);
  await expect(page.locator('.shot-card')).toHaveCount(shotlist.shots.length);
  await page.setViewportSize({width:1366,height:768});
  await compactFacts(page);
  await expect(page.locator('#player-frame')).toHaveAttribute('data-ready','1');
  await page.frameLocator('#player-frame').locator('body').evaluate(()=> (window as any).__player.ready);
  await noHorizontalOverflow(page);
  await page.screenshot({path:'test-results/ui/05-narrow-1366.png'});
  expect(errors).toEqual([]);
 });
});

test.describe('纯逻辑校验',()=>{
 test('运行进度只读取本次事件，帧数缺失时保留百分比',()=>{
  const state:any={run:{run:'r2',stage:'render',stage_durations_s:{ingest:1,model:2}},events:[
   {run:'r1',stage:'report',status:'ok',detail:{}},
   {run:'r2',stage:'render',status:'start',summary:'渲染中',detail:{frame:12,total:120}},
  ]};
  let progress=generationProgress(state);
  expect(progress.label).toBe('渲染'); expect(progress.percent).toBe(10);
  expect(progress.progress).toBe('已渲染 12 / 120 帧');
  expect(progress.completed.map(([id]:string[])=>id)).toEqual(['ingest','model']);
  state.events[1].detail={progress:20}; progress=generationProgress(state);
  expect(progress.percent).toBe(20); expect(progress.progress).toBe('已完成 20%');
  state.events.push({run:'r2',stage:'compose',status:'start',summary:'合成中',detail:{}});
  expect(generationProgress(state).label).toBe('渲染');
  state.run.stage='model';
  expect(generationProgress(state).label).toBe('三维模型');
  state.run.stage='';
  expect(generationProgress(state).label).toBe('准备中');
 });
 test('仅将缺少回放录制的画面质检警告降为提示',()=>{
  const warning={shot:'S1',severity:'warn',code:'VISUAL_QA',message:'自动画面质检未完成：缺少录制 visual_qa_test.json',hint:'人工复核'};
  expect(displayIssue(warning)).toMatchObject({severity:'info',message:'回放模式未录制画面质检',hint:''});
  expect(warning.severity).toBe('warn');
  for(const issue of [{...warning,severity:'block'},{...warning,code:'OTHER'},{...warning,message:'画面遮挡'}]) expect(displayIssue(issue)).toEqual(issue);
 });
 test('调用汇总合并进度并按运行时间跨度统计，费用保留未知项',()=>{
  const base={run:'r1',stage:'render',summary:'渲染',tool:'render.player'};
  const events=[
   {...base,ts:'2026-01-01T00:00:00Z',status:'start'},
   {...base,ts:'2026-01-01T00:00:01Z',status:'start',detail:{progress:50}},
   {...base,ts:'2026-01-01T00:00:01Z',status:'start',tool:'llm.opus.plan'},
   {...base,ts:'2026-01-01T00:00:02Z',status:'ok'},
   {...base,ts:'2026-01-01T00:00:03Z',status:'ok',tool:'llm.opus.plan'},
  ];
  const llm={calls:1,cost_usd:.12,unknown_cost_calls:1};
  expect(toolSummary(events,llm)).toBe('大模型 1 次 · 程序工具 1 次 · 总耗时 3.0 秒 · 已知费用 $0.1200 · 1 次费用未知，未计入合计');
  expect(toolSummary(events,llm,[{backend:'replay'}])).toContain('回放模式 · 不产生费用');
  expect(toolSummary(events.slice(0,1),null,[],Date.parse('2026-01-01T00:00:04Z'))).toContain('总耗时 4.0 秒 · 费用待统计');
  expect(toolSummary([],null)).toContain('大模型 0 次 · 程序工具 0 次 · 总耗时 0.0 秒');
 });
 test('预览等待时间线与播放器就绪，相同画面不因刷新或运行状态重建',async()=>{
  // 最小 DOM 替身：在无浏览器环境验证异步加载及 iframe 身份。
  const previous=Object.getOwnPropertyDescriptor(globalThis,'document');
  let children:any[]=[], finishReady!:()=>void, unsubscribed=0;
  const player={ready:new Promise<void>(resolve=>{finishReady=resolve;}),on:()=>()=>{unsubscribed++;}};
  const node=()=>({id:'',innerHTML:'',hidden:false,isConnected:false,dataset:{} as any,contentWindow:{__player:player},listeners:{} as any,
   addEventListener(name:string,fn:any){this.listeners[name]=fn;},
   remove(){children=children.filter(child=>child!==this);this.isConnected=false;}});
  const host={append(child:any){child.isConnected=true;children.push(child);},replaceChildren(...next:any[]){children.forEach(child=>{child.isConnected=false;});children=next;children.forEach(child=>{child.isConnected=true;});}};
  const targets:any={'#preview':host,'#timeline':node(),'#shot-detail':node()};
  Object.defineProperty(globalThis,'document',{configurable:true,value:{querySelector:(selector:string)=>targets[selector] || children.find(child=>`#${child.id}`===selector),createElement:node}});
  try {
   const state:any={pid:'p1',timelineLoaded:false,timeline:{shots:[{id:'S1'}],captions:[],audio:'a.wav'},run:{state:'done'},events:[]};
   const studio=createStudio({state,isRunning:()=>state.run.state==='running'});
   const frame=()=>children.find(child=>child.id==='player-frame');
   studio.preview(); expect(frame()).toBeUndefined(); expect(children[0].innerHTML).toContain('正在加载时间线');
   state.timelineLoaded=true; studio.preview(); const first=frame();
   const loading=first.listeners.load();
   expect(first.dataset.ready).toBeUndefined();
   state.timeline.rendered_duration_s=4; state.report={generated_at:'完成'}; studio.preview();
   expect(frame()).toBe(first);
   finishReady(); await loading; expect(first.dataset.ready).toBe('1');
   state.run={state:'running',stage:'model'}; studio.preview();
   expect(frame()).toBe(first); expect(first.hidden).toBe(true);
   expect(children.find(child=>child.id==='preview-status').innerHTML).toContain('正在生成：三维模型');
   state.run.state='done'; studio.preview(); expect(frame()).toBe(first); expect(first.hidden).toBe(false);
   for(const [key,value] of [['shots',[{id:'S2'}]],['captions',[{text:'新字幕'}]],['audio','b.wav']] as const) {
    const old=frame(); state.timeline[key]=value; studio.preview(); expect(frame()).not.toBe(old); expect(old.isConnected).toBe(false);
   }
   expect(unsubscribed).toBe(1);
   const old=frame(), staleLoad=old.listeners.load();
   state.pid='p2'; studio.preview(); await staleLoad;
   expect(frame()).not.toBe(old); expect(old.dataset.ready).toBeUndefined();
   studio.reset(); expect(children).toHaveLength(0);
  } finally {
   if(previous) Object.defineProperty(globalThis,'document',previous); else Reflect.deleteProperty(globalThis,'document');
  }
 });
 test('费用使用报告字段，只有完整回放记录显示免费',async()=>{
  const llm={calls:2,cost_usd:.1234,unknown_cost_calls:0};
  expect(costSummary(llm,[{backend:'cli'},{backend:'cli'}])).toContain('$0.1234');
  expect(costSummary(llm,[{backend:'replay'},{backend:'cli'}])).not.toContain('不产生费用');
  expect(costSummary(llm,[{backend:'replay'}])).not.toContain('不产生费用');
  const records:any={'/files/p1/llm/001_extract_facts.json':{backend:'replay'},'/files/p1/llm/002_plan.json':{backend:'replay'}};
  const logs=await readCallLogs('p1',2,[],async(url:string)=>records[url] || null);
  expect(costSummary({calls:2,cost_usd:0,unknown_cost_calls:2},logs)).toBe('回放模式 · 不产生费用');
  expect(costSummary({calls:1,cost_usd:0,unknown_cost_calls:1})).toContain('1 次费用未知');
  expect(await readCallLogs('p1',3,[],async(url:string)=>records[url] || null)).toEqual([]);
 });
 test('真实接口提取、确认与离线规划请求一致',async({request})=>{
  const seeded=await request.post('/api/demo/seed');
  expect(seeded.ok()).toBe(true);
  const project=await seeded.json();
  try {
   const response=await request.post(`/api/projects/${project.id}/docs?sync=1`,{multipart:{file:{name:'示例技术参数表.pdf',mimeType:'application/pdf',buffer:await readFile(path.join(root,'samples/示例技术参数表.pdf'))}}});
   expect(response.ok()).toBe(true);
   const facts=(await response.json()).facts;
   const pending=facts.find((fact:any)=>fact.status==='needs_review');
   expect(pending).toBeTruthy();
   const confirmed=await request.patch(`/api/projects/${project.id}/facts/${pending.id}`,{data:{status:'confirmed'}});
   expect((await confirmed.json()).status).toBe('confirmed');
   prepareReplay(project.id);
   const model=await request.post(`/api/projects/${project.id}/model/parametric`);
   expect(model.ok()).toBe(true);
   const data=await model.json();
   expect(data.kind).toBe('parametric');
   expect(data.derived_from.length).toBeGreaterThan(0);
   expect((await request.get(`/files/${project.id}/${data.glb}`)).ok()).toBe(true);
   expect((await request.get(`/api/projects/${project.id}/assets`)).ok()).toBe(true);
  } finally { await rm(path.join(testRoot,'projects',project.id),{recursive:true,force:true}); }
 });
 test('按运行与镜头合并工具事件，渲染进度不重复计数',()=>{
  const base={run:'r1',stage:'render',tool:'render.player',summary:'渲染',detail:{}};
  const events=[{...base,ts:'2026-01-01T00:00:00Z',status:'start'}, {...base,ts:'2026-01-01T00:00:01Z',status:'start',detail:{progress:50}}, {...base,ts:'2026-01-01T00:00:02Z',status:'ok'}, {...base,run:'r2',ts:'2026-01-01T00:00:03Z',status:'start'}];
  const calls=mergeEvents(events);
  expect(calls).toHaveLength(2); expect(calls[0].elapsed).toBe(2); expect(calls[0].updates).toHaveLength(3); expect(calls[1].status).toBe('start');
 });
 test('并发镜头配音与工具重试分别展示',()=>{
  const base={run:'r1',stage:'tts',tool:'tts.edge',summary:'配音',ts:'2026-01-01T00:00:00Z'};
  expect(mergeEvents([{...base,status:'ok',detail:{shot:'S1'}},{...base,status:'ok',detail:{shot:'S2'}}])).toHaveLength(2);
  expect(mergeEvents([{...base,status:'start'},{...base,status:'error'},{...base,status:'start'},{...base,status:'ok'}])).toHaveLength(2);
 });
 test('台词引用保留出处与类比依据，转义不可信文本',()=>{
  const html=narrationHTML('<script>坏</script>{{F_span}}{{A_span}}',[{id:'F_span',value:88,unit:'m',source:{doc:'参数.pdf',page:2,quote:'跨度 88 m'}}],[{id:'A_span',fact:'F_span',text:'约一个足球场',formula:'88 / 105',basis:'标准足球场长度'}]);
  expect(html).toContain('88米 · 第2页'); expect(html).toContain('跨度 88 m'); expect(html).toContain('88 / 105'); expect(html).toContain('标准足球场长度'); expect(html).not.toContain('<script>'); expect(html).toContain('&lt;script&gt;');
  expect(fileURL('p1','docs/参数 表.pdf')).toBe('/files/p1/docs/%E5%8F%82%E6%95%B0%20%E8%A1%A8.pdf');
  expect(esc('"<>&')).toBe('&quot;&lt;&gt;&amp;');
 });
});
