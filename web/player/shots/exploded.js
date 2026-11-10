import * as THREE from 'three';
import {orbit,ease,labelNodes} from './common.js';
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
 orbit(ctx,13,14,1.5);
 ctx.content.innerHTML='<div class="section-title"><small>结构分解 / 示意</small>从整体，读懂协同</div>';
 labelNodes(ctx,[...new Set([...(p.parts||[]),...(cab?['cab']:[])])],{splitSides:true});
}
