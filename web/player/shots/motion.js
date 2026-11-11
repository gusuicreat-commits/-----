import * as THREE from 'three';
import {ease,esc,partBounds} from './common.js';
import {cameraArc,cameraEase} from '../camera.js';
export {setup} from './common.js';

function updateRope(ctx,hook){
 const rope=ctx.model.getObjectByName('rope');if(!rope)return;
 const initial=ctx.originals.find(o=>o.n===rope),oldHook=ctx.originals.find(o=>o.n===hook);
 rope.geometry?.computeBoundingBox();const bounds=rope.geometry?.boundingBox;
 if(bounds&&Math.abs(bounds.min.y+1)<1e-5&&Math.abs(bounds.max.y)<1e-5){
  // 标准绳索局部范围 [-1,0]，顶部固定在小车，底部连接滑轮组顶板。
  rope.position.copy(initial.p);rope.scale.y=Math.max(.01,initial.s.y+oldHook.p.y-hook.position.y);
 }else{
  const anchor=initial.p.y+Math.abs(initial.p.y-oldHook.p.y);
  const length=Math.max(.01,anchor-hook.position.y),oldLength=Math.max(.01,anchor-oldHook.p.y);
  rope.position.y=(anchor+hook.position.y)/2;rope.scale.y=initial.s.y*length/oldLength;
 }
}

export function render(ctx,shot,t,dur){
 const p=shot.params,rig=ctx.timeline.model?.rig?.axes?.[p.axis];
 const node=ctx.model.getObjectByName(rig?.node||({trolley:'trolley',hoist:'hoist_hook',gantry:'crane'})[p.axis]);
 const value=p.from_m+(p.to_m-p.from_m)*ease(t/dur);
 if(node){
  const axis=rig?.axis||({trolley:'x',hoist:'y',gantry:'z'})[p.axis];
  if(p.axis==='hoist'){
   node.parent.updateWorldMatrix(true,false);
   const world=node.getWorldPosition(ctx.center.clone());world.y=value;
   node.position.copy(node.parent.worldToLocal(world));updateRope(ctx,node);
  }else{
   // 轨道受契约约束挂在整机下，但大车运行时仍固定于地面基础。
   const rails=p.axis==='gantry'?['rail_left','rail_right'].map(id=>ctx.model.getObjectByName(id)).filter(Boolean).map(n=>({n,world:n.getWorldPosition(ctx.center.clone())})):[];
   node.position[axis]=value;
   for(const {n,world} of rails)n.position.copy(n.parent.worldToLocal(world));
  }
 }
 const u=cameraEase(t/dur),scale=(ctx.size?.y||ctx.center.y*2||51)/51;
 const target=node?partBounds(node).getCenter(new THREE.Vector3()):ctx.center.clone();
 if(p.axis==='trolley'){target.y=(ctx.size?.y||ctx.center.y*2)*.85;target.z=0;}
 cameraArc(ctx,{angle:-25+u*7,elevation:p.axis==='trolley'?-9:5,distance:(p.axis==='trolley'?90:145)*scale,target,fov:35,screenX:.56,screenY:.49});
 const f=ctx.timeline.facts?.[rig?.speed_fact];
 document.getElementById('motion-info').innerHTML=`<strong>${(p.speedup??1)===1?'实时演示':`×${esc(p.speedup)} 倍速演示`}</strong>${f?`最大 ${esc(f.value)} m/min · 来源 第${esc(f.source.page)}页`:'速度参数待添加'}`;
 ctx.content.innerHTML=`<div class="section-title"><small>运动演示</small>${({trolley:'小车横移',hoist:'吊钩起升',gantry:'大车行走'})[p.axis]}</div>`;
}
