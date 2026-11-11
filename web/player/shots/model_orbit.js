import * as THREE from 'three';
import {editorialLabels} from './common.js';
import {cameraArc,cameraEase} from '../camera.js';
export {setup} from './common.js';
export function frameModelOrbit(ctx,p,t,dur){
 const u=cameraEase(t/dur),scale=(ctx.size?.y||ctx.center.y*2||51)/51;
 const target=ctx.center.clone();target.y+=6*scale;
 // 显式分镜参数遵循 CONTRACTS：角度为度，距离为包围盒对角线倍数。
 const from=p.from_deg??-29,to=p.to_deg??-13,elevation=p.elevation_deg??1,distance=(p.distance??1.1)*ctx.diagonal;
 cameraArc(ctx,{angle:from+(to-from)*u,elevation,distance,target,fov:36,screenX:.53,screenY:.51});
}
export function render(ctx,shot,t,dur){
 frameModelOrbit(ctx,shot.params,t,dur);
 const ids=shot.params.highlight||[],index=Math.min(ids.length-1,Math.floor(t/dur*Math.max(1,ids.length)));
 editorialLabels(ctx,ids.length?[ids[index]]:[]);
 ctx.content.innerHTML='<div class="section-title"><small>结构 / STRUCTURE</small>各有其职，协同承载</div>';
}
