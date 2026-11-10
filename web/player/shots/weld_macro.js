import * as THREE from 'three';
import {box,mesh,esc,source,clamp,frameParallel,backLabels} from './common.js';
import {referenceSize} from './analogy.js';
export function setup(ctx,shot){
 const f=ctx.timeline.facts[shot.params.fact],a=ctx.timeline.analogies?.[shot.params.analogy];
 const width=Number(f?.value??.5)*(f?.unit==='m'?1:.001),diameter=referenceSize(a||{ref:'hair'}).meters;
 const g=new THREE.Group(),weld=new THREE.Group();g.add(weld);weld.name='weld-plates';
 const plateWidth=Math.max(width*4,.002),thickness=Math.max(width,.0004),depth=plateWidth*.65,gap=plateWidth*.04;
 const left=box(weld,plateWidth,thickness,depth,-(plateWidth+gap)/2,0,0,'#758897');left.name='plate-left';
 const right=box(weld,plateWidth,thickness,depth,(plateWidth+gap)/2,width,0,'#9aadb9');right.name='plate-right';
 const seam=box(weld,gap,thickness+width,depth,0,width/2,0,'#c2a16a');seam.name='weld-seam';
 const count=Math.max(1,Math.min(30,Math.floor(width/diameter+1e-8))),length=diameter*16;
 const hairs=new THREE.Group();hairs.name='hair-comparison';g.add(hairs);
 const hairGap=count>1?(width-count*diameter)/(count-1):0;
 for(let i=0;i<count;i++){
  const hair=mesh(new THREE.CylinderGeometry(diameter/2,diameter/2,length,32),'#382319',.25);
  hair.name='hair-cylinder';hair.rotation.x=Math.PI/2;hair.position.x=-width/2+diameter/2+i*(diameter+hairGap);
  hair.material.roughness=.23;hair.material.transparent=true;hairs.add(hair);
 }
 // 微距物体不使用覆盖整座设备的大尺度阴影贴图。
 g.traverse(node=>{if(node.isMesh){node.castShadow=false;node.receiveShadow=false;}});
 g.userData={weld,left,right,seam,hairs,width,diameter,length,thickness,depth,gap};ctx.scene.add(g);ctx.groups.set(shot.id,g);
}
function screen(ctx,p){const v=p.clone().project(ctx.camera);return {x:(v.x+1)*960,y:(1-v.y)*540};}
export function render(ctx,shot,t,dur){
 ctx.model.visible=false;ctx.floor.visible=false;
 const g=ctx.groups.get(shot.id);g.visible=true;
 const {weld,hairs,width,diameter,length,thickness,depth,gap}=g.userData,opacity=clamp((t-.7)/.7);
 const f=ctx.timeline.facts[shot.params.fact],a=ctx.timeline.analogies?.[shot.params.analogy],size=referenceSize(a||{ref:'hair'});
 const millimeters=Number((width*1000).toFixed(5));
 // 样式只在本镜头生效，右上参数卡与下方示意尺寸各占独立区域。
 ctx.content.innerHTML=`<style>#numbers{top:150px;max-width:450px}.weld-copy{width:1000px;max-width:1000px}.weld-copy p{margin:12px 0}</style><div class="weld-copy"><div class="eyebrow">制造精度 / 示意放大</div><h1>错边 ≤ ${esc(millimeters)} mm</h1><p>${esc(a?.text||'每一处细节，都有严格尺度。')}</p><div class="source">${source(f)}</div></div>`;
 const copy=ctx.content.querySelector?.('.weld-copy'),bottom=copy?copy.offsetTop+copy.offsetHeight:440;
 const bounds=new THREE.Box3().setFromObject(weld);
 ctx.camera.near=.000001;
 frameParallel(ctx,bounds,{angle:0,elevation:12,width:.50,cx:.34,cy:Math.max(.64,(bottom+180)/1080)});
 ctx.scene.background.set('#142330');
 const halfWidth=1/ctx.camera.projectionMatrix.elements[0],halfHeight=1/ctx.camera.projectionMatrix.elements[5];
 // 仅收紧本帧投影的深度区间，保留毫米级表面的深度精度。
 ctx.camera.projectionMatrix.makeOrthographic(-halfWidth,halfWidth,halfHeight,-halfHeight,ctx.camera.near,Math.max(.02,bounds.getSize(new THREE.Vector3()).length()*10));
 ctx.camera.projectionMatrixInverse.copy(ctx.camera.projectionMatrix).invert();
 hairs.scale.setScalar((440/1920*2*halfWidth)/width);
 const right=new THREE.Vector3(1,0,0).applyQuaternion(ctx.camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(ctx.camera.quaternion);
 // 从近裁剪面取屏幕中心的世界坐标，再落到钢板中心的深度平面。
 const center=bounds.getCenter(new THREE.Vector3()),projected=screen(ctx,center);
 hairs.position.copy(center).addScaledVector(right,(1520-projected.x)/960*halfWidth).addScaledVector(up,(projected.y-620)/540*halfHeight);
 for(const hair of hairs.children)hair.material.opacity=opacity;
 g.updateMatrixWorld(true);
 const left=screen(ctx,hairs.localToWorld(new THREE.Vector3(-width/2,0,length/2)));
 const end=screen(ctx,hairs.localToWorld(new THREE.Vector3(width/2,0,length/2)));
 const y=Math.max(left.y,end.y)+diameter/2*hairs.scale.x*Math.cos(THREE.MathUtils.degToRad(12))/(2*halfHeight)*1080+30;
 // 端点严格落在两块钢板的上表面，垂直尺寸表示错边而非焊缝宽度。
 const low=screen(ctx,weld.localToWorld(new THREE.Vector3(-gap/2,thickness/2,depth/2)));
 const high=screen(ctx,weld.localToWorld(new THREE.Vector3(gap/2,thickness/2+width,depth/2)));
 const x=low.x-130;
 ctx.labels.innerHTML=`<g class="weld-step-dimension"><path d="M ${low.x} ${low.y} H ${x-12} M ${high.x} ${high.y} H ${x-12} M ${x} ${low.y} V ${high.y}"/><text x="${x-20}" y="${(low.y+high.y)/2+8}" text-anchor="end">${esc(millimeters)} mm</text><text x="${x}" y="${low.y+45}" text-anchor="middle">错边 · 示意放大</text></g><g opacity="${opacity}"><path class="hair-dimension" d="M ${left.x} ${y-12} v 24 M ${end.x} ${y-12} v 24 M ${left.x} ${y} H ${end.x}"/><text x="${(left.x+end.x)/2}" y="${y+38}" text-anchor="middle">${esc(millimeters)} mm · 等比对照</text><text class="hair-label" x="${left.x}" y="${y+72}">头发丝直径 ${esc(size.size)} ${esc(size.unit)}</text></g>`;
 backLabels(ctx);
}
