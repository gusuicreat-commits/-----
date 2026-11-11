import * as THREE from 'three';
import {railFade,seededRandom} from './materials.js';

// 布景仅作尺度参照，不属于设备参数或运动节点。
export function createShipyard(glass){
 const root=new THREE.Group();root.name='shipyard';
 const mats={
  white:new THREE.MeshStandardMaterial({color:'#e4e2dc',roughness:.78}),
  roof:new THREE.MeshStandardMaterial({color:'#bbc3c4',metalness:.3,roughness:.5}),
  blue:new THREE.MeshStandardMaterial({color:'#23628c',metalness:.12,roughness:.55}),
  red:new THREE.MeshStandardMaterial({color:'#ad3927',roughness:.55,metalness:.25}),
  steel:new THREE.MeshStandardMaterial({color:'#657780',roughness:.4,metalness:.72}),
  rust:new THREE.MeshStandardMaterial({color:'#865040',roughness:.85}),
  green:new THREE.MeshStandardMaterial({color:'#65776b',roughness:.7}),
  dark:new THREE.MeshStandardMaterial({color:'#303b3e',roughness:.87}),
  vest:new THREE.MeshStandardMaterial({color:'#d5d74b',roughness:.7}),
  helmet:new THREE.MeshStandardMaterial({color:'#e9bb4b',roughness:.5}),
  skin:new THREE.MeshStandardMaterial({color:'#b58b70',roughness:.9}),glass,
  water:new THREE.MeshPhysicalMaterial({color:'#357b94',roughness:.24,metalness:.42,clearcoat:.7}),
 };
 const geometries={box:new THREE.BoxGeometry(1,1,1),rod:new THREE.CylinderGeometry(1,1,1,8),head:new THREE.SphereGeometry(1,10,8)};
 let batchGroup='yard';
 const batches=new Map(),dummy=new THREE.Object3D(),axis=new THREE.Vector3(0,1,0);
 function instance(shape,material,pos,scale,quaternion){
  const key=`${batchGroup}:${shape}:${material}`;if(!batches.has(key))batches.set(key,[]);
  dummy.position.set(...pos);dummy.scale.set(...scale);dummy.quaternion.copy(quaternion||new THREE.Quaternion());dummy.updateMatrix();batches.get(key).push(dummy.matrix.clone());
 }
 const box=(mat,size,pos)=>instance('box',mat,pos,size);
 function rod(mat,a,b,r){const av=new THREE.Vector3(...a),bv=new THREE.Vector3(...b),dir=bv.sub(av);instance('rod',mat,av.addScaledVector(dir,.5).toArray(),[r,dir.length(),r],new THREE.Quaternion().setFromUnitVectors(axis,dir.normalize()));}
 const rand=seededRandom(22004);
 // 建筑位于镜头后景，门朝向设备；低矮轮廓留出主梁和支腿。
 for(const [i,x] of [-100,-10,110].entries()){
  batchGroup=`building_${i}`;
  const w=65,h=15+i*2,z=-230-[0,65,18][i];
  box('white',[w,h,45],[x,h/2,z]);
  for(const side of [-1,1]){
   const q=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),side*.07);
   instance('box','roof',[x+side*w/4,h+.6,z],[w/2+1,.35,47],q);
  }
  box('blue',[27,h*.72,.25],[x,h*.36,z+22.7]);
  for(let j=0;j<10;j++)box('steel',[.09,h*.72,.3],[x-13+j*2.8,h*.36,z+22.9]);
  for(const dx of [-20,20])box('glass',[8,.16,35],[x+dx,h+1.3,z]);
  for(let j=0;j<8;j++)box('glass',[4,1.6,.16],[x-w/2+5+j*8,h-2.3,z+22.65]);
 }
 batchGroup='yard';
 for(const x of [-116,105]){
  box('dark',[5,.5,5],[x,.25,-201]);
  rod('white',[x,.5,-201],[x,37,-201],1.8);
  for(const y of [25,30,35])rod('red',[x,y,-201],[x,y+2,-201],1.83);
 }
 // 履带和四弦格构臂，交替红白节段。
 for(const side of [-1,1]){
  const x=side*132,z=-118;
  for(const dx of [-2.1,2.1])box('dark',[1.5,1.4,8],[x+dx,.7,z]);
  box('helmet',[5,2.8,5.5],[x,2.7,z]);box('glass',[2,1.7,.15],[x,3.1,z+2.85]);
  for(let i=0;i<12;i++){
   const a=[x+side*i*1.4,4+i*3.7,z],b=[x+side*(i+1)*1.4,4+(i+1)*3.7,z],mat=i%4<2?'white':'red';
   for(const dx of [-.9,.9])for(const dz of [-.9,.9])rod(mat,[a[0]+dx,a[1],a[2]+dz],[b[0]+dx,b[1],b[2]+dz],.095);
   for(const dz of [-.9,.9]){rod(mat,[a[0]-.9,a[1],z+dz],[b[0]+.9,b[1],z+dz],.06);rod(mat,[a[0]+.9,a[1],z+dz],[b[0]-.9,b[1],z+dz],.06);}
   for(const dx of [-.9,.9])rod(mat,[a[0]+dx,a[1],z-.9],[b[0]+dx,b[1],z+.9],.06);
  }
  rod('dark',[x+side*16.8,48.4,z],[x+side*16.8,8,z],.035);
 }
 for(let i=0;i<16;i++){
  const x=70+(i%8)*6.4,z=-108-Math.floor(i/8)*6,y=1.3,mat=['rust','blue','green'][i%3];
  box(mat,[6,2.6,2.5],[x,y,z]);
  for(let rib=0;rib<12;rib++)box(mat,[.07,2.45,.08],[x-2.8+rib*.5,y,z+1.29]);
 }
 for(let i=0;i<4;i++){
  const x=-82+i*17,z=-90-rand()*18;
  box('rust',[13,.3,8],[x,.7,z]);
  for(const dx of [-6.3,6.3])box('rust',[.3,4,8],[x+dx,2.7,z]);
  for(let j=0;j<4;j++)box('steel',[.3,2.2,7.6],[x-5+j*3.2,1.9,z]);
 }
 for(const [gx,gz] of [[-42,26],[40,16],[0,-35],[64,-8]]){
  const count=gx===64?3:4;
  for(let i=0;i<count;i++){
   const x=gx+(i%2)*1.1+rand()*.25,z=gz+Math.floor(i/2)*1.4;
   for(const dx of [-.13,.13])rod('dark',[x+dx,.05,z],[x+dx,.85,z],.085);
   box('vest',[.45,.6,.28],[x,1.12,z]);box('white',[.46,.07,.29],[x,1.1,z]);
   for(const dx of [-.3,.3])rod('skin',[x+dx,.8,z],[x+dx,1.35,z],.065);
   instance('head','skin',[x,1.55,z],[.13,.16,.13]);instance('head','helmet',[x,1.68,z],[.18,.12,.18]);
  }
 }
 for(const [x,z] of [[-78,5],[78,0],[-100,-95],[95,-110],[0,-110]]){
  rod('steel',[x,0,z],[x,23,z],.2);box('white',[5,.25,.7],[x,23,z]);
  for(const dx of [-2,-.7,.7,2])box('glass',[.8,.12,.65],[x+dx,22.82,z]);
 }
 box('water',[1300,.04,2500],[-950,-.035,-400]);
 for(const [key,matrices] of batches){
  const [group,shape,material]=key.split(':'),mesh=new THREE.InstancedMesh(geometries[shape],mats[material],matrices.length);
  matrices.forEach((matrix,i)=>mesh.setMatrixAt(i,matrix));mesh.instanceMatrix.needsUpdate=true;
  mesh.castShadow=material!=='water';mesh.receiveShadow=true;mesh.name=`yard_${key}`;mesh.userData.building=group.startsWith('building_')?group:null;root.add(mesh);
 }
 root.userData.counts={buildings:3,chimneys:2,crawlers:2,containers:16,segments:4,workers:15,lamps:5};
 return root;
}

export function shipyardPlacement(camera,bounds){
 const center=bounds.getCenter(new THREE.Vector3()),size=bounds.getSize(new THREE.Vector3());
 const back=camera.position.clone().sub(center);back.y=0;if(back.lengthSq()<1e-6)back.set(0,0,1);back.normalize();
 const angle=Math.atan2(back.x,back.z);
 // 根据地面外包向后平移，大跨度类比也不把厂房放到参照物前面。
 const depth=Math.abs(back.x)*size.x+Math.abs(back.z)*size.z;
 const offset=Math.max(0,depth/2-45);
 return {angle,position:new THREE.Vector3(center.x,0,center.z).addScaledVector(back,-offset)};
}

export function placeShipyard(root,placement){root.position.copy(placement.position);root.rotation.y=placement.angle;root.updateMatrixWorld(true);}

export function createRailFoundations(span){
 const mesh=new THREE.InstancedMesh(new THREE.BoxGeometry(2.4,.12,80),railFade(new THREE.MeshStandardMaterial({color:'#d4d4ce',roughness:.94})),2);
 for(let i=0;i<2;i++)mesh.setMatrixAt(i,new THREE.Matrix4().makeTranslation((i-.5)*span,-.025,0));
 mesh.instanceMatrix.needsUpdate=true;mesh.receiveShadow=true;mesh.name='rail_foundations';return mesh;
}

// 按整栋建筑处理边缘裁切，不能逐个屋顶/墙面隐藏而留下半截建筑。
export function fitShipyardBuildings(root,camera){
 const buildings=new Map();
 root.updateMatrixWorld(true);camera.updateMatrixWorld();
 for(const mesh of root.children){
  const id=mesh.userData.building;if(!id)continue;
  mesh.visible=true;mesh.computeBoundingBox();
  if(!buildings.has(id))buildings.set(id,{meshes:[],bounds:new THREE.Box3()});
  const group=buildings.get(id);group.meshes.push(mesh);group.bounds.union(mesh.boundingBox.clone().applyMatrix4(mesh.matrixWorld));
 }
 for(const {meshes,bounds} of buildings.values()){
  let complete=true;
  for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z]){
   const p=new THREE.Vector3(x,y,z).project(camera);
   if(Math.abs(p.x)>.97||Math.abs(p.y)>.94||Math.abs(p.z)>1)complete=false;
  }
  for(const mesh of meshes)mesh.visible=complete;
 }
}
