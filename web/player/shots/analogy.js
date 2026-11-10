import * as THREE from 'three';
import {box,mesh,frameParallel,esc,clamp,projectBounds} from './common.js';
import {placeDimensionLabel,hudSafeArea,fitProjection,enclosingRect} from './layout.js';
const defaults={football_field:105,building_floor:3,boeing747:64.4,hair:.00007,person:1.75,bus:12};
export function referenceSize(a){
 const unit=a.ref==='hair'?'mm':'m',size=a.ref==='hair'?.07:defaults[a.ref];
 const modern=Number.isFinite(a.ref_size)&&['m','mm','t'].includes(a.ref_unit);
 return {size:modern?a.ref_size:size,unit:modern?a.ref_unit:unit,
  meters:modern&&Number.isFinite(a.ref_size_m)?a.ref_size_m:defaults[a.ref]};
}
function line(g,points,color='#ffffff'){const m=new THREE.Line(new THREE.BufferGeometry().setFromPoints(points.map(p=>new THREE.Vector3(...p))),new THREE.LineBasicMaterial({color}));g.add(m);}
export function setup(ctx,shot){const a=ctx.timeline.analogies?.[shot.params.analogy];if(!a)throw new Error('类比参数不存在');const g=new THREE.Group();g.userData.a=a;const ref=referenceSize(a).meters,r=new THREE.Group();g.add(r);g.userData.ref=r;
 if(a.ref==='football_field'){box(r,ref,.12,ref*68/105,0,.05,0,'#28654a');const w=ref/2-1,d=ref*68/105/2-1;line(r,[[-w,.15,-d],[w,.15,-d],[w,.15,d],[-w,.15,d],[-w,.15,-d]]);line(r,[[0,.15,-d],[0,.15,d]]);const pts=[];for(let i=0;i<=64;i++){const v=i/64*Math.PI*2;pts.push([Math.sin(v)*9.15,.16,Math.cos(v)*9.15]);}line(r,pts);for(const x of [-w,w]){line(r,[[x,.2,-3.66],[x,2.44,-3.66],[x,2.44,3.66],[x,.2,3.66]]);line(r,[[x-Math.sign(x)*16.5,.16,-20],[x,.16,-20],[x,.16,20],[x-Math.sign(x)*16.5,.16,20],[x-Math.sign(x)*16.5,.16,-20]]);}}
 else if(a.ref==='building_floor'){
  const floors=Math.max(1,Math.ceil(a.ratio)),height=Math.max(.1,a.ratio)*ref;
  box(r,13,height,12,0,height/2,0,'#cad4da').name='building-wall';
  for(let j=0;j<floors;j++){
   box(r,13.2,.12,12.2,0,j*ref+.06,0,'#536675');
   const remaining=Math.min(ref,height-j*ref),windowHeight=remaining*.52;
   for(let i=0;i<4;i++){
    // 独立窗片与墙面、楼层边条留出间距，避免共面闪烁。
    const window=box(r,1.5,windowHeight,.04,-4.5+i*3,j*ref+remaining/2,6.17,'#2a4d67');
    window.name='building-window';
   }
  }
  g.userData.height=height;
 }
 else if(a.ref==='bus'){box(r,ref,3.2,2.5,0,1.9,0,'#e0d6be');box(r,ref*.88,1.1,2.56,0,2.4,0,'#20425a');for(const x of [-ref*.33,ref*.33])for(const z of [-1.3,1.3]){const wheel=mesh(new THREE.CylinderGeometry(.55,.55,.3,20),'#18212a');wheel.rotation.x=Math.PI/2;wheel.position.set(x,.6,z);r.add(wheel);}}
 else if(a.ref==='person'){const body=mesh(new THREE.CapsuleGeometry(.18,.55,4,12),'#243c50');body.position.y=.95;r.add(body);const head=mesh(new THREE.SphereGeometry(.15,16,12),'#ffae59');head.position.y=1.6;r.add(head);for(const x of [-.11,.11])box(r,.14,.65,.16,x,.325,0,'#243c50');r.scale.setScalar(ref/1.75);}
 else if(a.ref==='boeing747'){
  // 翼展沿 x，与主梁共用尺度轴；机身沿 z。
  const scale=ref/64.4;
  const fuselage=mesh(new THREE.CylinderGeometry(3,2,70,32),'#d6dee4');
  fuselage.name='fuselage';fuselage.rotation.x=Math.PI/2;fuselage.position.y=6;r.add(fuselage);
  const wing=new THREE.Shape();
  wing.moveTo(-32.2,15);wing.lineTo(-4,-8);wing.lineTo(4,-8);wing.lineTo(32.2,15);wing.lineTo(4,6);wing.lineTo(-4,6);wing.closePath();
  const wings=mesh(new THREE.ExtrudeGeometry(wing,{depth:.8,bevelEnabled:false}),'#d6dee4');
  wings.name='wings';wings.rotation.x=Math.PI/2;wings.position.y=6;r.add(wings);
  box(r,22,.6,7,0,6,29,'#d6dee4');box(r,.6,9,10,0,9,28,'#d6dee4');
  // 起落架触地，机身和机翼保持离地间隙。
  for(const [x,z] of [[0,-24],[-5,10],[5,10]]){
   box(r,.45,3.5,.45,x,2.5,z,'#536675');
   const wheel=mesh(new THREE.CylinderGeometry(.8,.8,.6,20),'#18212a');
   wheel.name='landing-wheel';wheel.rotation.z=Math.PI/2;wheel.position.set(x,.8,z);r.add(wheel);
  }
  for(const part of [...r.children]){
   part.castShadow=true;part.receiveShadow=true;
   const edges=new THREE.LineSegments(new THREE.EdgesGeometry(part.geometry,25),new THREE.LineBasicMaterial({color:'#263b4b'}));
   part.add(edges);
  }
  r.scale.setScalar(scale);
 }
 else if(a.ref==='hair'){throw new Error('头发丝类比仅支持焊缝微距镜头');}
 else throw new Error('不支持的类比参照物');
 const crane=new THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')||ctx.model);
 const girder=new THREE.Box3().setFromObject(ctx.model.getObjectByName('girder')||ctx.model);
 const local=new THREE.Box3().setFromObject(r),heightAxis=a.axis==='height';
 // 参照物从第一帧起就与设备对齐，不用横向滑入破坏真实尺度。
 if(heightAxis){
  r.position.set(crane.max.x+6-local.min.x,-local.min.y,crane.getCenter(new THREE.Vector3()).z-local.getCenter(new THREE.Vector3()).z);
 }else{
  // 轨道可能比设备本体更长，统一放在完整轨道占地之外。
  const footprint=crane.clone();
  for(const name of ['rail_left','rail_right']){
   const rail=ctx.model.getObjectByName(name);if(rail)footprint.union(new THREE.Box3().setFromObject(rail));
  }
  r.position.set(girder.min.x-local.min.x,crane.min.y-local.min.y,footprint.min.z-6-local.max.z);
 }
 ctx.scene.add(g);ctx.groups.set(shot.id,g);
}
function screen(ctx,point){const p=point.clone().project(ctx.camera);return {x:(p.x+1)*960,y:(1-p.y)*540};}
function dimension(ctx,start,end,color,heightAxis){
 const a=screen(ctx,start),b=screen(ctx,end),tick=8;
 const ticks=heightAxis?`M ${a.x-tick} ${a.y} h ${tick*2} M ${b.x-tick} ${b.y} h ${tick*2}`:`M ${a.x} ${a.y-tick} v ${tick*2} M ${b.x} ${b.y-tick} v ${tick*2}`;
 return `<g class="dimension" style="--dimension-color:${color}"><path d="M ${a.x} ${a.y} L ${b.x} ${b.y} ${ticks}"/></g>`;
}
export function render(ctx,shot,t,dur){
 const g=ctx.groups.get(shot.id),a=g.userData.a;g.visible=true;
 const crane=new THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')||ctx.model),girder=new THREE.Box3().setFromObject(ctx.model.getObjectByName('girder')||ctx.model),ref=new THREE.Box3().setFromObject(g.userData.ref);
 const heightAxis=a.axis==='height';
 frameParallel(ctx,[crane,ref],heightAxis?{angle:0,elevation:0,height:.62,cy:.47}:{angle:-35,elevation:35,width:.62,cy:.43});
 // 正面平行投影让 y=0 与包围盒顶端直接对应屏幕上下端点。
 const f=ctx.timeline.facts[a.fact],ground=0;
 const size=referenceSize(a);
 const refText=a.ref==='building_floor'?`参照 ${Number(a.ratio.toFixed(2))} 层 × ${size.size} ${size.unit}`:`参照 ${size.size} ${size.unit}`;
 const dimensions=heightAxis?[
  [new THREE.Vector3(crane.min.x-3,ground,crane.max.z),new THREE.Vector3(crane.min.x-3,crane.max.y,crane.max.z),`${f?.name||'整机高度'} ${f?.value??ctx.size.y} ${f?.unit||'m'}`,'#ff8a1f'],
  [new THREE.Vector3(ref.max.x+3,ground,ref.max.z),new THREE.Vector3(ref.max.x+3,ref.max.y,ref.max.z),refText,'#38d1ff']
 ]:[
  [new THREE.Vector3(girder.min.x,crane.max.y+4,girder.max.z),new THREE.Vector3(girder.max.x,crane.max.y+4,girder.max.z),`主梁 ${f?.value??Number((girder.max.x-girder.min.x).toFixed(2))} ${f?.unit||'m'}`,'#ff8a1f'],
  [new THREE.Vector3(ref.min.x,ref.max.y+1,ref.max.z+3),new THREE.Vector3(ref.max.x,ref.max.y+1,ref.max.z+3),refText,'#38d1ff']
 ];
 if(a.ref==='boeing747'){
  // 尺寸端点与真实翼尖共用 x、z，斜视时仍保持屏幕横向对齐。
  dimensions[1][0]=g.userData.ref.localToWorld(new THREE.Vector3(-32.2,7.5,15));
  dimensions[1][1]=g.userData.ref.localToWorld(new THREE.Vector3(32.2,7.5,15));
 }
 const opacity=clamp(t/.6);
 ctx.content.innerHTML=`<div class="section-title analogy-title"><small>尺度对照 / 等比例</small>${heightAxis?'把高度放回日常':'把长度放回日常'}</div><div class="analogy-copy" style="opacity:${opacity}">${esc(a.text)}<small>参照尺寸 ${esc(size.size)} ${esc(size.unit)} · 按真实比例呈现</small></div>`+
  dimensions.map(([, ,text,color],i)=>`<div class="dimension-label ${heightAxis?(i===0?'left':'right'):'center'}" style="left:0;top:0;--dimension-color:${color};opacity:${opacity}">${esc(text)}</div>`).join('');
 const nodes=[...(ctx.content.querySelectorAll?.('.dimension-label')||[])];
 const safe=hudSafeArea(ctx,shot,t);
 const layout=()=>{
  const segments=dimensions.flatMap(([start,end])=>{
   const a=screen(ctx,start),b=screen(ctx,end),tick=10;
   return [[a,b],...[a,b].map(p=>heightAxis?[{x:p.x-tick,y:p.y},{x:p.x+tick,y:p.y}]:[{x:p.x,y:p.y-tick},{x:p.x,y:p.y+tick}])];
  });
  const trolley=ctx.model.getObjectByName('trolley');
  const obstacles=trolley?[projectBounds(ctx,new THREE.Box3().setFromObject(trolley))]:[];
  const rects=dimensions.map(([start,end],i)=>{
   const a=screen(ctx,start),b=screen(ctx,end),width=nodes[i]?.offsetWidth||340,height=nodes[i]?.offsetHeight||36;
   // 高度标签严格固定在中点外侧；取景为文字预留空间，不向上挪标签。
   const rect=heightAxis?{x:i===0?a.x-width-14:a.x+14,y:(a.y+b.y-height)/2,width,height}:
    placeDimensionLabel(a,b,width,height,'center',segments,obstacles);
   obstacles.push(rect);return rect;
  });
  const geometry=[crane,ref].map(b=>projectBounds(ctx,b));
  return {rects,bounds:enclosingRect([...geometry,...rects,...segments.flat().map(p=>({x:p.x-2,y:p.y-2,width:4,height:4}))])};
 };
 // 缩放后标签仍保持像素字号，因此重新测量外包直到留白稳定。
 for(let i=0;i<12;i++){
  const {bounds}=layout();
  fitProjection(ctx,bounds,{x:safe.x+2,y:safe.y+2,width:safe.width-4,height:safe.height-4});
 }
 const {rects}=layout();
 nodes.forEach((node,i)=>Object.assign(node.style,{left:`${rects[i].x}px`,top:`${rects[i].y}px`,transform:'none',marginLeft:'0'}));
 ctx.labels.innerHTML=`<g opacity="${opacity}">${dimensions.map(([start,end,,color])=>dimension(ctx,start,end,color,heightAxis)).join('')}</g>`;
}
