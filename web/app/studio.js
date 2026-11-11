import {$, esc, kinds, pill, fileURL, jsonOptions, busy, toast, generationProgress, displayIssue} from './common.js';
const units = {m:'米',t:'吨',mm:'毫米','m/min':'米/分钟'};
export function narrationHTML(text, facts, analogies) {
  return String(text || '').split(/(\{\{[FA]_[a-zA-Z0-9_]+\}\})/g).map(part => {
    const id = part.match(/^\{\{(.+)\}\}$/)?.[1]; if (!id) return esc(part);
    const fact = facts.find(f => f.id === id), analogy = analogies.find(a => a.id === id);
    const basis = facts.find(f => f.id === analogy?.fact);
    const label = fact ? `${fact.value}${units[fact.unit] || fact.unit} · 第${fact.source?.page ?? '？'}页` : analogy?.text || id;
    const detail = fact ? `${fact.source?.doc} · 第${fact.source?.page}页\n${fact.source?.quote || '原文待补充'}` : analogy ? `${analogy.formula || `比例 ${analogy.ratio} = 参数值 ÷ 参照尺寸`}\n${analogy.basis || '参照依据待补充'}\n依据：${basis?.name || analogy.fact} ${basis?.value ?? ''}${basis?.unit || ''} · 第${basis?.source?.page ?? '？'}页` : '引用缺失，请人工核对';
    return `<span class="citation-wrap"><button class="citation ${fact ? 'fact' : 'analogy'}" data-citation="${esc(id)}" aria-label="${esc(label)}">${esc(label)}</button><span role="tooltip" class="citation-tooltip">${esc(detail)}</span></span>`;
  }).join('');
}
export function createStudio(ctx) {
  let selected = null, signature = '', previewKey = '', unsubscribe = () => {}, editing = false, readyPlayer = null;
  const getShots = () => ctx.state.shotlist.shots || [];
  function timeline() {
    const shots = getShots().length ? getShots() : ctx.state.timeline.shots || [];
    $('#shot-count').textContent = shots.length ? `· ${shots.length} 个镜头` : '';
    $('#timeline').innerHTML = shots.map((shot,index) => {
      const timed = ctx.state.timeline.shots?.find(s => s.id === shot.id), duration = timed ? timed.end-timed.start : shot.duration_s || 0;
      const issues = ctx.state.issues.map(displayIssue).filter(i => i.shot === shot.id), blocks = issues.filter(i => i.severity === 'block').length, warns = issues.filter(i => i.severity === 'warn').length;
      return `<button class="shot-card source-${esc(shot.source)} ${shot.id === selected ? 'selected' : ''}" data-shot="${esc(shot.id)}" aria-pressed="${shot.id === selected}" style="flex-basis:${Math.max(72,duration*15)}px;flex-grow:${Math.max(0,duration)}"><span class="shot-number">${String(index+1).padStart(2,'0')}<span class="review-dot ${esc(shot.review?.status || 'pending')}" aria-label="${shot.review?.status === 'approved' ? '已通过' : '待复核'}"></span></span><strong>${esc(kinds[shot.kind] || shot.kind)}</strong><span class="shot-duration">${duration.toFixed(1)} 秒</span><span class="issue-badges">${blocks ? `<b class="block">${blocks}</b>` : ''}${warns ? `<b class="warn">${warns}</b>` : ''}</span></button>`;
    }).join('') || '<p class="empty-note">生成分镜后，可逐镜头查看台词、出处与复核状态。</p>';
  }
  function detail() {
    const shot = getShots().find(s => s.id === selected);
    if (!shot) { $('#shot-detail').innerHTML='<div class="detail-empty">选择一个镜头，查看它的资料依据与复核记录。</div>'; return; }
    const analogies = ctx.state.shotlist.analogies || [], issues = ctx.state.issues.map(displayIssue).filter(i => i.shot === shot.id);
    const usedAnalogies = analogies.filter(a => (shot.analogy_refs || []).includes(a.id) || shot.params?.analogy === a.id || shot.narration?.includes(`{{${a.id}}}`));
    const calculations = usedAnalogies.map(a => `<div class="analogy-calculation"><strong>类比算式</strong><p>${esc(a.formula || '算式待补充')}</p><small>${esc(a.basis || '参照依据待补充')}</small></div>`).join('');
    const asset = ctx.state.assets.find(a => a.id === shot.params?.asset);
    const labels = {title:'标题',subtitle:'副标题',from_deg:'起始角度',to_deg:'结束角度',elevation_deg:'仰角',distance:'相对距离',highlight:'高亮节点',analogy:'类比依据',axis:'运动轴',from_m:'起点（米）',to_m:'终点（米）',speedup:'演示倍速',parts:'拆解部件',spread_m:'展开距离（米）',facts:'引用参数',asset:'素材编号',effect:'画面效果',caption:'画面说明',recipe:'创意场景',palette:'色调',prompt:'画面描述',fact:'参数依据'};
    $('#shot-detail').innerHTML = `<div class="detail-heading"><h3><code>${esc(shot.id)}</code> ${esc(kinds[shot.kind])}</h3>${pill(shot.review?.status || 'pending')}</div><div class="narration-heading"><h4>台词与出处</h4><button id="edit-narration">编辑台词</button></div><div id="narration-view" class="narration">${narrationHTML(shot.narration,ctx.state.facts,analogies)}</div><form id="narration-form" hidden><textarea name="narration" aria-label="台词编辑" rows="4" required>${esc(shot.narration)}</textarea><div class="actions"><button class="primary" type="submit">保存台词</button><button id="cancel-edit" type="button">取消</button></div></form><p class="resolved">${esc(shot.narration_resolved || '保存后从真实性校验重跑，以更新解析台词与成片。')}</p>${calculations}<details class="shot-params" open><summary>镜头参数</summary><dl>${Object.entries(shot.params || {}).map(([key,value]) => `<div><dt>${esc(labels[key] || key)}</dt><dd>${esc(key === 'speedup' ? `×${value} 倍速` : typeof value === 'object' ? JSON.stringify(value) : value)}</dd></div>`).join('') || '<span class="muted">无额外参数</span>'}</dl>${asset ? `<div class="shot-asset">${asset.kind === 'video' ? `<video src="${fileURL(ctx.state.pid,asset.file)}" controls></video>` : `<img src="${fileURL(ctx.state.pid,asset.file)}" alt="${esc(asset.title)}">`}<div>${esc(asset.title)}<p class="credit">${esc(asset.credit)}</p></div></div>` : ''}</details><div class="shot-issues">${issues.map(i => `<p class="${esc(i.severity)}"><code>${esc(i.code)}</code> ${esc(i.message)}<small>${esc(i.hint)}</small></p>`).join('')}</div><section class="review-section"><h4>人工复核</h4><input id="review-note" aria-label="复核备注" placeholder="留下复核依据或修改建议" value="${esc(shot.review?.note || '')}"><div class="actions"><button class="success" data-review="approved">✓ 通过</button><button data-review="changes">需修改</button></div><form id="revise-form"><label for="revision-instruction">让智能体改写</label><div class="revise-row"><input id="revision-instruction" name="instruction" required placeholder="例如：保留参数依据，让台词更口语化"><button type="submit" class="ai-button">改写</button></div></form></section>`;
  }
  function select(id, seek = false) {
    if (!getShots().some(s => s.id === id)) { toast(`找不到镜头 ${id}，请刷新分镜后重试`); return; }
    selected = id; editing = false; timeline(); detail();
    if (seek) {
      const shot = ctx.state.timeline.shots?.find(s => s.id === id), player = $('#player-frame')?.contentWindow?.__player;
      if (!shot) { toast(`时间线尚未包含镜头 ${id}，请生成或更新预览`); return; }
      const film = $('#scale-film-preview');
      if(film) { film.currentTime=Math.min(shot.start+.6,shot.end-.05); return; }
      if (!player || player !== readyPlayer) { toast('播放器尚未就绪，请等待加载完成后重试'); return; }
      Promise.resolve().then(() => player.seek(Math.min(shot.start + 0.6, shot.end - 0.05))).catch(() => toast('播放器跳转失败，请检查时间线'));
    }
  }
  function preview() {
    const running = ctx.isRunning(), progress = running ? generationProgress(ctx.state) : null;
    const host = $('#preview');
    const placeholder = html => {
      let status = $('#preview-status');
      if (!status) { status = document.createElement('div'); status.id = 'preview-status'; host.append(status); }
      if (status.innerHTML !== html) status.innerHTML = html;
      const frame = $('#player-frame'); if (frame) frame.hidden = true;
      const film = $('#scale-film-preview'); if(film) { film.pause(); film.hidden=true; }
    };
    if (ctx.state.pid && !ctx.state.timelineLoaded) {
      placeholder('<div class="preview-empty" role="status">正在加载时间线…</div>');
      return;
    }
    const exists = ctx.state.timeline.shots?.length;
    if (running) {
      placeholder(`<div class="preview-empty preview-running" role="status"><span class="eyebrow">智能体正在生成视频</span><h2>正在生成：${esc(progress.label)}</h2><progress max="100" ${progress.percent != null ? `value="${progress.percent}"` : ''} aria-label="当前阶段进度"></progress><p>${esc(progress.progress)}</p><p class="generation-summary">${esc(progress.summary)}</p><ul class="completed-stages" aria-label="已完成阶段">${progress.completed.map(([,label]) => `<li>✓ ${esc(label)}</li>`).join('')}</ul></div>`);
      return;
    }
    if(ctx.state.project?.render_mode==='scale_film') {
      const current=ctx.state.project.scale_film_ready===true && ctx.state.timeline.render_mode==='scale_film' && ctx.state.run.state==='done';
      if(!current) {
        const message=ctx.state.run.state==='error'?'本轮制作未完成。请查看右侧原因，修正后重跑。':ctx.state.timeline.render_mode==='scale_film'?'参数或分镜已有变化，需重新生成当前版本；旧片不会作为新结果展示。':'选择好参数与目标时长，从分镜规划生成尺度短片；成片完成后将在这里播放。';
        placeholder(`<div class="preview-empty" role="status"><span class="eyebrow">主梁尺度短片</span><h2>从一个数字，到看得见的长度</h2><p>${message}</p></div>`);
        return;
      }
      const key=JSON.stringify([ctx.state.pid,ctx.state.run.run,ctx.state.run.finished_at]);
      $('#preview-status')?.remove();
      const existing=$('#scale-film-preview');
      if(existing && key===previewKey) { existing.hidden=false; return; }
      unsubscribe();unsubscribe=()=>{};readyPlayer=null;previewKey=key;
      const film=document.createElement('video');film.id='scale-film-preview';film.controls=true;film.playsInline=true;film.preload='metadata';film.setAttribute('aria-label','尺度短片成片');
      film.src=`${fileURL(ctx.state.pid,'renders/final.mp4')}?v=${encodeURIComponent(ctx.state.run.run || '')}`;
      film.addEventListener('timeupdate',()=>{
        const shot=ctx.state.timeline.shots?.find(s=>film.currentTime>=s.start && film.currentTime<s.end);
        if(!shot)return;
        if(shot.id!==selected && !editing && !$('#shot-detail').contains(document.activeElement))select(shot.id);
        document.querySelectorAll('.shot-card').forEach(card=>card.classList.toggle('playing',card.dataset.shot===shot.id));
      });
      film.addEventListener('error',()=>toast('成片加载失败，请检查本轮渲染与合成结果'));
      host.replaceChildren(film);return;
    }
    if (!exists) {
      if ($('#player-frame')) { unsubscribe(); unsubscribe = () => {}; readyPlayer = null; previewKey = ''; host.replaceChildren(); }
      placeholder('<div class="preview-empty"><div class="crane-symbol" aria-hidden="true"><i></i><i></i><i></i><i></i></div><span class="eyebrow">从真实资料，到可信画面</span><h2>让重器的每一处细节，有据可循</h2><p>上传资料 <span>→</span> 生成视频 <span>→</span> 人工复核</p><button class="primary" data-action="seed">载入示例项目</button></div>');
      return;
    }
    $('#preview-status')?.remove();
    const {shots, captions, audio} = ctx.state.timeline;
    const key = JSON.stringify([ctx.state.pid, shots, captions, audio]);
    const existing = $('#player-frame');
    if (existing && key === previewKey) { existing.hidden = false; return; }
    previewKey = key; unsubscribe(); unsubscribe = () => {}; readyPlayer = null;
    const iframe = document.createElement('iframe'); iframe.id='player-frame'; iframe.title='成片预览播放器'; iframe.allow='autoplay';
    iframe.src=`/player/index.html?timeline=${encodeURIComponent(fileURL(ctx.state.pid,'timeline.json'))}&mode=preview&v=${Date.now()}`;
    iframe.addEventListener('load',async () => {
      try {
        const player = iframe.contentWindow.__player; if (!player) throw new Error();
        await player.ready; if (!iframe.isConnected) return;
        readyPlayer = player;
        iframe.dataset.ready = '1';
        unsubscribe = player.on?.('shot',shot => {
          if (shot.id !== selected && !editing && !$('#shot-detail').contains(document.activeElement)) select(shot.id);
          document.querySelectorAll('.shot-card').forEach(card => card.classList.toggle('playing',card.dataset.shot===shot.id));
        }) || (() => {});
      } catch { if (iframe.isConnected) toast('播放器加载失败，请检查模型与时间线文件'); }
    });
    $('#preview').replaceChildren(iframe);
  }
  function render() {
    preview();
    const ready = ctx.state.project?.render_mode==='scale_film' ? ctx.state.project.scale_film_ready===true && ctx.state.run.state==='done' : ctx.state.run.state === 'done' || Boolean(ctx.state.report.generated_at);
    $('#film-links').innerHTML = ready ? `<a class="button primary" href="${fileURL(ctx.state.pid,'renders/final.mp4')}" download>↓ 下载成片</a><a class="button" target="_blank" rel="noopener" href="${fileURL(ctx.state.pid,'report.html')}">查看溯源报告 ↗</a>` : '';
    const next = JSON.stringify([ctx.state.pid, ctx.state.shotlist, ctx.state.timeline, ctx.state.issues, ctx.state.facts]);
    if (next !== signature) { signature = next; if (!getShots().some(s => s.id === selected)) selected = getShots()[0]?.id || null; timeline(); if (!editing && !$('#shot-detail').contains(document.activeElement)) detail(); }
  }
  $('#timeline').addEventListener('click',event => { const card=event.target.closest('[data-shot]'); if(card) select(card.dataset.shot,true); });
  $('#shot-detail').addEventListener('click',event => {
    const button=event.target.closest('button'); if(!button) return;
    if(button.id==='edit-narration' || button.id==='cancel-edit') { editing=button.id==='edit-narration'; $('#narration-form').hidden=!editing; $('#narration-view').hidden=editing; if(editing) $('textarea').focus(); }
    if(button.dataset.citation) { if(button.dataset.citation.startsWith('F_')) { ctx.resources.select('facts'); const row=[...document.querySelectorAll('[data-fact]')].find(r=>r.dataset.fact===button.dataset.citation); if(row) { $('details',row).open=true; row.scrollIntoView({block:'nearest',behavior:'smooth'}); } } else button.parentElement.classList.toggle('pinned'); }
    if(button.dataset.review) busy(button,async()=> { const sid=selected; await ctx.api(`/shots/${encodeURIComponent(sid)}`,jsonOptions('PATCH',{review:{status:button.dataset.review,note:$('#review-note').value}})); ctx.markEdited(); await ctx.refresh(); if(selected===sid) detail(); });
  });
  $('#shot-detail').addEventListener('submit',event => {
    event.preventDefault(); const form=event.target, sid=selected, button=$('button[type="submit"]',form), data=new FormData(form);
    busy(button,async()=> {
      if(form.id==='narration-form') await ctx.api(`/shots/${encodeURIComponent(sid)}`,jsonOptions('PATCH',{narration:data.get('narration')}));
      else await ctx.api(`/shots/${encodeURIComponent(sid)}/revise`,jsonOptions('POST',{instruction:data.get('instruction')}));
      editing=false; ctx.markEdited(); await ctx.refresh(); if(selected===sid) detail();
    });
  });
  return {render,preview,select,reset(){ unsubscribe(); unsubscribe=()=>{}; $('#preview').replaceChildren(); selected=null; signature=''; editing=false; previewKey=''; readyPlayer=null; }};
}
