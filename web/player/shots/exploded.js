import * as THREE from 'three';
import {ease,labelNodes,frameParallel,partBounds,projectBounds,projectPoint,editorialLabels} from './common.js';
import {hudSafeArea} from './layout.js';
export {setup} from './common.js';
export function renderBackground(ctx,shot,t,pointSource){
 ctx.content.innerHTML='<div class="section-title"><small>结构分解 / 示意</small>从整体，读懂协同</div>';
 const safe=hudSafeArea(ctx,shot,t);
 // 右上数字卡占据整列，标签不进入该列。
 if(shot.text_overlays?.length)safe.width=Math.min(safe.width,1920*.74-safe.x);
 labelNodes(ctx,[...new Set([...(shot.params.parts||[]),'cab'])],{splitSides:true,safe,pointSource});
 for(const id of ['hoist_hook','trolley']){
  const point=pointSource(id);if(!point)continue;
  ctx.labels.innerHTML+=`<circle class="part-highlight" data-highlight="${id}" cx="${point.x}" cy="${point.y}" r="22"/>`;
 }
}
export function render(ctx,shot,t,dur){
 if(shot.bg)return;
 const p=shot.params,amount=ease(Math.min(t/dur*3,(1-t/dur)*3))*(p.spread_m??12)*.6;
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
 // 收紧分解距离后，仍为主梁与支腿保留至少 6 米净空。
 const girder=ctx.model.getObjectByName('girder');
 if(girder&&p.parts?.includes('girder')){
  const tops=['leg_left','leg_right'].map(id=>ctx.model.getObjectByName(id)).filter(Boolean).map(n=>partBounds(n).max.y);
  if(tops.length){
   const lift=Math.max(0,Math.max(...tops)+6-partBounds(girder).min.y);
   const target=girder.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,lift,0));
   girder.position.copy(girder.parent?girder.parent.worldToLocal(target):target);
  }
 }
 ctx.content.innerHTML='<div class="section-title"><small>结构分解 / 示意</small>从整体，读懂协同</div>';
 const safe=hudSafeArea(ctx,shot,t);
 const trolley=ctx.model.getObjectByName('trolley');
 const fit=()=>{
  const parts=[];ctx.model.updateWorldMatrix(true,true);
  ctx.model.traverseVisible(n=>{
   if(!n.isMesh)return;n.geometry.computeBoundingBox();
   parts.push(n.geometry.boundingBox.clone().applyMatrix4(n.matrixWorld));
  });
  // 平行投影以视野宽度拉近主体；完整部件留在画布内，标签单独避让 HUD。
  frameParallel(ctx,parts,{angle:13,elevation:14,width:.65,cy:.5});
 };
 // 只按小车本体校正净空，避免把下挂吊钩也抬到主梁上方。
 for(let i=0;i<24;i++){
  fit();
  if(!trolley||!girder||!p.parts?.includes('trolley'))break;
  const tb=partBounds(trolley),gb=partBounds(girder);
  const tr=projectBounds(ctx,tb),gr=projectBounds(ctx,gb),gap=gr.y-tr.y-tr.height;
  if(gap>=24)break;
  const center=tb.getCenter(new THREE.Vector3()),a=projectPoint(ctx,center),b=projectPoint(ctx,center.clone().add(new THREE.Vector3(0,1,0)));
  const target=trolley.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0,(28-gap)/Math.max(.01,a.y-b.y),0));
  trolley.position.copy(trolley.parent?trolley.parent.worldToLocal(target):target);
 }
 fit();
 const sequence=[...new Set([...(p.parts||[]),...(cab?['cab']:[])])],phase=Math.min(Math.ceil(sequence.length/2)-1,Math.floor(t/dur*Math.ceil(sequence.length/2)));
 editorialLabels(ctx,sequence.slice(phase*2,phase*2+2));

}
