const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels = ['上传资料','对话创意','制作方式','AI 导演','预览与修改','制作与下载'];
const titles = ['好故事，从真实资料开始。','先聊想法，再编排镜头。','用合适的方式，把故事讲好。','让创意，成为有依据的方案。','先看见故事，再决定成片。','把确认的方案，变成作品。'];
const descriptions = ['上传设备资料，让每一句讲解、每个画面都有依据。','告诉导演你的观众、讲解重点与想要的表达。','两种制作引擎，同一个目标：把复杂知识讲明白。','AI 理解资料、编排镜头；预览不会启动完整视频制作。','检查分镜、台词与关键画面，用自然语言继续打磨。','三维画面、配音与字幕合成完成后，下载视频和项目。'];
const kinds = {title:'开场',model_orbit:'整机展示',data_card:'参数讲解',analogy:'尺度比较',motion:'运动演示',exploded:'结构拆解',real_photo:'实拍图片',real_video:'实拍视频',outro:'收束',weld_macro:'局部细节'};
let pid = new URLSearchParams(location.search).get('project') || '', step = 1, engine = 'threejs', content = 'auto', caps = null, workflow = {}, shots = [], timeline = {}, selected = '', busy = false, dirty = false, replanNeeded = false, timer, playerKey = '', project = {}, uploaded = [];
async function api(path, options = {}) {
  let response; try { response = await fetch(path, options); } catch { throw new Error('连接服务失败，请检查服务后重试。你的创意草稿仍保留在页面中。'); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.error === 'string' ? body.error : typeof body.detail === 'string' ? body.detail : `服务返回 ${response.status}，请检查输入后重试。`);
  return body;
}
const json = (method, body) => ({method, headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const route = suffix => `/api/projects/${encodeURIComponent(pid)}${suffix}`;
function notice(message = '') { $('#notice').hidden = !message; $('#notice').textContent = message; }
function showStep(next) {
  step = Number(next); document.querySelectorAll('[data-panel]').forEach(p => p.hidden = Number(p.dataset.panel) !== step);
  $('#steps').innerHTML = labels.map((label,i) => `<button class="step ${step === i+1 ? 'active' : ''}" data-step="${i+1}" ${step === i+1 ? 'aria-current="step"' : ''}><span class="step-index">${String(i+1).padStart(2,'0')}</span>${label}</button>`).join('');
  $('#step-eyebrow').textContent = `0${step} / 06 · ${labels[step-1]}`; $('#step-title').textContent = titles[step-1]; $('#step-description').textContent = descriptions[step-1]; summary(); renderControls();
  window.scrollTo({top:0,behavior:'instant'});
}
function summary() {
  $('#brief-summary').innerHTML = [['创意',$('#brief').value || '还没有填写创意'],['目标时长',`${$('#duration').value} 秒`],['制作方式',engine === 'threejs' ? '轻量快制 · Three.js' : '精细制作 · Blender'],['内容重点',({auto:'由资料与创意决定',scale:'尺度',motion:'运动',structure:'结构'})[content]]].map(([k,v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
}
function draftKey() { return `kepu.workflow.draft.${pid || 'new'}`; }
function saveDraft() { try { localStorage.setItem(draftKey(),JSON.stringify({brief:$('#brief').value,target_s:Number($('#duration').value),engine,content})); } catch {} }
function invalidate(replan = true) {
  replanNeeded = replanNeeded || replan; saveDraft();
  dirty = true; workflow = {...workflow,can_produce:false,can_download:false,exports:{}}; $('#downloads').replaceChildren(); $('#final-video').replaceChildren(); playerKey = ''; $('#preview-stage').innerHTML = '<div class="preview-placeholder"><span>↻</span><h2>创作已更新</h2><p>更新方案与预览后，可确认新版本。</p></div>'; renderControls();
}
function providerReady() { const p = caps?.provider; return p?.configured === true && p?.mode !== 'replay' && p?.mode !== 'fake' && p?.live !== false; }
function renderControls() {
  const running = ['previewing','producing'].includes(workflow.state);
  const engineReady = caps?.engines?.find(e => e.id === engine)?.available === true;
  $('#seed-example').disabled = busy || running; $('#create-project').disabled = busy || !!pid; $('#project-name').disabled = !!pid;
  $('#files').disabled = busy || running || !pid;
  $('#preview-plan').disabled = busy || running || !pid || !$('#brief').value.trim() || !providerReady() || !engineReady;
  $('#repreview').disabled = busy || running || !pid || !shots.length || !providerReady();
  $('#produce').disabled = busy || running || dirty || workflow.can_produce !== true;
  $('#retry-produce').disabled = busy || running || !pid || !shots.length || !providerReady();
  $('#revise').disabled = busy || running || !selected || !providerReady();
  document.querySelectorAll('[data-next],[data-content],#brief,#duration').forEach(b => b.disabled = busy || running);
  document.querySelectorAll('[data-engine]').forEach(b => b.disabled = busy || running || caps?.engines?.find(e => e.id === b.dataset.engine)?.available !== true);
  $('#revision-status').textContent = dirty ? '修改尚未更新预览' : workflow.can_produce ? '当前方案已通过校验' : workflow.state === 'blocked' ? '有待复核问题' : '';
  $('#busy-status').hidden = !(busy || running);
  if (!busy && running) $('#busy-text').textContent = workflow.state === 'previewing' ? 'AI 正在理解资料、编排镜头与准备预览。等待服务返回结果…' : '正在制作画面、配音字幕并合成视频。请等待真实制作结果…';
}
async function action(text, fn) { if (busy) return; busy = true; notice(); $('#busy-text').textContent = text; renderControls(); try { await fn(); } catch(e) { notice(e.message); } finally { busy = false; renderControls(); } }
async function loadCaps() {
  try {
    caps = await api('/api/workflow/capabilities'); const p = caps.provider || {};
    $('#capabilities').classList.toggle('unavailable', !providerReady());
    $('#capabilities').textContent = providerReady() ? 'AI 服务已配置。生成时仍将核对资料与可用制作能力。' : p.mode === 'replay' ? '当前为测试回放模式，不能作为真实 AI 导演使用。请配置在线模型服务后重新检查。' : `AI 导演尚未就绪：${p.error || p.message || '需要配置在线模型服务'}。可先准备资料与创意。`;
    $('#service-details').textContent = JSON.stringify(caps,null,2);
    document.querySelectorAll('[data-engine]').forEach(b => { const c = caps.engines?.find(e => e.id === b.dataset.engine); b.disabled = c?.available !== true; b.title = c?.available ? '' : '此制作引擎尚未可用'; });
  } catch(e) { caps = null; $('#capabilities').textContent = e.message; $('#capabilities').classList.add('unavailable'); }
  renderControls();
}
async function createProject() {
  const name = $('#project-name').value.trim(); if (!name) throw new Error('先给视频起个名字。');
  project = await api('/api/projects',json('POST',{name,brief:''})); pid = project.id;
  if (!pid) throw new Error('项目创建结果缺少编号，请刷新后重试。');
  history.replaceState(null,'',`/create.html?project=${encodeURIComponent(pid)}`); $('#project-label').textContent = project.name || name;
  $('#review-link').href = $('#advanced-link').href = `/?project=${encodeURIComponent(pid)}`; notice('空白项目已创建，现在可以上传资料。');
}
function fileList() { $('#file-list').innerHTML = uploaded.map((f,i) => `<li><span>${esc(f.name)}</span><span class="${f.status === '失败' ? 'failed' : ''}">${esc(f.status)}</span>${f.status === '失败' && f.file ? `<button data-retry="${i}">重试</button>` : ''}</li>`).join(''); $('#upload-count').textContent = uploaded.length ? `${uploaded.filter(f => f.status === '已上传').length} / ${uploaded.length} 份已上传` : '尚未上传'; }
async function seedExample() {
  saveDraft();
  const example = await api('/api/demo/seed',json('POST',{}));
  if (!example.id) throw new Error('示例创建结果缺少编号，请重试。');
  location.assign(`/create.html?project=${encodeURIComponent(example.id)}&example=crane`);
}
function keyframeLabel(frame) {
  if (frame?.engine === 'blender') return 'Blender 精细关键帧';
  if (frame?.engine === 'source') return ['video','real_video'].includes(frame.kind) ? '实拍视频素材' : ['image','real_photo'].includes(frame.kind) ? '实拍图片素材' : '来源素材预览';
  return frame?.engine === 'threejs' ? '网页三维预览帧' : '关键画面预览';
}
function keyframeMedia(frame, label, detail = false) {
  if (!frame) return '';
  if (frame.engine === 'source' && ['video','real_video'].includes(frame.kind)) {
    return `<video ${detail ? 'class="keyframe" controls' : 'tabindex="-1"'} muted playsinline preload="metadata" src="${esc(frame.url)}" aria-label="${esc(label)}"></video>`;
  }
  return `<img ${detail ? 'class="keyframe"' : ''} src="${esc(frame.url)}" alt="${esc(label)}">`;
}
async function uploadOne(item) {
  const file = item.file; const suffix = file.name.split('.').at(-1).toLowerCase(); let path;
  const data = new FormData(); data.append('file',file);
  if(suffix === 'pdf') path = '/docs?sync=1'; else if(['step','stp'].includes(suffix)) path = '/model/step'; else if(file.type.startsWith('image/') || file.type.startsWith('video/')) {
    path = '/assets'; const provenance = $('#provenance').value, credit = $('#credit').value.trim(); if(provenance === 'reference' && !credit) throw new Error('参考图片或视频需要填写作者、许可与来源链接。');
    data.append('provenance',provenance); data.append('title',file.name); data.append('credit',credit);
  } else throw new Error('暂不支持此文件，请选择 PDF、图片、视频或 STEP。');
  item.status = '上传与处理…'; fileList();
  try { await api(route(path),{method:'POST',body:data}); item.status = '已上传'; invalidate(); } catch(e) { item.status = '失败'; item.error = e.message; throw e; } finally { fileList(); }
}
async function upload(files) {
  if (!pid) throw new Error('请先创建项目。'); const errors = [];
  for(const file of files) { const item = {name:file.name,file,status:'等待上传'}; uploaded.push(item); try { await uploadOne(item); } catch(e) { item.status = '失败'; errors.push(`${file.name}：${e.message}`); fileList(); } }
  if(errors.length) throw new Error(errors.join('\n')); notice('资料已上传。参数提取结果需到高级工作室复核；不会自动把缺失依据当作事实。');
}
async function saveBrief() {
  if (!pid) throw new Error('请先创建项目并上传资料。'); if (!$('#brief').value.trim()) throw new Error('请先写下你想讲清楚的内容。');
  await api(route('/workflow/brief'),json('PATCH',{brief:$('#brief').value.trim(),target_s:Number($('#duration').value),engine,content}));
  dirty = false;
}
async function preview(replan) {
  if(!providerReady()) throw new Error('AI 模型服务尚未配置，请先检查制作服务。');
  await saveBrief(); workflow = await api(route('/workflow/preview'),json('POST',{replan:replan || replanNeeded})); replanNeeded = false; try { localStorage.removeItem(draftKey()); } catch {} showStep(5); await refresh();
}
function schedule() { clearTimeout(timer); if(['previewing','producing'].includes(workflow.state)) timer = setTimeout(() => refresh().catch(e => { notice(e.message); schedule(); }),2000); }
async function refresh() {
  if(!pid) return; workflow = await api(route('/workflow'));
  if(workflow.preview?.timeline_url && workflow.current) {
    const [s,t] = await Promise.all([api(route('/shotlist')),api(workflow.preview.timeline_url)]); shots = s.shots || []; timeline = t;
    if(!shots.some(s => s.id === selected)) selected = shots[0]?.id || '';
    renderPlan(s); renderShots(); renderPreview();
  }
  if(workflow.error) notice(workflow.error);
  if(workflow.state === 'blocked') notice('当前方案有需复核的问题。查看导演卡片中的原因，修正后更新预览。');
  renderFinal(); renderControls(); schedule();
}
function renderPlan(plan) {
  $('#plan-title').textContent = plan.title || `${shots.length} 个镜头，讲清一个故事`;
  const director = workflow.director_plan || {};
  const rationale = plan.rationale || plan.summary || plan.director?.rationale || director.question;
  $('#plan-body').innerHTML = `${rationale ? `<p>${esc(typeof rationale === 'string' ? rationale : JSON.stringify(rationale))}</p>` : `<p>当前分镜：${shots.map(s => esc(kinds[s.kind] || s.kind)).join(' → ')}。</p>`}<p>${esc(engine === 'blender' ? '精细制作 · Blender' : '轻量快制 · Three.js')} · ${esc(Math.round(Number(timeline.duration_s || shots.reduce((a,s) => a + Number(s.duration_s || 0),0)) * 10) / 10)} 秒</p>${director.sequence?.length ? `<p class="fine">导演编排：${director.sequence.map(s => esc(kinds[s.kind] || s.kind || s)).join(' → ')}</p>` : ''}<p class="fine">${engine === 'blender' ? '构图预演使用网页三维；精细关键帧由 Blender 单独生成。' : '当前为无声构图预演；配音字幕在确认制作后生成。'}</p>${(workflow.issues || []).length ? `<ul>${workflow.issues.map(i => `<li>${esc(i.message)}${i.hint ? `：${esc(i.hint)}` : ''}</li>`).join('')}</ul>` : '<p class="fine">校验结果：当前未报告阻断问题。</p>'}`;
}
function renderShots() {
  $('#shots').innerHTML = shots.map((s,i) => {const keyframe = workflow.preview?.keyframes?.find(k => k.shot === s.id); return `<button class="shot ${s.id === selected ? 'selected' : ''}" data-shot="${esc(s.id)}" aria-pressed="${s.id === selected}">${keyframeMedia(keyframe, `镜头 ${i+1} ${keyframeLabel(keyframe)}`)}<span>${String(i+1).padStart(2,'0')} / ${esc(s.duration_s)}s</span><strong>${esc(s.title || kinds[s.kind] || s.kind)}</strong></button>`;}).join('');
  const shot = shots.find(s => s.id === selected); if(!shot) return;
  const selectedFrame = workflow.preview?.keyframes?.find(k => k.shot === selected);
  $('#shot-position').textContent = `镜头 ${shots.indexOf(shot)+1} / ${shots.length}`;
  $('#shot-detail').innerHTML = `<span class="tag">镜头 ${shots.indexOf(shot)+1} · ${esc(kinds[shot.kind] || shot.kind)}</span><h2>${esc(shot.title || shot.description || '画面与台词')}</h2>${selectedFrame ? `${keyframeMedia(selectedFrame, `当前镜头 ${keyframeLabel(selectedFrame)}`, true)}<p class="fine">${esc(keyframeLabel(selectedFrame))} · ${selectedFrame.engine === 'source' && ['video','real_video'].includes(selectedFrame.kind) ? '可播放来源素材' : '单帧画面预览'}</p>` : ''}<p class="narration">${esc(shot.narration_resolved || shot.narration || '此镜头暂无台词')}</p><div>${(shot.fact_refs || []).map(f => `<span class="source-chip">依据 ${esc(f)}</span>`).join('')}</div><details><summary>高级 · 镜头依据与参数</summary><pre>${esc(JSON.stringify({fact_refs:shot.fact_refs,params:shot.params},null,2))}</pre></details>`;
}
function renderPreview() {
  if (dirty || !workflow.current || !workflow.preview?.timeline_url) return;
  const key = workflow.plan_revision;
  if(key === playerKey) return;
  playerKey = key; const frame = document.createElement('iframe'); frame.title = '分镜构图预演（非最终成片）'; frame.id = 'workflow-player'; frame.src = `/player/index.html?timeline=${encodeURIComponent(workflow.preview.timeline_url)}&mode=preview&v=${encodeURIComponent(key)}`;
  frame.addEventListener('load',async () => { try { const player = frame.contentWindow.__player; if(!player) throw new Error(); await player.ready; if(frame.isConnected) frame.dataset.ready = 'true'; } catch { notice('构图播放器未能加载。可先查看分镜与台词，再检查模型资源后更新预览。'); } });
  $('#preview-stage').replaceChildren(frame);
}
async function selectShot(id) {
  selected = id; renderShots(); renderControls(); const shot = timeline.shots?.find(s => s.id === id); if(!shot) return;
  const frame = $('#workflow-player'); const player = frame?.contentWindow?.__player;
  if(frame?.dataset.ready === 'true' && player) { try { await player.seek(Math.min(shot.start+.05,shot.end-.01)); } catch { notice('镜头定位失败，请更新预览后重试。'); } }
}
async function produce() {
  if(dirty || !workflow.can_produce || !workflow.plan_revision) throw new Error('请先更新并确认通过校验的方案。');
  workflow = await api(route('/workflow/produce'),json('POST',{plan_revision:workflow.plan_revision})); showStep(6); renderFinal(); await refresh();
}
function renderFinal() {
  const ready = !dirty && workflow.can_download === true; const exports = ready ? workflow.exports || {} : {};
  $('#final-title').textContent = ready ? '你的作品，已制作完成。' : workflow.state === 'error' ? '这次制作尚未完成。' : workflow.state === 'producing' ? '正在把方案变成作品。' : '确认方案后，开始制作。';
  $('#production-status').textContent = ready ? '播放并检查成片，下载 MP4、项目与来源报告。' : workflow.error || (workflow.state === 'producing' ? '工作室正在制作三维画面、配音字幕并合成 MP4。完成时间以实际任务为准。' : '请返回分镜确认当前方案；完整制作只会在你点击确认后启动。');
  $('#production-error').hidden = workflow.state !== 'error';
  if(ready && exports.mp4) { if(!$('#final-video video')) { const video = document.createElement('video'); video.controls = true; video.playsInline = true; video.preload = 'metadata'; video.setAttribute('aria-label','最终 MP4 成片'); video.addEventListener('error',() => notice('成片文件未能播放，请检查制作结果后刷新状态或直接下载查看。')); video.src = exports.mp4 + `?v=${encodeURIComponent(workflow.plan_revision)}`; $('#final-video').replaceChildren(video); } }
  else $('#final-video').replaceChildren();
  $('#downloads').innerHTML = Object.entries({mp4:'↓ 下载 MP4',project:'↓ 下载项目',sources:'查看来源与报告 ↗'}).filter(([key]) => exports[key]).map(([key,label]) => `<a href="${esc(exports[key])}" ${key === 'sources' ? 'target="_blank" rel="noopener"' : 'download'}>${label}</a>`).join('');
}
$('#steps').addEventListener('click', e => { const b = e.target.closest('[data-step]'); if(b) showStep(b.dataset.step); });
document.querySelectorAll('[data-next]').forEach(b => b.addEventListener('click', () => { if(!pid) return notice('请先创建空白项目。'); notice(); showStep(b.dataset.next); }));
$('#seed-example').onclick = () => action('正在创建独立起重机示例项目…',seedExample);
$('#create-project').onclick = () => action('正在创建空白项目…',createProject);
$('#files').onchange = e => { const files = [...e.target.files]; action('正在上传并处理资料…',() => upload(files)); e.target.value = ''; };
$('#file-list').onclick = e => { const b = e.target.closest('[data-retry]'); if(b) action('正在重试上传…',() => uploadOne(uploaded[Number(b.dataset.retry)])); };
const zone = $('#dropzone'); ['dragenter','dragover'].forEach(name => zone.addEventListener(name,e => {e.preventDefault(); zone.classList.add('drag');})); ['dragleave','drop'].forEach(name => zone.addEventListener(name,e => { e.preventDefault(); zone.classList.remove('drag'); })); zone.addEventListener('drop',e => { if(!busy && !['previewing','producing'].includes(workflow.state)) action('正在上传并处理资料…',() => upload([...e.dataTransfer.files])); });
$('#brief').oninput = () => { invalidate(); summary(); }; $('#duration').onchange = () => invalidate();
document.querySelectorAll('[data-prompt]').forEach(b => b.onclick = () => { $('#brief').value = [$('#brief').value,b.dataset.prompt].filter(Boolean).join('\n'); invalidate(); });
document.querySelectorAll('[data-engine]').forEach(b => b.onclick = () => { engine = b.dataset.engine; document.querySelectorAll('[data-engine]').forEach(c => { c.classList.toggle('selected',c === b); c.setAttribute('aria-pressed',String(c === b)); }); invalidate(); });
document.querySelectorAll('[data-content]').forEach(b => b.onclick = () => { content = b.dataset.content; document.querySelectorAll('[data-content]').forEach(c => { c.classList.toggle('selected',c === b); c.setAttribute('aria-pressed',String(c === b)); }); invalidate(); });
$('#refresh-status').onclick = () => action('正在检查服务…',loadCaps); $('#preview-plan').onclick = () => action('正在保存创意并请求导演编排…',() => preview(true)); $('#repreview').onclick = () => action('正在校验修改并更新预览…',() => preview(false));
$('#shots').onclick = e => { const b = e.target.closest('[data-shot]'); if(b) selectShot(b.dataset.shot); };
$('#revise-form').onsubmit = e => {e.preventDefault(); action('AI 正在修改选中的镜头…',async () => { if(!selected) throw new Error('先选择一个镜头。'); await api(route(`/shots/${encodeURIComponent(selected)}/revise`),json('POST',{instruction:$('#instruction').value})); invalidate(false); notice('镜头已修改。请更新方案与预览后再确认制作。'); const s = await api(route('/shotlist')); shots = s.shots || []; renderShots(); });};
$('#produce').onclick = () => action('正在提交当前方案制作…',produce); $('#retry-produce').onclick = () => action('正在重新检查方案…',() => preview(false)); $('#refresh-result').onclick = () => action('正在刷新制作状态…',refresh);
async function init() {
  showStep(1); $('#example-notice').hidden = new URLSearchParams(location.search).get('example') !== 'crane'; await loadCaps(); if(!pid) { try { const d = JSON.parse(localStorage.getItem(draftKey()) || 'null'); if(d?.brief) $('#brief').value = d.brief; } catch {} return; }
  try { project = await api(route('')); $('#project-label').textContent = project.name; $('#project-name').value = project.name; $('#brief').value = project.brief || ''; $('#duration').value = String(project.target_s || 30); engine = project.production_engine || 'threejs'; content = project.director_recipe === 'off' ? 'auto' : project.director_recipe || 'auto';
    document.querySelectorAll('[data-engine]').forEach(b => { const yes = b.dataset.engine === engine; b.classList.toggle('selected',yes); b.setAttribute('aria-pressed',String(yes)); }); document.querySelectorAll('[data-content]').forEach(b => { const yes = b.dataset.content === content; b.classList.toggle('selected',yes); b.setAttribute('aria-pressed',String(yes)); });
    $('#review-link').href = $('#advanced-link').href = `/?project=${encodeURIComponent(pid)}`;
    await refresh(); try { const d = JSON.parse(localStorage.getItem(draftKey()) || 'null'); if(d && (d.brief !== $('#brief').value || d.target_s !== Number($('#duration').value) || d.engine !== engine || d.content !== content)) { $('#brief').value = d.brief; $('#duration').value = String(d.target_s); engine = d.engine; content = d.content; invalidate(); } } catch {} if(['preview_ready','blocked','stale','previewing'].includes(workflow.state)) showStep(5); if(['producing','production_done'].includes(workflow.state)) showStep(6);
  } catch(e) { notice(e.message); } finally { renderControls(); }
}
init();
