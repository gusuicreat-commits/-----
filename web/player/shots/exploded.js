import * as THREE from 'three';
import {ease,labelNodes,frameParallel,projectBounds,projectPoint} from './common.js';
import {hudSafeArea,fitProjection} from './layout.js';
export {setup} from './common.js';
export function render(ctx,shot,t,dur){
 const p=shot.params,amount=ease(Math.min(t/dur*3,(1-t/dur)*3))*(p.spread_m??12);
 const leg=ctx.model.getObjectByName('leg_left'),cab=ctx.model.getObjectByName('cab');
 const legBefore=leg?.getWorldPosition(new THREE.Vector3()),cabBefore=cab?.getWorldPosition(new THREE.Vector3());
 for(const id of new Set(p.parts||[])){
  // 司机室是刚性腿的附属件，不单独拆出。
  if(id==='cab')continue;
  const n=ctx.model.getObjectByName(id);if(!n)continue;
  const dir=({girder:[0,1,0],leg_left:[-1,0,0],leg_right:[1,0,0],trolley:[0,1.8,0],hoist_hook:[0,-1,0]})[id]||[0,1,0];
  n.position.x+=dir[0]*amount;n.position.y+=dir[1]*amount;n.position.z+=dir[2]*amount;
 }
 if(leg&&cab){
  const target=cabBefore.add(leg.getWorldPosition(new THREE.Vector3()).sub(legBefore));
  cab.position.copy(cab.parent?cab.parent.worldToLocal(target):target);
 }
 ctx.content.innerHTML='<div class="section-title"><small>结构分解 / 示意</small>从整体，读懂协同</div>';
 const safe=hudSafeArea(ctx,shot,t);
 const trolley=ctx.model.getObjectByName('trolley'),girder=ctx.model.getObjectByName('girder');
 const fit=()=>{
  const bounds=new THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')||ctx.model);
  frameParallel(ctx,bounds,{angle:13,elevation:14,width:.6,cy:.5});
  fitProjection(ctx,projectBounds(ctx,bounds),{x:350,y:safe.y+26,width:1220,height:Math.min(770,safe.y+safe.height)-safe.y-52});
 };
 // 小车 Box3 含吊钩、绳索，必须整体抬到主梁投影上方，锚点才落在独立部件内。
 for(let i=0;i<24;i++){
  fit();
  if(!trolley||!girder||!p.parts?.includes('trolley'))break;
  const tb=new THREE.Box3().setFromObject(trolley),gb=new THREE.Box3().setFromObject(girder);
  const tr=projectBounds(ctx,tb),gr=projectBounds(ctx,gb),gap=gr.y-tr.y-tr.height;
  if(gap>=24)break;
  const center=tb.getCenter(new THREE.Vector3()),a=projectPoint(ctx,center),b=projectPoint(ctx,center.clone().add(new THREE.Vector3(0,1,0)));
  const target=trolley.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,(28-gap)/Math.max(.01,a.y-b.y),0));
  trolley.position.copy(trolley.parent?trolley.parent.worldToLocal(target):target);
 }
 fit();
 labelNodes(ctx,[...new Set([...(p.parts||[]),...(cab?['cab']:[])])],{splitSides:true});
}
