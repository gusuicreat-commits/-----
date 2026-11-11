import * as THREE from 'three';

export function seededRandom(seed=22019){
 return ()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
}

export function craneMaterials(height=51){
 const paint=new THREE.MeshPhysicalMaterial({name:'paint',color:'#D9461C',metalness:.12,roughness:.38,clearcoat:.3,clearcoatRoughness:.25});
 paint.onBeforeCompile=shader=>{
  shader.uniforms.paintHeight={value:height};
  shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying vec3 vPaintWorld;')
   .replace('#include <worldpos_vertex>','#include <worldpos_vertex>\nvPaintWorld=(modelMatrix*vec4(transformed,1.0)).xyz;');
  shader.fragmentShader=shader.fragmentShader.replace('#include <common>',`#include <common>
   varying vec3 vPaintWorld; uniform float paintHeight;
   float paintHash(vec3 p){return fract(sin(dot(p,vec3(127.1,311.7,74.7)))*43758.5453);}
   float paintNoise(vec3 p){vec3 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);
    return mix(mix(mix(paintHash(i),paintHash(i+vec3(1,0,0)),f.x),mix(paintHash(i+vec3(0,1,0)),paintHash(i+vec3(1,1,0)),f.x),f.y),
    mix(mix(paintHash(i+vec3(0,0,1)),paintHash(i+vec3(1,0,1)),f.x),mix(paintHash(i+vec3(0,1,1)),paintHash(i+vec3(1,1,1)),f.x),f.y),f.z);}`)
   .replace('#include <color_fragment>',`#include <color_fragment>
    float paintVariation=paintNoise(vPaintWorld*3.7)*2.0-1.0;
    diffuseColor.rgb*=1.0+paintVariation*.012;
    float lowWear=1.0-smoothstep(0.0,paintHeight*.18,vPaintWorld.y);
    vec3 paintNormal=normalize(cross(dFdx(vPaintWorld),dFdy(vPaintWorld)));
    paintNormal*=gl_FrontFacing?1.0:-1.0;
    float downWear=smoothstep(.2,.9,-paintNormal.y);
    float edgeWear=clamp(length(fwidth(paintNormal))*.7,0.0,1.0);
    float wear=smoothstep(.77,.96,paintNoise(vPaintWorld*17.0))*(lowWear*.12+downWear*.08+edgeWear*.12);
    diffuseColor.rgb=mix(diffuseColor.rgb,vec3(.055,.029,.018),wear);`)
   .replace('#include <roughnessmap_fragment>','#include <roughnessmap_fragment>\nroughnessFactor=clamp(roughnessFactor+paintVariation*.025,.05,1.0);');
 };
 paint.customProgramCacheKey=()=> 'crane-paint-v2';
 return {
  paint,
  primer:new THREE.MeshStandardMaterial({name:'primer',color:'#e4e6e5',roughness:.6,metalness:.08}),
  steel:new THREE.MeshStandardMaterial({name:'steel',color:'#8c99a2',roughness:.23,metalness:.92}),
  glass:new THREE.MeshPhysicalMaterial({name:'glass',color:'#567b91',roughness:.12,metalness:.35,transmission:0,ior:1.5,clearcoat:1,envMapIntensity:1.4}),
  rubber:new THREE.MeshStandardMaterial({name:'rubber',color:'#24282b',roughness:.92}),
  hazard:new THREE.MeshStandardMaterial({name:'hazard',color:'#e9af32',roughness:.46,metalness:.15}),
 };
}

export function replaceCraneMaterials(model,height,kind){
 const palette=craneMaterials(height);
 model.traverse(node=>{
  if(!node.isMesh)return;
  node.material=[].concat(node.material).map(material=>{
   if(palette[material.name])return palette[material.name];
   if(kind!=='parametric')return material.clone();
   // 兼容早期未命名的参数化文件；导入模型保留原材质。
   let owner=node;while(owner.parent&&!['girder','leg_left','leg_right','trolley','hoist_hook','rope','rail_left','rail_right','cab'].includes(owner.name))owner=owner.parent;
   if(['rail_left','rail_right','rope'].includes(owner.name))return palette.steel;
   if(owner.name==='hoist_hook')return palette.hazard;
   if(material.color?.b>material.color?.r*1.15&&owner.name==='cab')return palette.glass;
   return palette.paint;
  });
  node.material=node.material.map(base=>{
   const material=base.clone();
   // 无法线的 GLB 必须使用面导数；替换材质不能丢失此加载语义。
   material.flatShading=!node.geometry.hasAttribute('normal')||base.flatShading;
   material.onBeforeCompile=base.onBeforeCompile;material.customProgramCacheKey=base.customProgramCacheKey;return material;
  });
  if(node.material.length===1)node.material=node.material[0];
 });
 return palette;
}

// 轨道端部以固定世界坐标淡出。
export function railFade(material){
 material.transparent=true;material.depthWrite=false;
 material.onBeforeCompile=shader=>{
  shader.vertexShader=shader.vertexShader.replace('#include <common>','#include <common>\nvarying float vRailZ;')
   .replace('#include <begin_vertex>','#include <begin_vertex>\nvRailZ=(modelMatrix*vec4(position,1.0)).z;');
  shader.fragmentShader=shader.fragmentShader.replace('#include <common>','#include <common>\nvarying float vRailZ;')
   .replace('#include <alphatest_fragment>','#include <alphatest_fragment>\ndiffuseColor.a*=1.0-smoothstep(30.0,40.0,abs(vRailZ));if(abs(vRailZ)>=40.0)discard;');
 };
 material.customProgramCacheKey=()=> 'rail-fade-v1';return material;
}

export function prepareRails(model){
 model.updateMatrixWorld(true);
 for(const name of ['rail_left','rail_right']){
  const rail=model.getObjectByName(name);if(!rail)continue;
  const length=new THREE.Box3().setFromObject(rail).getSize(new THREE.Vector3()).z;
  if(length>80)rail.scale.z*=80/length;
  rail.traverse(n=>{if(!n.isMesh)return;
   n.material=railFade(new THREE.MeshStandardMaterial({name:'steel',color:'#bec9cd',metalness:.5,roughness:.3,flatShading:!n.geometry.hasAttribute('normal')}));
   // 薄轨的亚像素投影容易成为长黑线；基础和设备仍接收真实阴影。
   n.userData.noCastShadow=true;
  });
 }
 model.updateMatrixWorld(true);
}

export function concreteTextures(){
 const size=2048,rand=seededRandom(22002),canvas=document.createElement('canvas'),rough=document.createElement('canvas');
 canvas.width=canvas.height=rough.width=rough.height=size;
 const g=canvas.getContext('2d'),r=rough.getContext('2d'),pixels=g.createImageData(size,size),roughPixels=r.createImageData(size,size);
 const patches=Array.from({length:64},()=>rand()*12-6);
 const slabs=new Array(16);
 // 各列均值一致，避免重复平铺形成整条明暗色带。
 for(let x=0;x<4;x++){const a=rand()*8-4,b=rand()*8-4;[a,b,-a,-b].forEach((v,y)=>slabs[y*4+x]=v);}
 for(let y=0;y<size;y++)for(let x=0;x<size;x++){
  const u=x/size*8,v=y/size*8,ix=Math.floor(u),iy=Math.floor(v),fx=u-ix,fy=v-iy;
  const p=(a,b)=>patches[(b%8)*8+a%8];
  const broad=THREE.MathUtils.lerp(THREE.MathUtils.lerp(p(ix,iy),p(ix+1,iy),fx),THREE.MathUtils.lerp(p(ix,iy+1),p(ix+1,iy+1),fx),fy);
  const grain=(rand()-.5)*6,delta=broad+grain+slabs[Math.floor(y/512)*4+Math.floor(x/512)],index=(y*size+x)*4;
  [156,150,140].forEach((c,k)=>pixels.data[index+k]=c+delta);pixels.data[index+3]=255;
  const value=229+broad+grain;roughPixels.data.set([value,value,value,255],index);
 }
 g.putImageData(pixels,0,0);r.putImageData(roughPixels,0,0);
 // 一张覆盖 48 m，四块 12 m 大板；缝约 70 mm，不画调试网格。
 g.strokeStyle='rgba(67,63,57,.20)';g.lineWidth=3;
 for(let i=0;i<4;i++){
  const p=i*512+.5;g.beginPath();g.moveTo(p,0);g.lineTo(p,size);g.moveTo(0,p);g.lineTo(size,p);g.stroke();
 }
 for(let i=0;i<13;i++){
  const x=rand()*size,y=rand()*size,rx=8+rand()*38,ry=4+rand()*15;
  const gradient=g.createRadialGradient(x,y,0,x,y,rx);gradient.addColorStop(0,'rgba(45,40,30,.13)');gradient.addColorStop(1,'rgba(45,40,30,0)');
  g.fillStyle=gradient;g.beginPath();g.ellipse(x,y,rx,ry,rand()*Math.PI,0,Math.PI*2);g.fill();
  r.fillStyle='#b8b8b8';r.beginPath();r.ellipse(x,y,rx,ry,0,0,Math.PI*2);r.fill();
 }
 g.strokeStyle='rgba(40,37,33,.065)';g.lineWidth=3;
 for(let i=0;i<5;i++){const x=rand()*size,y=rand()*size;for(const d of [0,24]){g.beginPath();g.moveTo(x+d,y);g.bezierCurveTo(x+d+14,y+80,x+d-15,y+130,x+d+9,y+200);g.stroke();}}
 const map=new THREE.CanvasTexture(canvas),roughnessMap=new THREE.CanvasTexture(rough);
 map.colorSpace=THREE.SRGBColorSpace;
 for(const texture of [map,roughnessMap]){texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.anisotropy=4;}
 return {map,roughnessMap};
}

export function createConcreteGround(camera){
 const textures=concreteTextures(),extent=camera.far*4;
 for(const texture of Object.values(textures))texture.repeat.set(extent/48,extent/48);
 const floor=new THREE.Mesh(new THREE.PlaneGeometry(extent,extent),new THREE.MeshStandardMaterial({...textures,roughness:1,metalness:.025}));
 // 扩大地面接收器的 PCF 软核，4096 阴影图保留设备细节。
 floor.material.onBeforeCompile=shader=>{
  shader.fragmentShader=shader.fragmentShader.replace('#include <shadowmap_pars_fragment>',THREE.ShaderChunk.shadowmap_pars_fragment.replaceAll('vec2 texelSize = vec2( 1.0 ) / shadowMapSize;','vec2 texelSize = vec2( 3.0 ) / shadowMapSize;'));
 };
 floor.material.customProgramCacheKey=()=> 'concrete-soft-shadow-v1';
 floor.name='concrete_ground';floor.rotation.x=-Math.PI/2;floor.position.y=-.08;floor.receiveShadow=true;
 return floor;
}

export function placeConcreteGround(floor,camera){
 floor.position.x=camera.position.x;floor.position.z=camera.position.z;
 for(const map of [floor.material.map,floor.material.roughnessMap])map.offset.set(floor.position.x/48,-floor.position.z/48);
}
