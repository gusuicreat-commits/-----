import * as THREE from 'three';
import {box,mesh,esc,source,clamp} from './common.js';
export function setup(ctx,shot){
 const g=new THREE.Group(),weld=new THREE.Group();g.add(weld);weld.position.x=-.03;
 box(weld,.045,.004,.09,-.0235,0,0,'#758897');box(weld,.045,.004,.09,.0235,.0003,0,'#758897');
 for(let i=0;i<36;i++){
  const bead=mesh(new THREE.SphereGeometry(.003,20,12),'#99a8b3',.95);
  bead.scale.set(.95,.55,1.4);bead.position.set(0,.002,-.043+i*.00245);weld.add(bead);
 }
 const f=ctx.timeline.facts[shot.params.fact],a=ctx.timeline.analogies?.[shot.params.analogy];
 const width=Number(f?.value||.5)/1000,diameter=a?.ref_size_m||.00007;
 const count=Math.max(1,Math.min(30,Math.floor(width/diameter+1e-8))),length=diameter*16;
 const hairs=new THREE.Group();hairs.name='hair-comparison';g.add(hairs);
 const gap=count>1?(width-count*diameter)/(count-1):0;
 for(let i=0;i<count;i++){
  const hair=mesh(new THREE.CylinderGeometry(diameter/2,diameter/2,length,32),'#382319',.25);
  hair.name='hair-cylinder';hair.rotation.x=Math.PI/2;hair.position.x=-width/2+diameter/2+i*(diameter+gap);
  hair.material.roughness=.23;hair.material.transparent=true;hairs.add(hair);
 }
 g.userData={hairs,width,diameter,length};ctx.scene.add(g);ctx.groups.set(shot.id,g);
}
function screen(ctx,p){const v=p.clone().project(ctx.camera);return {x:(v.x+1)*960,y:(1-v.y)*540};}
export function render(ctx,shot,t,dur){
 ctx.model.visible=false;ctx.floor.visible=false;
 const g=ctx.groups.get(shot.id);g.visible=true;
 // 平行投影使圆柱端面的并排宽度与尺寸线严格一致。
 const halfHeight=.05,halfWidth=halfHeight*ctx.camera.aspect;
 ctx.camera.near=.0001;ctx.camera.position.set(0,.125,Math.sqrt(3)*.125);ctx.camera.lookAt(0,0,0);ctx.camera.updateMatrixWorld();
 ctx.camera.projectionMatrix.makeOrthographic(-halfWidth,halfWidth,halfHeight,-halfHeight,ctx.camera.near,ctx.camera.far);
 ctx.camera.projectionMatrixInverse.copy(ctx.camera.projectionMatrix).invert();
 ctx.scene.background.set('#142330');
 const {hairs,width,diameter,length}=g.userData,opacity=clamp((t-.7)/.7);
 hairs.scale.setScalar((440/1920*2*halfWidth)/width);
 const up=new THREE.Vector3(0,1,0).applyQuaternion(ctx.camera.quaternion);
 hairs.position.copy(up.multiplyScalar((1-2*450/1080)*halfHeight));hairs.position.x=(1520/960-1)*halfWidth;
 for(const hair of hairs.children)hair.material.opacity=opacity;
 g.updateMatrixWorld(true);
 const left=screen(ctx,hairs.localToWorld(new THREE.Vector3(-width/2,0,length/2)));
 const right=screen(ctx,hairs.localToWorld(new THREE.Vector3(width/2,0,length/2)));
 const y=Math.max(left.y,right.y)+diameter/2*hairs.scale.x*Math.cos(Math.PI/6)/(.1)*1080+30;
 const f=ctx.timeline.facts[shot.params.fact],a=ctx.timeline.analogies?.[shot.params.analogy];
 ctx.content.innerHTML=`<div class="weld-copy"><div class="eyebrow">制造精度 / 放大示意</div><h1>错边 ≤ ${esc(f?.value??'待添加')} mm</h1><p>${esc(a?.text||'每一处细节，都有严格尺度。')}</p><div class="source">${source(f)}</div></div>`;
 ctx.labels.innerHTML=`<g opacity="${opacity}"><path class="hair-dimension" d="M ${left.x} ${y-12} v 24 M ${right.x} ${y-12} v 24 M ${left.x} ${y} H ${right.x}"/><text x="${(left.x+right.x)/2}" y="${y+38}" text-anchor="middle">${esc(f?.value??.5)} mm · 等比对照</text><text class="hair-label" x="${left.x}" y="${y+72}">头发丝直径 ${Number((diameter*1000).toFixed(5))} mm</text></g>`;
}
