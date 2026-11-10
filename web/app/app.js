import {$, esc, stages, stageLabel, fileURL, pill, request, jsonOptions, busy, stored, persist, toast} from './common.js';
import {createResources} from './resources.js';
import {createStudio} from './studio.js';
import {createAgent} from './agent.js';

const empty=()=>({pid:'',project:null,facts:[],assets:[],shotlist:{},timeline:{},timelineLoaded:false,issues:[],report:{},run:{},events:[]});
const ctx={state:empty()};
let revision=0, refreshTimer, pollBusy=false, runPending=false, lastPollError='', settingsPending=false;
ctx.isRunning=()=>ctx.state.run.state==='running' || runPending;
ctx.api=(path,options={},optional=false)=>request(`/api/projects/${encodeURIComponent(ctx.state.pid)}${path}`,options,optional);
ctx.markEdited=()=>{ $('#rerun-stage').value='validate'; toast('已保存，请从真实性校验重跑以更新成片与报告'); };
ctx.refresh=async()=>{
  const pid=ctx.state.pid, token=++revision; if(!pid) return;
  const keys=['project','facts','assets','shotlist','issues','timeline','report','run'];
  const paths=['','/facts','/assets','/shotlist','/issues','/timeline','/report','/run'];
  const responses=await Promise.all(paths.map(path=>request(`/api/projects/${encodeURIComponent(pid)}${path}`,{},path==='/shotlist')));
  if(pid!==ctx.state.pid || token!==revision) return;
  keys.forEach((key,index)=>{ const value=responses[index] || {}; ctx.state[key]=['facts','assets','issues'].includes(key)?value[key] || []:value; });
  ctx.state.timelineLoaded=true;
  render();
};
ctx.onEvent=event=>{
  renderRun();
  if(event.status!=='start') {
    clearTimeout(refreshTimer);
    refreshTimer=setTimeout(()=>ctx.refresh().catch(e=>toast(e.message)),150);
  }
};
ctx.resources=createResources(ctx); ctx.studio=createStudio(ctx); ctx.agent=createAgent(ctx);
$('#rerun-stage').innerHTML=stages.map(([id,label])=>`<option value="${id}">从${label}重跑</option>`).join('');
function renderRun() {
  const state=ctx.state, run=state.run, running=run.state==='running' || runPending;
  const label=stageLabel(run.stage);
  $('#generate').disabled=!state.pid || running || settingsPending; $('#generate').textContent=running?`${label}…`:'▶ 生成视频';
  $('#open-film').disabled=!state.pid || running || !(run.state==='done' || state.report.generated_at);
  $('#rerun').disabled=!state.pid || running || settingsPending; $('#rerun-stage').disabled=running;
  $('#project-select').disabled=runPending || settingsPending;
  $('#render-mode').disabled=!state.project || running || settingsPending;
  $('#render-mode').value=state.project?.render_mode || 'standard';
  $('#render-mode option[value=photoreal]').disabled=!state.project?.blender_available;
  $('#render-mode-hint').textContent=state.project && !state.project.blender_available?'未检测到 Blender，写实选项不可用。':'';
  $('#run-status').outerHTML=`<span id="run-status" class="pill ${esc(run.state || 'pending')}" role="status">${running?`${label} · 运行中`:({paused:'等待人工复核',done:'已完成',error:'运行失败'})[run.state] || (state.pid?'资料就绪':'等待资料')}</span>`;
  const blockCount=state.issues.filter(i=>i.severity==='block').length, paused=run.state==='paused';
  document.querySelectorAll('[data-action="force"]').forEach(b=>{ b.hidden=!paused; b.disabled=running; });
  $('#block-banner').hidden=!(paused && blockCount);
  $('#block-banner').innerHTML=paused && blockCount?`<strong>存在 ${blockCount} 个阻断问题，需人工复核后继续</strong><span>强制继续会在报告中保留未解决问题。</span><button class="danger" data-action="force">强制继续</button>`:'';
  $('#pipeline').innerHTML=stages.map(([id,name,icon])=>{
    const active=run.stage===id && running;
    const events=state.events.filter(e=>e.stage===id && (!run.run || e.run===run.run));
    const last=events.at(-1), done=run.stage_durations_s?.[id];
    const status=active?'running':run.stage===id && run.state==='error'?'error':run.stage===id && paused?'warn':last?.status==='warn'?'warn':done!=null || last?.status==='ok'?'ok':last?.status==='error'?'error':last?.status==='start'?'running':'pending';
    return `<div class="stage ${status}" data-stage="${id}"><span class="stage-icon">${icon}</span><div><strong>${name}</strong><small>${done!=null?`${Number(done).toFixed(1)} 秒`:status==='running'?'进行中':status==='pending'?'待运行':status==='error'?'失败':status==='warn'?'需关注':'已完成'}</small></div></div>`;
  }).join('');
  ctx.studio.preview();
}
function render() { renderRun(); ctx.resources.render(); ctx.studio.render(); ctx.agent.render(); }
async function loadProjects(selected) {
  const projects=await request('/api/projects');
  $('#project-select').innerHTML='<option value="">选择项目</option>'+projects.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  if(projects.some(p=>p.id===selected)) $('#project-select').value=selected;
  return projects;
}
async function selectProject(pid) {
  revision++; clearTimeout(refreshTimer); ctx.agent.close(); ctx.state=empty(); ctx.state.pid=pid; runPending=false;
  ctx.studio.reset(); $('#project-select').value=pid; persist('kepu.pid',pid); $('#rerun-stage').value='ingest'; render();
  if(pid) { await ctx.refresh(); ctx.agent.connect(); }
}
async function run(fromStage,force=false) {
  if(!ctx.state.pid || runPending || settingsPending || ctx.state.run.state==='running') return;
  runPending=true; renderRun();
  try { await ctx.api('/run',jsonOptions('POST',{...(fromStage?{from_stage:fromStage}:{}),force})); await ctx.refresh(); }
  finally { runPending=false; renderRun(); }
}
$('#open-film').addEventListener('click',()=>window.open(fileURL(ctx.state.pid,'renders/final.mp4'),'_blank','noopener'));
$('#generate').addEventListener('click',()=>run().catch(e=>toast(e.message)));
$('#rerun').addEventListener('click',()=>run($('#rerun-stage').value).catch(e=>toast(e.message)));
$('#render-mode').addEventListener('change',async event=>{
  const mode=event.target.value,pid=ctx.state.pid;
  settingsPending=true;renderRun();
  try{
    const project=await ctx.api('/settings',jsonOptions('PATCH',{render_mode:mode}));
    if(pid!==ctx.state.pid)return;
    ctx.state.project=project;$('#rerun-stage').value='render';
    toast('画面风格已保存，请从渲染阶段重跑');
  }catch(error){toast(error.message);}
  finally{settingsPending=false;renderRun();}
});
$('#project-select').addEventListener('change',event=>selectProject(event.target.value).catch(e=>toast(e.message)));
let seeding=false;
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-action]'); if(!button) return;
  if(button.dataset.action==='force') run('tts',true).catch(e=>toast(e.message));
  if(button.dataset.action==='seed' && !seeding) busy(button,async()=>{
    seeding=true;
    try {
      const project=await request('/api/demo/seed',{method:'POST'});
      await loadProjects(project.id); await selectProject(project.id);
      ctx.resources.rememberDoc('示例技术参数表.pdf'); ctx.resources.render();
      toast('示例已载入：1 份技术文档、5 张参考实拍素材');
    } finally { seeding=false; }
  });
});
setInterval(async()=>{
  ctx.agent.updateTimes();
  if(!ctx.state.pid || pollBusy) return;
  pollBusy=true; const pid=ctx.state.pid;
  try {
    const runState=await ctx.api('/run'); if(pid!==ctx.state.pid) return;
    if(JSON.stringify(runState)!==JSON.stringify(ctx.state.run)) {
      ctx.state.run=runState; await ctx.refresh();
    }
    lastPollError='';
  } catch(error) { if(lastPollError!==error.message) { toast(error.message); lastPollError=error.message; } }
  finally { pollBusy=false; }
},2000);
window.addEventListener('pagehide',()=>ctx.agent.close());
render();
try {
  const saved=stored('kepu.pid'), projects=await loadProjects(saved);
  if(saved && projects.some(p=>p.id===saved)) await selectProject(saved);
} catch(error) { toast(error.message); }
