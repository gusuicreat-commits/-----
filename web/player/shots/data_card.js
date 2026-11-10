import {orbit,clamp,esc,source} from './common.js';
export {setup} from './common.js';
export function render(ctx,shot,t,dur){
 if(!shot.bg){const target=ctx.center.clone();target.x-=27;orbit(ctx,-8+t/dur*10,16,1.48,target);}
 const facts=(shot.params.facts||[]).map(id=>ctx.timeline.facts[id]).filter(Boolean);
 ctx.content.innerHTML=`<div class="data-panel${facts.length>=4?' data-grid':''}" data-count="${facts.length}"><h2>关键参数</h2><div class="data-items">${facts.map((f,i)=>`<div class="data-card" style="opacity:${clamp((t-i*.3)/.45)}"><div class="name">${esc(f.name)}</div><div class="data-value"><span class="value">${esc(f.value)}</span><span class="unit">${esc(f.unit)}</span></div><div class="source">${source(f)}</div></div>`).join('')}</div></div>`;
}
// 字幕更新后测量，同样适用于乱序定位和两行字幕。
export function fitPanel(content,caption){
 const panel=content.querySelector('.data-panel');if(!panel)return;
 const captionTop=caption.textContent?caption.offsetTop:890;
 const available=captionTop-16-panel.offsetTop;
 panel.style.maxHeight='none';
 panel.style.transform='';
 // 保留完整来源行；特别长的资料名在必要时等比收拢整卡。
 const height=panel.offsetHeight;
 if(height>available)panel.style.transform=`scale(${available/height})`;
}
