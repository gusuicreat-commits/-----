import {esc,clamp} from './common.js';
export {setup} from './common.js';
export function mediaTitle(value){
 return String(value||'').trim().replace(/^(?:(?:参考实拍|[（(]非本(?:机|设备)[）)]|非本(?:机|设备))[\s：:·、—-]*)+/u,'').trim();
}
export function fitMediaTitle(node){
 if(!node)return;
 node.style.fontSize='66px';
 if(node.scrollWidth>node.clientWidth){
  node.style.fontSize=`${Math.min(43,66*node.clientWidth/node.scrollWidth)}px`;
  while(node.scrollWidth>node.clientWidth&&parseFloat(node.style.fontSize)>1)node.style.fontSize=`${parseFloat(node.style.fontSize)-.5}px`;
 }
}
export async function render(ctx,shot,t,dur){const asset=ctx.timeline.assets[shot.params.asset],el=ctx.media.get(shot.params.asset);if(!asset||!el)throw new Error('镜头引用的素材不存在');ctx.mediaLayer.style.display='block';if(ctx.mediaLayer.firstChild!==el)ctx.mediaLayer.replaceChildren(el);if(asset.kind==='video'){const target=Math.min(t,Math.max(0,el.duration-.001));if(Math.abs(el.currentTime-target)>.0001){await new Promise((ok,no)=>{const timer=setTimeout(()=>{cleanup();no(new Error('视频定位超时'));},15000);const cleanup=()=>{clearTimeout(timer);el.removeEventListener('seeked',done);el.removeEventListener('error',failed);};const done=()=>{cleanup();ok();};const failed=()=>{cleanup();no(new Error('视频定位失败'));};el.addEventListener('seeked',done);el.addEventListener('error',failed);el.currentTime=target;});}}el.style.transform=shot.params.effect==='none'?'none':`scale(${1+.08*clamp(t/dur)})`;document.getElementById('credit').textContent=asset.credit?`图：${asset.credit}`:'';ctx.content.innerHTML=`<div class="media-copy">${esc(mediaTitle(shot.params.caption)||mediaTitle(asset.title))}</div>`;fitMediaTitle(ctx.content.querySelector('.media-copy'));}
