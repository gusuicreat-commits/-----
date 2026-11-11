import {test,after} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {createShipyard,shipyardPlacement,placeShipyard,fitShipyardBuildings} from '../player/environment.js';
import {prepareRails,craneMaterials,replaceCraneMaterials,placeConcreteGround} from '../player/materials.js';
import {SUN_DIRECTION,fitSunShadow,DeterministicGTAOPass} from '../player/pipeline.js';
import {boundsCorners} from '../player/shots/common.js';
import {render as motion} from '../player/shots/motion.js';
import {frameModelOrbit} from '../player/shots/model_orbit.js';

const temp=mkdtempSync(path.join(tmpdir(),'kepu-t22-geometry-'));
after(()=>rmSync(temp,{recursive:true,force:true}));
const file=path.join(temp,'crane.glb');
execFileSync(path.resolve('../backend/.venv/bin/python'),['-c',`from pathlib import Path
from app.model3d.parametric import build_parametric
import sys
build_parametric({'F_girder_length':104,'F_overall_height':51,'F_span':88,'F_wheel_count':64},Path(sys.argv[1]))`,file],{cwd:path.resolve('../backend'),env:{...process.env,PYTHONPATH:'.'}});
async function model(){const bytes=readFileSync(file);return (await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'')).scene;}

test('新模型 GLB 可解析且合批后材质独立高亮',async()=>{
 const root=await model();replaceCraneMaterials(root,51,'parametric');
 const girder=root.getObjectByName('girder_paint').material,leg=root.getObjectByName('leg_left_paint').material;
 assert.notEqual(girder,leg);assert.equal(girder.type,'MeshPhysicalMaterial');assert.equal(girder.color.getHexString(),'d9461c');
 girder.emissive.set('cyan');assert.equal(leg.emissive.getHexString(),'000000');
 const shader={uniforms:{},vertexShader:THREE.ShaderLib.physical.vertexShader,fragmentShader:THREE.ShaderLib.physical.fragmentShader};
 girder.onBeforeCompile(shader);assert.match(shader.fragmentShader,/roughnessFactor\+paintVariation/);assert.match(shader.vertexShader,/vPaintWorld=\(modelMatrix/);
 assert.equal(shader.uniforms.paintHeight.value,51);
});

test('缺少NORMAL的真实GLB替换后保持面法线，漆面不读取零法线',async()=>{
 const root=await model();let count=0;
 root.traverse(n=>{if(n.isMesh){assert.equal(n.geometry.hasAttribute('normal'),false);assert.equal(n.material.flatShading,true);count++;}});
 assert.ok(count>15);replaceCraneMaterials(root,51,'parametric');
 root.traverse(n=>{if(n.isMesh)for(const m of [].concat(n.material))assert.equal(m.flatShading,true,n.name);});
 const material=root.getObjectByName('girder_paint').material;
 const shader={uniforms:{},vertexShader:THREE.ShaderLib.physical.vertexShader,fragmentShader:THREE.ShaderLib.physical.fragmentShader};
 material.onBeforeCompile(shader);assert.match(shader.fragmentShader,/cross\(dFdx\(vPaintWorld\),dFdy\(vPaintWorld\)\)/);
 assert.doesNotMatch(shader.vertexShader,/vPaintNormal|normalize\(.*objectNormal/);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
 const ao=new DeterministicGTAOPass(scene,camera,16,16);assert.equal(ao.normalMaterial.flatShading,true);ao.dispose();
});

test('T23透视相机遵循显式方位俯仰距离契约并支持乱序定位',async()=>{
 const root=await model(),camera=new THREE.PerspectiveCamera(40,16/9,.1,2500),ctx={model:root,camera,center:new THREE.Vector3(0,25.5,0),diagonal:167};
 for(const p of [{from_deg:35,to_deg:65,elevation_deg:22,distance:1.7},{from_deg:-50,to_deg:-10,elevation_deg:-4,distance:.92}]){
  const target=ctx.center.clone().add(new THREE.Vector3(0,6,0)),frames=new Map();
  for(const [t,angle] of [[0,p.from_deg],[2.5,(p.from_deg+p.to_deg)/2],[5,p.to_deg]]){
   frameModelOrbit(ctx,p,t,5);assert.equal(camera.projectionMatrix.elements[15],0);
   const v=camera.position.clone().sub(target),azimuth=THREE.MathUtils.radToDeg(Math.atan2(v.x,v.z)),elevation=THREE.MathUtils.radToDeg(Math.asin(v.y/v.length()));
   assert.ok(Math.abs(azimuth-angle)<1e-8);assert.ok(Math.abs(elevation-p.elevation_deg)<1e-8);assert.ok(Math.abs(v.length()-p.distance*ctx.diagonal)<1e-8);
   frames.set(t,[...camera.matrixWorld.elements,...camera.projectionMatrix.elements]);
  }
  for(const t of [2.5,0,5]){frameModelOrbit(ctx,p,t,5);assert.deepEqual([...camera.matrixWorld.elements,...camera.projectionMatrix.elements],frames.get(t));}
 }
});

test('新 GLB 起升始终保持绳顶和滑轮组连接',async()=>{
 const root=await model(),originals=[];root.traverse(n=>originals.push({n,p:n.position.clone(),s:n.scale.clone(),q:n.quaternion.clone()}));
 const ctx={model:root,originals,timeline:{facts:{}},center:new THREE.Vector3(0,25.5,0),diagonal:118,camera:new THREE.PerspectiveCamera(40,16/9,.1,2500),content:{innerHTML:''},floor:{material:{}}};
 const old=globalThis.document;globalThis.document={getElementById:()=>({innerHTML:''})};
 try{for(const y of [2,30.6,36,2]){
  for(const o of originals){o.n.position.copy(o.p);o.n.scale.copy(o.s);}
  motion(ctx,{params:{axis:'hoist',from_m:y,to_m:y}},1,5);root.updateMatrixWorld(true);
  const rope=new THREE.Box3().setFromObject(root.getObjectByName('rope'));
  assert.ok(Math.abs(rope.max.y-45.5)<1e-5);assert.ok(Math.abs(rope.min.y-(y+4.1))<1e-5);
 }
 for(const z of [-40,40,0]){
  for(const o of originals){o.n.position.copy(o.p);o.n.scale.copy(o.s);}
  motion(ctx,{params:{axis:'gantry',from_m:z,to_m:z}},1,5);root.updateMatrixWorld(true);
  assert.ok(Math.abs(root.getObjectByName('crane').getWorldPosition(new THREE.Vector3()).z-z)<1e-5);
  for(const id of ['rail_left','rail_right'])assert.ok(Math.abs(new THREE.Box3().setFromObject(root.getObjectByName(id)).getCenter(new THREE.Vector3()).z)<1e-5);
 }
 }finally{globalThis.document=old;}
});

test('足部外伸线对应有限长度的钢轨且位于基础内',async()=>{
 const root=await model();replaceCraneMaterials(root,51,'parametric');prepareRails(root);
 for(const [name,x] of [['rail_left',-44],['rail_right',44]]){
  const node=root.getObjectByName(name),bounds=new THREE.Box3().setFromObject(node),size=bounds.getSize(new THREE.Vector3());
  assert.ok(Math.abs(size.z-80)<1e-6);assert.ok(size.x<=1.5);assert.ok(size.y<.31);
  assert.ok(Math.abs(bounds.getCenter(new THREE.Vector3()).x-x)<1e-6);
  node.traverse(n=>{if(n.isMesh){assert.equal(n.material.name,'steel');assert.equal(n.material.flatShading,true);}});
 }
});

test('阴影相机覆盖设备和24度太阳的地面投影',()=>{
 const scene=new THREE.Scene(),sun=new THREE.DirectionalLight();scene.add(sun,sun.target);
 const bounds=new THREE.Box3(new THREE.Vector3(-64,0,-100),new THREE.Vector3(64,88,100));fitSunShadow(sun,bounds);sun.shadow.updateMatrices(sun);
 assert.ok(Math.abs(THREE.MathUtils.radToDeg(Math.asin(SUN_DIRECTION.y))-24)<1e-9);
 for(const p of boundsCorners(bounds))for(const v of [p,p.clone().addScaledVector(SUN_DIRECTION,-p.y/SUN_DIRECTION.y)]){
  const q=v.clone().project(sun.shadow.camera);assert.ok(Math.max(Math.abs(q.x),Math.abs(q.y),Math.abs(q.z))<=1.001);
 }
 assert.ok(sun.shadow.camera.right-sun.shadow.camera.left<400);
});

test('船厂全实例化、对象数量正确且跨次构建完全一致',()=>{
 const a=createShipyard(craneMaterials().glass),b=createShipyard(craneMaterials().glass);
 assert.deepEqual(a.userData.counts,{buildings:3,chimneys:2,crawlers:2,containers:16,segments:4,workers:15,lamps:5});
 assert.ok(a.children.length<40);
 a.children.forEach((mesh,i)=>{assert.ok(mesh.isInstancedMesh);assert.deepEqual(mesh.instanceMatrix.array,b.children[i].instanceMatrix.array);});
});

test('各方向厂房均在设备后方且镜头内变换不依赖时间',()=>{
 const bounds=new THREE.Box3(new THREE.Vector3(-52,0,-60),new THREE.Vector3(52,51,60));
 for(const angle of [-150,-30,0,65,170]){
  const camera=new THREE.PerspectiveCamera(40,16/9,.1,2500);camera.position.set(Math.sin(angle*Math.PI/180)*200,65,Math.cos(angle*Math.PI/180)*200);camera.lookAt(0,25.5,0);camera.updateMatrixWorld();
  const yard=createShipyard(craneMaterials().glass),placement=shipyardPlacement(camera,bounds);placeShipyard(yard,placement);
  const building=new THREE.Vector3(0,8,-380).applyMatrix4(yard.matrixWorld),forward=new THREE.Vector3();camera.getWorldDirection(forward);
  assert.ok(building.clone().sub(bounds.getCenter(new THREE.Vector3())).dot(forward)>300);
  assert.ok(Math.abs(building.clone().project(camera).x)<1);
 }
});

test('混凝土颜色与粗糙度贴图在平移和回跳后保持世界定位',()=>{
 const floor={position:new THREE.Vector3(),material:{map:new THREE.Texture(),roughnessMap:new THREE.Texture()}};
 for(const x of [0,40,-80,0]){
  placeConcreteGround(floor,{position:new THREE.Vector3(x,20,160)});
  for(const map of [floor.material.map,floor.material.roughnessMap]){assert.equal(map.offset.x,x/48);assert.equal(map.offset.y,-160/48);}
 }
});

test('AO初始化固定噪声不受全局随机数影响',()=>{
 const a=DeterministicGTAOPass.prototype.generateNoise(),b=DeterministicGTAOPass.prototype.generateNoise();assert.deepEqual(a.image.data,b.image.data);assert.ok(new Set(a.image.data).size>200);
});

test('投影测量不能被黑色剪影、灰色设备、空mask或背景橙色掩盖',async()=>{
 const {measureProjection,projectionPasses}=await import('./projection-metrics.mjs');
 const width=160,height=100,mask=new Uint8Array(width*height*4),pixels=new Uint8Array(mask.length);
 for(let y=0;y<height;y++)for(let x=0;x<width;x++){
  const i=(y*width+x)*4;pixels.set([217,70,28,255],i);
  if(x>=20&&x<140&&y>=10&&y<90)mask.set([255,255,255,255],i);
 }
 assert.equal(projectionPasses(measureProjection(pixels,mask,width,height)),true);
 for(const rgb of [[0,0,0],[100,100,100],[20,9,2]]){
  const defective=pixels.slice();for(let i=0;i<mask.length;i+=4)if(mask[i])defective.set([...rgb,255],i);
  assert.equal(projectionPasses(measureProjection(defective,mask,width,height)),false);
 }
 assert.equal(projectionPasses(measureProjection(pixels,new Uint8Array(mask.length),width,height)),false);
});

test('厂房以整栋为单位避免上边缘裁切，回跳可恢复',()=>{
 const yard=createShipyard(craneMaterials().glass),camera=new THREE.PerspectiveCamera(40,16/9,.1,2500);
 for(const targetY of [0,250,0]){
  camera.position.set(0,30,150);camera.lookAt(0,targetY,-380);camera.updateMatrixWorld();fitShipyardBuildings(yard,camera);
  const groups=new Map();
  for(const n of yard.children){if(!n.userData.building)continue;
   const id=n.userData.building;if(groups.has(id))assert.equal(n.visible,groups.get(id));else groups.set(id,n.visible);
   if(n.visible)for(const p of boundsCorners(n.boundingBox)){const q=p.applyMatrix4(n.matrixWorld).project(camera);assert.ok(q.y<=.94&&q.y>=-.94&&Math.abs(q.x)<=.97);}
  }
  assert.ok(groups.size===3);if(targetY===0)assert.ok([...groups.values()].some(Boolean));
 }
});

test('实测光比不能被平光、空mask或背景亮色通过',async()=>{
 const {measureLighting}=await import('./lighting-metrics.mjs');
 const w=100,h=60,mask=new Uint8Array(w*h*4),pixels=new Uint8Array(mask.length);
 for(let y=5;y<55;y++)for(let x=5;x<95;x++){
  const i=(y*w+x)*4;mask.set(x<50?[255,0,0,255]:[0,255,0,255],i);pixels.set(x<50?[200,100,50,255]:[40,20,10,255],i);
 }
 assert.ok(measureLighting(pixels,mask,w,h).ratio>=3);
 for(let i=0;i<pixels.length;i+=4)pixels.set([200,100,50,255],i);
 assert.equal(measureLighting(pixels,mask,w,h).ratio,1);
 assert.ok(!Number.isFinite(measureLighting(pixels,new Uint8Array(mask.length),w,h).ratio));
});
