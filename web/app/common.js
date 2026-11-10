export const $ = (selector, root = document) => root.querySelector(selector);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const stages = [['ingest','资料入库','▤'],['model','三维模型','◇'],['plan','分镜规划','▦'],['validate','真实性校验','✓'],['tts','配音','♫'],['render','渲染','▣'],['compose','合成','▧'],['qa','画面质检','◎'],['report','溯源报告','▥']];
export const stageLabel = stage => stages.find(([id]) => id === stage)?.[1] || stage || '准备中';
export const displayIssue = issue => issue.severity === 'warn' && issue.code === 'VISUAL_QA' && issue.message?.includes('缺少录制')
  ? {...issue, severity:'info', message:'回放模式未录制画面质检', hint:''} : issue;
export const kinds = {title:'标题',model_orbit:'环绕展示',analogy:'尺寸类比',motion:'运动演示',exploded:'结构拆解',data_card:'参数卡',real_media:'实拍',ai_broll:'AI创意',weld_macro:'焊缝特写',outro:'片尾'};
export const statuses = {verified:'已核验',needs_review:'待确认',confirmed:'人工确认',rejected:'已否决',pending:'待复核',approved:'已通过',changes:'需修改',running:'运行中',paused:'等待复核',done:'已完成',error:'运行失败',ok:'完成',warn:'需关注'};
export const pill = status => `<span class="pill ${esc(status)}">${esc(statuses[status] || status)}</span>`;
export const fileURL = (pid, path) => `/files/${encodeURIComponent(pid)}/${path.split('/').map(encodeURIComponent).join('/')}`;
export function toast(message) { const el = document.createElement('div'); el.className = 'toast'; el.textContent = message; $('#toasts').append(el); setTimeout(() => el.remove(), 7000); }
export async function request(url, options = {}, optional = false) {
  let response;
  try { response = await fetch(url, options); } catch { throw new Error('网络连接失败，请检查后端服务'); }
  if (optional && response.status === 404) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(data?.error || `请求失败（${response.status}）`);
  return data;
}
export const jsonOptions = (method, data) => ({method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
export async function busy(button, task) { if (button.disabled) return; button.disabled = true; button.classList.add('working'); try { await task(); } catch (error) { toast(error.message); } finally { button.disabled = false; button.classList.remove('working'); } }
export function stored(key, fallback = null) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
export function persist(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 本地存储不可用时仍可操作。 */ } }
export function mergeEvents(events) {
  const calls = [], open = new Map();
  for (const event of events) {
    const key = `${event.run}:${event.tool}:${event.detail?.shot || ''}`;
    const progress = event.tool === 'render.player' && (event.detail?.progress != null || event.detail?.frame != null);
    let item = open.get(key);
    if (event.status === 'start' && !progress) {
      item = {...event, started: event.ts, updates: [event]}; calls.push(item); open.set(key, item);
    } else if (item) {
      item.updates.push(event); Object.assign(item, event);
      if (!progress && event.status !== 'start') { item.elapsed = Math.max(0, (Date.parse(event.ts) - Date.parse(item.started)) / 1000); open.delete(key); }
    } else { calls.push({...event, updates:[event]}); }
  }
  return calls;
}

export function generationProgress(state) {
  const run = state.run || {};
  const events = (state.events || []).filter(e => run.run && e.run === run.run);
  const stage = run.stage;
  const current = events.filter(e => e.stage === stage);
  const detail = current.findLast(e => e.detail?.frame != null || e.detail?.progress != null)?.detail || {};
  const hasFrames = Number.isFinite(detail.frame) && Number.isFinite(detail.total) && detail.total > 0;
  const percent = hasFrames ? detail.frame / detail.total * 100 : detail.progress;
  const completed = stages.filter(([id], index) => id !== stage && (
    run.stage_durations_s?.[id] != null || (index < stages.findIndex(([key]) => key === stage) && events.some(e => e.stage === id && ['ok','warn'].includes(e.status)))
  ));
  return {label: stageLabel(stage), completed,
    percent: Number.isFinite(percent) ? Math.max(0, Math.min(100, percent)) : null,
    progress: hasFrames ? `已渲染 ${detail.frame} / ${detail.total} 帧` : Number.isFinite(percent) ? `已完成 ${percent}%` : '正在处理，请稍候',
    summary: current.at(-1)?.summary || '正在准备本次生成任务'};
}

// 报告负责费用汇总；接口返回的完整摘要用于确认回放模式。
export async function readCallLogs(pid, read = request) {
  const data = await read(`/api/projects/${encodeURIComponent(pid)}/llm`);
  return data.calls;
}

export function costSummary(llm, logs = []) {
  if (!llm) return '';
  const cost = costDetail(llm, logs);
  return cost.startsWith('回放模式') ? cost : `大模型调用 ${llm.calls} 次 · ${cost}`;
}

export function costDetail(llm, logs = []) {
  if (!llm) return '费用待统计';
  if (logs.length > 0 && logs.every(log => log.backend === 'replay')) return '回放模式 · 不产生费用';
  const cost = Number.isFinite(llm.cost_usd) ? `已知费用 $${llm.cost_usd.toFixed(4)}` : '费用待统计';
  return `${cost}${llm.unknown_cost_calls ? ` · ${llm.unknown_cost_calls} 次费用未知，未计入合计` : ''}`;
}

export function toolSummary(events, llm, logs = [], now = Date.now()) {
  const calls = mergeEvents(events), models = calls.filter(e => e.tool.startsWith('llm.')).length;
  // 每次运行取事件的时间跨度，避免并发工具耗时重复累加。
  const runs = new Map();
  for (const event of events) {
    const time = Date.parse(event.ts); if (!Number.isFinite(time)) continue;
    const span = runs.get(event.run) || [time, time];
    runs.set(event.run, [Math.min(span[0], time), Math.max(span[1], time)]);
  }
  for (const call of calls.filter(e => e.status === 'start')) {
    const span = runs.get(call.run); if (span) span[1] = Math.max(span[1], now);
  }
  const seconds = [...runs.values()].reduce((total, [start, end]) => total + (end - start) / 1000, 0);
  return `大模型 ${models} 次 · 程序工具 ${calls.length - models} 次 · 总耗时 ${seconds.toFixed(1)} 秒 · ${costDetail(llm, logs)}`;
}
