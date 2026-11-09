import {$, esc, pill, fileURL, jsonOptions, busy, stored, persist, toast} from './common.js';

export function createResources(ctx) {
  let tab = 'facts', signature = '', disposeModel = () => {};
  const root = $('#resource-content');
  const docsFor = () => {
    const docs = new Map(stored(`kepu.docs.${ctx.state.pid}`, []).map(d => [d.name, d]));
    for (const fact of ctx.state.facts) if (fact.source?.doc && !docs.has(fact.source.doc)) docs.set(fact.source.doc, {name:fact.source.doc});
    return [...docs.values()];
  };
  function rememberDoc(name, extra = {}) {
    const docs = docsFor(), existing = docs.find(d => d.name === name);
    if (existing) Object.assign(existing, extra); else docs.push({name, ...extra});
    persist(`kepu.docs.${ctx.state.pid}`, docs); signature = '';
  }
  function factsHTML() {
    const facts = ctx.state.facts;
    if (!facts.length) return '<div class="empty-note"><b>参数从资料中来</b><p>上传 PDF 或载入示例项目，再提取参数。每条数值都会保留文档、页码和原文摘录。</p><button data-go-docs>上传 / 提取文档</button></div>';
    return `<p class="stats">共 ${facts.length} 条 · 已核验 ${facts.filter(f => f.status === 'verified').length} · 待确认 ${facts.filter(f => f.status === 'needs_review').length}</p>${facts.map(f => `<article class="fact-row ${f.status === 'needs_review' ? 'attention' : ''}" data-fact="${esc(f.id)}"><details><summary title="${esc(`${f.source?.doc || '出处待补充'} · 第${f.source?.page ?? '？'}页：${f.source?.quote || ''}`)}"><span>${esc(f.name)}</span><strong class="fact-value">${esc(f.value)}<small>${esc(f.unit)}</small></strong><span class="fact-page muted">第${esc(f.source?.page ?? '？')}页</span></summary><div class="fact-source"><a target="_blank" rel="noopener" href="${fileURL(ctx.state.pid, `docs/${f.source?.doc || ''}`)}#page=${encodeURIComponent(f.source?.page || 1)}">${esc(f.source?.doc)} · 第${esc(f.source?.page)}页 ↗</a><blockquote>${esc(f.source?.quote || '原文待补充')}</blockquote></div></details><div class="fact-actions">${pill(f.status)}${f.status === 'needs_review' ? '<button data-fact-action="confirmed" class="success">确认</button><button data-fact-action="rejected" class="danger">否决</button>' : ''}<button data-fact-action="edit">修改</button><form class="fact-edit" hidden><input name="value" type="number" step="any" required aria-label="参数数值" value="${esc(f.value)}"><input name="unit" aria-label="参数单位" value="${esc(f.unit)}"><button type="submit">保存</button><button type="button" data-fact-action="cancel">取消</button></form></div></article>`).join('')}`;
  }
  function docsHTML() {
    const docs = docsFor();
    return `<label class="drop-zone" tabindex="0">↑<strong>拖入 PDF，建立参数依据</strong><span>或点击选择文件</span><input id="pdf-upload" type="file" accept=".pdf" hidden ${!ctx.state.pid ? 'disabled' : ''}></label><p class="muted">共 ${docs.length} 份文档</p><div class="doc-list">${docs.map(d => `<article class="doc-card"><span class="doc-icon">PDF</span><div><a target="_blank" rel="noopener" href="${fileURL(ctx.state.pid, `docs/${d.name}`)}">${esc(d.name)}</a><p class="muted">${d.pages ? `${d.pages} 页` : '页数待解析'} · ${d.parsing ? '正在解析…' : d.failed ? '解析失败，可重试' : '已入库'}</p></div><button data-extract="${esc(d.name)}" ${d.parsing ? 'disabled' : ''}>提取参数</button></article>`).join('') || '<p class="empty-note">暂无文档，请先选择项目或载入示例项目。</p>'}</div>`;
  }
  function assetsHTML() {
    return `<p class="stats">共 ${ctx.state.assets.length} 张素材 · 来源单独标记</p><div class="asset-grid">${ctx.state.assets.map(a => `<article class="asset-card" data-asset="${esc(a.id)}"><div class="asset-picture">${a.kind === 'video' ? `<video src="${fileURL(ctx.state.pid,a.file)}" muted preload="metadata" controls></video>` : `<img src="${fileURL(ctx.state.pid,a.file)}" alt="${esc(a.title)}" loading="lazy">`}<span class="source-badge ${a.provenance === 'own' ? 'own' : 'reference'}">${a.provenance === 'own' ? '本机实拍' : '参考实拍·非本机'}</span></div><strong>${esc(a.title || a.id)}</strong><p class="credit" title="${esc(a.credit)}">${esc(a.credit || '未填写署名')}</p></article>`).join('')}</div><details class="upload-form"><summary>＋ 上传素材</summary><form id="asset-upload"><label>素材文件<input name="file" type="file" accept="image/*,video/*" required></label><fieldset><legend>来源</legend><label><input type="radio" name="provenance" value="own" checked> 本机实拍</label><label><input type="radio" name="provenance" value="reference"> 参考实拍</label></fieldset><label>标题<input name="title" required placeholder="说明画面内容"></label><label>标签<input name="tags" placeholder="多个标签用英文逗号分隔"></label><label>署名<input name="credit" placeholder="作者 / 许可证 / 来源链接"></label><button class="primary" ${!ctx.state.pid ? 'disabled' : ''}>上传素材</button></form></details>`;
  }
  function modelHTML() {
    const model = ctx.state.project?.model;
    const facts = Object.fromEntries(ctx.state.facts.map(f => [f.id, f]));
    return `<div class="model-toolbar"><label class="button">上传 STEP<input id="step-upload" type="file" accept=".step,.stp" hidden ${!ctx.state.pid ? 'disabled' : ''}></label><button id="rebuild" ${!ctx.state.pid ? 'disabled' : ''}>按参数重建</button></div>${model ? `<h3>${model.kind === 'step' ? 'STEP 导入' : '参数化重建'}</h3><div id="model-preview" class="model-preview"><p class="muted">正在加载三维预览…</p></div><p class="muted">可拖动查看 · 自动缓慢旋转</p><h4>依据参数</h4><div class="model-facts">${(model.derived_from || []).map(id => `<span class="pill verified" title="${esc(id)}">${esc(facts[id]?.name || id)}${facts[id] ? ` · ${esc(facts[id].value)} ${esc(facts[id].unit)}` : ''}</span>`).join('') || '<span class="muted">无已核验参数</span>'}</div>${model.assumed?.length ? `<p class="warn">默认假设（assumed）：${model.assumed.map(esc).join('、')}</p>` : ''}<h4>尺寸核验</h4>${(model.dims_check || []).map(c => `<p class="${c.ok ? 'ok' : 'error'}">${c.ok ? '✓' : '✗'} ${esc(facts[c.fact]?.name || c.fact)}：${esc(c.message || `模型 ${c.model_value} m / 文档 ${c.doc_value} m`)}</p>`).join('') || '<p class="muted">暂无尺寸核验结果</p>'}<h4>模型节点</h4><div id="model-nodes" class="node-list muted">加载模型后显示实际节点</div>` : '<p class="empty-note">提取并确认参数后，重建可溯源的三维模型；也可以上传 STEP。</p>'}`;
  }
  function render(force = false) {
    const next = JSON.stringify([ctx.state.pid, tab, ctx.state.facts, ctx.state.assets, ctx.state.project?.model, docsFor()]);
    if (!force && next === signature) return;
    signature = next; disposeModel(); disposeModel = () => {};
    root.innerHTML = ({facts:factsHTML, docs:docsHTML, assets:assetsHTML, model:modelHTML})[tab]();
    if (tab === 'model' && ctx.state.project?.model) {
      const host = $('#model-preview'), pid = ctx.state.pid;
      import('./model-preview.js').then(async ({mountModel}) => {
        if (!host.isConnected || pid !== ctx.state.pid) return;
        const dispose = await mountModel(host, fileURL(pid, ctx.state.project.model.glb), nodes => {
          if (host.isConnected) $('#model-nodes').textContent = nodes.join(' · ') || '模型没有命名节点';
        });
        if (!host.isConnected || pid !== ctx.state.pid) dispose(); else disposeModel = dispose;
      }).catch(() => { if (host.isConnected) host.textContent = '三维预览不可用，请检查模型或浏览器图形支持'; });
    }
  }
  function select(value) { tab = value; document.querySelectorAll('[data-tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.tab === value))); render(); }
  async function uploadPDF(file) {
    if (!ctx.state.pid) { toast('请先选择项目或载入示例项目'); return; }
    if (!file?.name.toLowerCase().endsWith('.pdf')) { toast('请选择 PDF 文档'); return; }
    const pid = ctx.state.pid, data = new FormData(); data.append('file', file);
    rememberDoc(file.name, {parsing:true}); render();
    try { await ctx.api('/docs', {method:'POST',body:data}); }
    catch (error) { if (pid === ctx.state.pid) { rememberDoc(file.name,{parsing:false,failed:true}); render(); } throw error; }
  }
  root.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button) return;
    if (button.hasAttribute('data-go-docs')) return select('docs');
    const row = button.closest('[data-fact]');
    if (row && button.dataset.factAction) {
      const action = button.dataset.factAction;
      if (action === 'edit' || action === 'cancel') { $('.fact-edit',row).hidden = action === 'cancel'; if (action === 'edit') $('input',row).focus(); return; }
      await busy(button, async () => { await ctx.api(`/facts/${encodeURIComponent(row.dataset.fact)}`, jsonOptions('PATCH',{status:action})); await ctx.refresh(); });
    }
    if (button.dataset.extract) await busy(button, async () => {
      const name = button.dataset.extract, pid = ctx.state.pid;
      rememberDoc(name,{parsing:true,failed:false}); render();
      try {
        const response = await fetch(fileURL(pid, `docs/${name}`)).catch(() => { throw new Error('读取文档失败，请检查网络连接'); });
        if (!response.ok) throw new Error('读取文档失败，请重新上传');
        const data = new FormData(); data.append('file', new File([await response.blob()],name,{type:'application/pdf'}));
        await ctx.api('/docs', {method:'POST',body:data});
      } catch (error) { if (pid === ctx.state.pid) { rememberDoc(name,{parsing:false,failed:true}); render(); } throw error; }
    });
    if (button.id === 'rebuild') await busy(button,async () => { await ctx.api('/model/parametric',{method:'POST'}); await ctx.refresh(); });
  });
  root.addEventListener('submit', event => {
    event.preventDefault(); const form = event.target, button = $('button[type="submit"],button.primary',form);
    if (form.matches('.fact-edit')) busy(button,async () => { const data = new FormData(form); await ctx.api(`/facts/${encodeURIComponent(form.closest('[data-fact]').dataset.fact)}`,jsonOptions('PATCH',{value:Number(data.get('value')),unit:data.get('unit')})); await ctx.refresh(); });
    if (form.id === 'asset-upload') busy(button,async () => { await ctx.api('/assets',{method:'POST',body:new FormData(form)}); await ctx.refresh(); });
  });
  root.addEventListener('change', event => {
    const input = event.target;
    if (input.name === 'provenance') $('[name="credit"]',input.form).required = input.value === 'reference';
    if (input.id === 'pdf-upload' && input.files[0]) uploadPDF(input.files[0]).catch(e => toast(e.message));
    if (input.id === 'step-upload' && input.files[0]) { const data = new FormData(); data.append('file',input.files[0]); input.disabled = true; ctx.api('/model/step',{method:'POST',body:data}).then(() => ctx.refresh()).catch(e => toast(e.message)).finally(() => { input.disabled = false; }); }
  });
  root.addEventListener('keydown', event => { if (event.target.matches('.drop-zone') && ['Enter',' '].includes(event.key)) { event.preventDefault(); $('#pdf-upload').click(); } });
  root.addEventListener('dragover', event => { if (event.target.closest('.drop-zone')) { event.preventDefault(); event.target.closest('.drop-zone').classList.add('dragging'); } });
  root.addEventListener('dragleave', event => event.target.closest('.drop-zone')?.classList.remove('dragging'));
  root.addEventListener('drop', event => { if (event.target.closest('.drop-zone')) { event.preventDefault(); event.target.closest('.drop-zone').classList.remove('dragging'); uploadPDF(event.dataTransfer.files[0]).catch(e => toast(e.message)); } });
  document.querySelectorAll('[data-tab]').forEach(button => button.addEventListener('click',() => select(button.dataset.tab)));
  return {render, select, rememberDoc, onEvent(event) {
    if (event.tool === 'pdf.extract' && event.status === 'start' && docsFor().length === 1) rememberDoc(docsFor()[0].name,{parsing:true,failed:false});
    const parsing = docsFor().filter(d => d.parsing);
    if (event.tool === 'pdf.extract' && event.status === 'ok' && parsing.length === 1) {
      const pages = event.summary.match(/(\d+)\s*页/); if (pages) rememberDoc(parsing[0].name,{pages:Number(pages[1])});
    }
    if (event.tool === 'verify.facts' && ['ok','warn'].includes(event.status) || event.stage === 'ingest' && event.status === 'error') {
      parsing.forEach(d => rememberDoc(d.name,{parsing:false,failed:event.status === 'error'}));
    }
  }};
}
