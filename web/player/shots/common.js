import * as THREE from 'three';
import {routeLeader,splitLeaderSlots,nearLeaderSlots} from './layout.js';
export const clamp = (x,a=0,b=1) => Math.max(a,Math.min(b,x));
export const ease = x => (x=clamp(x))<.5?4*x*x*x:1-(-2*x+2)**3/2;
export const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const names = {girder:'主梁',leg_left:'刚性腿',leg_right:'柔性腿',trolley:'起重小车',hoist_hook:'吊钩',cab:'司机室'};
export function source(f){return `来源：${esc(f?.source?.doc || '待添加')} 第${esc(f?.source?.page ?? '待添加')}页`;}
export function orbit(ctx,angle=20,elevation=18,distance=1.2,target=ctx.center){
 const a=THREE.MathUtils.degToRad(angle), e=THREE.MathUtils.degToRad(elevation), r=ctx.diagonal*distance;
 ctx.camera.position.set(target.x+Math.sin(a)*Math.cos(e)*r,target.y+Math.sin(e)*r,target.z+Math.cos(a)*Math.cos(e)*r);
 ctx.camera.lookAt(target);ctx.camera.updateMatrixWorld();
}
// 为背景采样保留两侧各 8% 画宽，沿视线后退而不改变透视方向。
export function fitBackgroundColumns(ctx){
 ctx.model.updateWorldMatrix(true,true);ctx.camera.updateMatrixWorld();
 const camera=ctx.camera,limit=.83/camera.projectionMatrix.elements[0];let retreat=0;
 ctx.model.traverseVisible(n=>{
  if(!n.isMesh)return;n.geometry.computeBoundingBox();
  for(const p of boundsCorners(n.geometry.boundingBox)){
   p.applyMatrix4(n.matrixWorld).applyMatrix4(camera.matrixWorldInverse);
   retreat=Math.max(retreat,Math.abs(p.x)/limit+p.z);
  }
 });
 camera.position.addScaledVector(new THREE.Vector3(0,0,1).applyQuaternion(camera.quaternion),retreat);
 camera.updateMatrixWorld();
}
export function mesh(geometry,color,metalness=.35){return new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,metalness,roughness:.4}));}
export function box(group,w,h,d,x,y,z,color){const m=mesh(new THREE.BoxGeometry(w,h,d),color);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;group.add(m);return m;}
export function partBounds(node){
 const bounds=new THREE.Box3();
 node.updateWorldMatrix(true,true);
 const visit=n=>{
  // 吊钩、绳索等独立运动部件不计入小车本体的锚点。
  if(n!==node&&(names[n.name]||['rope','rail_left','rail_right'].includes(n.name)))return;
  if(n.isMesh){n.geometry.computeBoundingBox();bounds.union(n.geometry.boundingBox.clone().applyMatrix4(n.matrixWorld));}
  for(const child of n.children)visit(child);
 };
 visit(node);return bounds.isEmpty()?new THREE.Box3().setFromObject(node):bounds;
}
export function projectPoint(ctx,point){const p=point.clone().project(ctx.camera);return {x:(p.x+1)*960,y:(1-p.y)*540};}
export function projectBounds(ctx,bounds){
 const points=boundsCorners(bounds).map(p=>projectPoint(ctx,p));
 const x=Math.min(...points.map(p=>p.x)),y=Math.min(...points.map(p=>p.y));
 return {x,y,width:Math.max(...points.map(p=>p.x))-x,height:Math.max(...points.map(p=>p.y))-y};
}
export function labelNodes(ctx,ids,{splitSides=false,safe,pointSource}={}){
 ctx.scene.updateMatrixWorld(true);ctx.camera.updateMatrixWorld();
 if(splitSides||pointSource){
  const center=pointSource?null:new THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')||ctx.model).getCenter(new THREE.Vector3());
  const items=[...new Set(ids)].map(id=>{
   if(pointSource){const point=pointSource(id);return point?{id,...point}:null;}
   const node=ctx.model.getObjectByName(id);if(!node)return null;
   const anchor=partBounds(node).getCenter(new THREE.Vector3());
   return {id,left:anchor.x<center.x,...projectPoint(ctx,anchor)};
  }).filter(Boolean);
  const obstacles=pointSource?Object.keys(names).map(id=>{const p=pointSource(id);return p?{id,...p}:null;}).filter(Boolean):[];
  ctx.labels.innerHTML=(pointSource?nearLeaderSlots(items,safe,obstacles):splitLeaderSlots(items,safe)).map(v=>{
   const {x,y}=v.label;
   if(pointSource)v.points.reverse();
   return `<g data-part="${esc(v.id)}" data-side="${v.left?'left':'right'}"><path d="${v.points.map((p,j)=>`${j?'L':'M'} ${p.x} ${p.y}`).join(' ')}"/><circle cx="${v.x}" cy="${v.y}" r="5"/><rect x="${x}" y="${y}" width="210" height="50" rx="8"/><text x="${x+20}" y="${y+34}">${names[v.id]||esc(v.id)}</text></g>`;
  }).join('');
  return;
 }
 const parts=[...new Set([...Object.keys(names),'rope','rail_left','rail_right',...ids])].map(id=>{
  if(pointSource){const point=pointSource(id);return point?{id,...point}:null;}
  const node=ctx.model.getObjectByName(id);if(!node)return null;
  const bounds=partBounds(node);return {id,...projectPoint(ctx,bounds.getCenter(new THREE.Vector3())),rect:projectBounds(ctx,bounds)};
 }).filter(Boolean);
 const items=parts.filter(p=>ids.includes(p.id)).sort((a,b)=>a.y-b.y);
 ctx.labels.innerHTML=items.map((v,i)=>{
  const left=v.x<960,x=left?95:1590,y=385+i*85;
  const points=routeLeader(v,{x:left?x+210:x,y:y+25},parts.filter(p=>p!==v).map(p=>p.rect));
  return `<g data-part="${esc(v.id)}"><path d="${points.map((p,j)=>`${j?'L':'M'} ${p.x} ${p.y}`).join(' ')}"/><circle cx="${v.x}" cy="${v.y}" r="5"/><rect x="${x}" y="${y}" width="210" height="50" rx="8"/><text x="${x+20}" y="${y+34}">${names[v.id]||esc(v.id)}</text></g>`;
 }).join('');
}
// SVG 文字按实际字体包围盒加不透明底，保持字样与钢板高亮区分离。
export function backLabels(ctx){
 for(const text of ctx.labels.querySelectorAll?.('text')||[]){
  const b=text.getBBox(),rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
  for(const [key,value] of Object.entries({x:b.x-10,y:b.y-5,width:b.width+20,height:b.height+10,rx:6}))rect.setAttribute(key,String(value));
  rect.setAttribute('class','label-background');text.style.fill='#fff';text.before(rect);
 }
}
export const setup = () => {};

export const sceneBackground = '#1d2b3a';
// 背景和地面共用屏幕空间渐变；颜色在线性空间混合后统一输出。
const atmosphereShader=`
uniform vec3 skyColor;
uniform vec3 groundColor;
uniform float viewportHeight;
vec3 atmosphereColor() {
 float y = 1.0 - gl_FragCoord.y / viewportHeight;
 return mix(skyColor, groundColor, smoothstep(0.2, 0.85, y));
}`;
function atmosphereUniforms(){return {skyColor:{value:new THREE.Color(sceneBackground)},groundColor:{value:new THREE.Color('#8999a6')},viewportHeight:{value:1080}};}
export function createBackdrop(){
 const material=new THREE.ShaderMaterial({
  uniforms:atmosphereUniforms(),depthTest:false,depthWrite:false,
  vertexShader:'void main(){gl_Position=vec4(position.xy,1.0,1.0);}',
  fragmentShader:`${atmosphereShader}
void main(){
 gl_FragColor=vec4(atmosphereColor(),1.0);
 #include <tonemapping_fragment>
 #include <colorspace_fragment>
}`,
 });
 const backdrop=new THREE.Mesh(new THREE.PlaneGeometry(2,2),material);
 backdrop.frustumCulled=false;backdrop.renderOrder=-1000;return backdrop;
}
// 平面覆盖远裁剪范围；近裁剪和远处都渐隐到相同背景。
export function createGround(camera,texture){
 const extent=camera.far*4;
 texture.repeat.set(24*extent/1500,24*extent/1500);
 const material=new THREE.MeshStandardMaterial({map:texture,roughness:.94,metalness:.08});
 const uniforms={...atmosphereUniforms(),groundFadeNear:{value:1},groundFadeFar:{value:100}};
 material.onBeforeCompile=shader=>{
  Object.assign(shader.uniforms,uniforms);
  shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
${atmosphereShader}
uniform float groundFadeNear;
uniform float groundFadeFar;`);
  // 在色调映射之前混合，避免背景与地面经过不同颜色变换形成接缝。
  shader.fragmentShader=shader.fragmentShader.replace('#include <tonemapping_fragment>',`
 vec3 haze = atmosphereColor();
 float screenFade = smoothstep(0.35, 0.75, 1.0-gl_FragCoord.y/viewportHeight);
 float groundVisibility = screenFade;
 #ifdef USE_FOG
  groundVisibility *= smoothstep(groundFadeNear, groundFadeFar, vFogDepth);
  groundVisibility *= 1.0-smoothstep(fogNear, fogFar, vFogDepth);
 #endif
 gl_FragColor.rgb = mix(haze, gl_FragColor.rgb, groundVisibility);
 #include <tonemapping_fragment>`).replace('#include <fog_fragment>','');
 };
 const floor=new THREE.Mesh(new THREE.PlaneGeometry(extent,extent),material);
 floor.rotation.x=-Math.PI/2;floor.position.y=-.12;floor.receiveShadow=true;
 floor.userData.fadeUniforms=uniforms;
 return floor;
}
export function updateGround(ctx){
 const {camera,floor,scene}=ctx;
 floor.position.x=camera.position.x;floor.position.z=camera.position.z;
 if(ctx.photoreal)return;
 const map=floor.material.map,extent=floor.geometry.parameters.width;
 map.offset.x+=floor.position.x/extent*map.repeat.x;
 map.offset.y-=floor.position.z/extent*map.repeat.y;
 const fade=floor.userData.fadeUniforms;
 fade.groundFadeNear.value=camera.near;
 fade.groundFadeFar.value=camera.near+Math.max(1,ctx.diagonal*.7);
 fade.skyColor.value.copy(scene.background);
 ctx.backdrop?.material.uniforms.skyColor.value.copy(scene.background);
 scene.fog.color.copy(scene.background);
}

export function boundsCorners(bounds){
 const points=[];
 for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z])points.push(new THREE.Vector3(x,y,z));
 return points;
}
// 以外包投影占比取景，保持类比两侧的比例一致。
export function frameParallel(ctx,bounds,{angle=0,elevation=35,width,height,cx=.5,cy=.5}){
 const parts=Array.isArray(bounds)?bounds:[bounds];
 bounds=parts.reduce((all,part)=>all.union(part),new THREE.Box3());
 const center=bounds.getCenter(new THREE.Vector3());
 orbit(ctx,angle,elevation,1,center);
 const right=new THREE.Vector3(1,0,0).applyQuaternion(ctx.camera.quaternion);
 const up=new THREE.Vector3(0,1,0).applyQuaternion(ctx.camera.quaternion);
 const back=new THREE.Vector3(0,0,1).applyQuaternion(ctx.camera.quaternion);
 const points=parts.flatMap(boundsCorners).map(p=>p.sub(center));
 const extent=axis=>Math.max(...points.map(p=>p.dot(axis)))-Math.min(...points.map(p=>p.dot(axis)));
 const halfHeight=height?extent(up)/(2*height):extent(right)/(2*width*ctx.camera.aspect);
 const halfWidth=halfHeight*ctx.camera.aspect;
 const midpoint=axis=>(Math.max(...points.map(p=>p.dot(axis)))+Math.min(...points.map(p=>p.dot(axis))))/2;
 const target=center.clone().addScaledVector(right,midpoint(right)-(2*cx-1)*halfWidth).addScaledVector(up,midpoint(up)-(1-2*cy)*halfHeight);
 ctx.camera.position.copy(target).addScaledVector(back,bounds.getSize(new THREE.Vector3()).length());
 ctx.camera.lookAt(target);ctx.camera.updateMatrixWorld();
 ctx.camera.projectionMatrix.makeOrthographic(-halfWidth,halfWidth,halfHeight,-halfHeight,ctx.camera.near,ctx.camera.far);
 ctx.camera.projectionMatrixInverse.copy(ctx.camera.projectionMatrix).invert();
}
