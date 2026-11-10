import {$, esc, fileURL, mergeEvents, toast, readCallLogs, costSummary, toolSummary, displayIssue} from './common.js';
export function createAgent(ctx) {
  let source, timer, delay=1000, generation=0, seen=new Set(), openCards=new Set();
  let costKey = '', callLogs = [];
  const stream=$('#event-stream');
  stream.addEventListener('toggle',event => { const id=event.target.dataset.event; if(id) event.target.open ? openCards.add(id) : openCards.delete(id); },true);
  function renderEvents() {
    const bottom=stream.scrollHeight-stream.scrollTop-stream.clientHeight<60;
    const calls=mergeEvents(ctx.state.events);
    renderSummary();
    stream.innerHTML=calls.map((event,index)=>{
      const color=event.tool.startsWith('llm.')?'llm':event.tool.startsWith('model.')?'model':/^(verify|validate)/.test(event.tool)?'verify':'media';
      const status=event.status==='start'?'running':event.status;
      const progress=event.detail?.progress;
      const percent=typeof progress==='number'?Math.min(100,Math.max(0,progress)):null;
      return `<details class="event-card ${esc(status)}" data-event="${index}" ${openCards.has(String(index))?'open':''}><summary><span class="event-icon ${status==='running'?'spinner':''}">${({running:'◌',ok:'✓',warn:'!',error:'×'})[status] || '·'}</span><div class="event-body"><div class="event-meta"><code class="tool ${color}">${esc(event.tool)}</code><time data-ts="${esc(event.ts)}">刚刚</time></div><p>${esc(event.summary)}</p>${event.elapsed>=0.05?`<small class="muted">耗时 ${event.elapsed.toFixed(1)} 秒</small>`:''}${percent!=null?`<progress max="100" value="${percent}" aria-label="渲染进度"></progress>`:''}</div></summary><pre>${esc(JSON.stringify(event.updates.map(e=>({时间:e.ts,详情:e.detail})),null,2))}</pre></details>`;
    }).join('') || '<p class="empty-note">准备好资料后，智能体将在这里展示每一步工具调用。</p>';
    updateTimes(); if(bottom) stream.scrollTo({top:stream.scrollHeight,behavior:'smooth'});
  }
  function renderSummary() { $('#tool-count').textContent=toolSummary(ctx.state.events,ctx.state.report.llm,callLogs); }
  function updateTimes() { renderSummary(); stream.querySelectorAll('time').forEach(el=>{ const seconds=Math.max(0,Math.floor((Date.now()-Date.parse(el.dataset.ts))/1000)); el.textContent=seconds<5?'刚刚':seconds<60?`${seconds}秒前`:seconds<3600?`${Math.floor(seconds/60)}分钟前`:`${Math.floor(seconds/3600)}小时前`; }); }
  function connect() {
    const token=++generation, pid=ctx.state.pid; seen=new Set(); openCards=new Set(); ctx.state.events=[]; renderEvents(); delay=1000;
    source?.close(); clearTimeout(timer); if(!pid) return;
    const open=()=> {
      if(token!==generation) return;
      const connection=new EventSource(`/api/projects/${encodeURIComponent(pid)}/events`);
      source=connection;
      $('#connection').textContent='正在连接';
      connection.onopen=()=>{ if(token!==generation) return; delay=1000; $('#connection').textContent='● 实时连接'; $('#connection').className='ok'; };
      connection.onmessage=message=>{
        if(token!==generation) return;
        let event; try { event=JSON.parse(message.data); } catch { return; }
        const key=JSON.stringify(event); if(seen.has(key)) return; seen.add(key);
        ctx.state.events.push(event); ctx.resources.onEvent(event); renderEvents(); ctx.onEvent(event);
      };
      connection.onerror=()=>{
        connection.close(); if(token!==generation) return;
        if(delay===1000) toast('工具事件连接中断，正在自动重连');
        $('#connection').textContent=`连接中断，${delay/1000} 秒后重连`; $('#connection').className='warn';
        timer=setTimeout(open,delay); delay=Math.min(10000,delay*2);
      };
    }; open();
  }
  function render() {
    const issues=ctx.state.issues.map(displayIssue);
    $('#issue-count').textContent=issues.length;
    const opened=new Set([...$('#issues').querySelectorAll('details[open]')].map(el=>el.dataset.severity));
    const hasPrevious=Boolean($('#issues details'));
    $('#issues').innerHTML=['block','warn','info'].map(level=>{
      const items=issues.filter(i=>i.severity===level); if(!items.length) return '';
      return `<details data-severity="${level}" ${(!hasPrevious || opened.has(level))?'open':''}><summary class="${level}">● ${{block:'阻断',warn:'警告',info:'提示'}[level]} <span>${items.length}</span></summary>${items.map(i=>`<button class="issue-item" data-issue-shot="${esc(i.shot || '')}"><code>${esc(i.code)}</code><span>${esc(i.message)}</span><small>${esc(i.hint)}</small>${i.shot?`<b>定位 ${esc(i.shot)} ↗</b>`:''}</button>`).join('')}</details>`;
    }).join('') || '<p class="muted">暂无校验问题</p>';
    const outputs=[['renders/final.mp4','final.mp4',Boolean(ctx.state.report.generated_at) || ctx.state.run.state==='done'],['report.html','report.html',Boolean(ctx.state.report.generated_at)],['timeline.json','timeline.json',Boolean(ctx.state.timeline.shots?.length)],['shotlist.json','shotlist.json',Boolean(ctx.state.shotlist.shots?.length)]];
    const llm=ctx.state.report.llm;
    const nextCostKey = JSON.stringify([ctx.state.pid, ctx.state.report.generated_at, llm]);
    if (nextCostKey !== costKey) {
      costKey = nextCostKey; callLogs = [];
      if (llm?.calls) readCallLogs(ctx.state.pid).then(logs => {
        if (costKey !== nextCostKey) return;
        callLogs = logs; render();
      }).catch(() => { /* 原始记录不可读时保留报告中的真实费用汇总。 */ });
    }
    renderSummary();
    $('#outputs').innerHTML=`<div class="output-grid">${outputs.map(([path,label,exists])=>exists?`<a href="${fileURL(ctx.state.pid,path)}" target="_blank" rel="noopener"><span>↗</span><code>${label}</code></a>`:`<span class="output-pending"><code>${label}</code><small>待生成</small></span>`).join('')}</div>${llm?`<p class="muted">${esc(costSummary(llm, callLogs))}</p>`:''}`;
  }
  $('#issues').addEventListener('click',event=>{ const item=event.target.closest('[data-issue-shot]'); if(item?.dataset.issueShot) ctx.studio.select(item.dataset.issueShot,true); });
  return {connect,render,updateTimes,close(){generation++; source?.close();clearTimeout(timer);}};
}
