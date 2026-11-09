import * as THREE from 'three';
import {frameParallel,clamp,esc} from './common.js';
export {setup} from './common.js';
const letters=(text,t,delay=0)=>[...text].map((s,i)=>`<span class="letter" style="opacity:${clamp((t-delay-i*.055)/.4)}">${esc(s)}</span>`).join('');
export function render(ctx,shot,t,dur){
 ctx.content.innerHTML=`<div class="hero opening"><div class="eyebrow">工程纪实 / 结构与尺度</div><h1>${letters(shot.params.title||'工程的尺度',t)}</h1><p>${letters(shot.params.subtitle||'让真实参数，成为看得见的震撼。',t,.35)}</p></div>`;
 const bounds=new THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')||ctx.model);
 if(bounds.isEmpty())bounds.setFromCenterAndSize(ctx.center,ctx.size);
 // 左侧文字与右下模型各自保留完整投影空间。
 frameParallel(ctx,bounds,{angle:-12,elevation:12,width:.50,cx:.70,cy:.56});
 ctx.renderer.toneMappingExposure=1.15;
}
