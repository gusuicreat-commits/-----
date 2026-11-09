import {orbit,clamp,esc} from './common.js';
export {setup} from './common.js';
const letters=(text,t,delay=0)=>[...text].map((s,i)=>`<span class="letter" style="opacity:${clamp((t-delay-i*.055)/.4)}">${esc(s)}</span>`).join('');
export function render(ctx,shot,t,dur){const target=ctx.center.clone();target.y=ctx.size.y*.69;orbit(ctx,-12,-8,1.5-t/dur*.04,target);ctx.renderer.toneMappingExposure=.6;ctx.content.innerHTML=`<div class="hero opening"><div class="eyebrow">工程纪实 / 结构与尺度</div><h1>${letters(shot.params.title||'工程的尺度',t)}</h1><p>${letters(shot.params.subtitle||'让真实参数，成为看得见的震撼。',t,.35)}</p></div>`;}
