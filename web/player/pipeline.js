import * as THREE from 'three';
import {Sky} from 'three/addons/objects/Sky.js';
import {EffectComposer} from 'three/addons/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/addons/postprocessing/RenderPass.js';
import {GTAOPass} from 'three/addons/postprocessing/GTAOPass.js';
import {UnrealBloomPass} from 'three/addons/postprocessing/UnrealBloomPass.js';
import {ShaderPass} from 'three/addons/postprocessing/ShaderPass.js';
import {SMAAPass} from 'three/addons/postprocessing/SMAAPass.js';
import {OutputPass} from 'three/addons/postprocessing/OutputPass.js';
import {seededRandom} from './materials.js';
import {boundsCorners} from './shots/common.js';

export const SUN_ELEVATION=24;
export const SUN_DIRECTION=new THREE.Vector3().setFromSphericalCoords(1,THREE.MathUtils.degToRad(90-SUN_ELEVATION),THREE.MathUtils.degToRad(-75));
export const LOOK={exposure:1.05,sunIntensity:3.6,sunColor:'#fffaf5',environmentIntensity:.9,fogDensity:.0003};
export const gradeShader={
 uniforms:{tDiffuse:{value:null},vignette:{value:.25},contrast:{value:1.05},saturation:{value:1.08}},
 vertexShader:'varying vec2 vUv; void main(){vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}',
 fragmentShader:`uniform sampler2D tDiffuse;uniform float vignette,contrast,saturation;varying vec2 vUv;
 void main(){vec4 c=texture2D(tDiffuse,vUv);float l=dot(c.rgb,vec3(.2126,.7152,.0722));
 c.rgb=max(vec3(0.),mix(vec3(l),c.rgb,saturation));c.rgb=max(vec3(0.),(c.rgb-.18)*contrast+.18);
 vec2 p=(vUv-.5)*1.41421356;c.rgb*=1.-vignette*smoothstep(.22,1.,dot(p,p));gl_FragColor=c;}`,
};

// 重载初始化噪声，既不修改全局随机数，也不积累历史帧。
export class DeterministicGTAOPass extends GTAOPass{
 constructor(...args){super(...args);this.normalMaterial.flatShading=true;}
 overrideVisibility(){super.overrideVisibility();const sky=this.scene.getObjectByName('day_sky');if(sky)sky.visible=false;}
 generateNoise(size=64){const rand=seededRandom(22022),data=new Uint8Array(size*size*4);for(let i=0;i<data.length;i++)data[i]=Math.floor(rand()*256);
  const texture=new THREE.DataTexture(data,size,size);texture.wrapS=texture.wrapT=THREE.RepeatWrapping;texture.needsUpdate=true;return texture;}
}

export function fitSunShadow(sun,bounds){
 const center=bounds.getCenter(new THREE.Vector3()),size=bounds.getSize(new THREE.Vector3());
 const distance=Math.max(200,size.length()*2);
 sun.target.position.copy(center);sun.position.copy(center).addScaledVector(SUN_DIRECTION,distance);
 sun.updateMatrixWorld();sun.target.updateMatrixWorld();sun.shadow.updateMatrices(sun);
 const lightBounds=new THREE.Box3();
 // 同时包括落到地面的长投影，避免下午低太阳切掉阴影末端。
 for(const p of boundsCorners(bounds)){
  lightBounds.expandByPoint(p.clone().applyMatrix4(sun.shadow.camera.matrixWorldInverse));
  const ground=p.clone().addScaledVector(SUN_DIRECTION,-p.y/SUN_DIRECTION.y);
  lightBounds.expandByPoint(ground.applyMatrix4(sun.shadow.camera.matrixWorldInverse));
 }
 const padding=Math.max(3,size.length()*.025),c=sun.shadow.camera;
 c.left=lightBounds.min.x-padding;c.right=lightBounds.max.x+padding;c.bottom=lightBounds.min.y-padding;c.top=lightBounds.max.y+padding;
 c.near=Math.max(.1,-lightBounds.max.z-padding);c.far=-lightBounds.min.z+padding;c.updateProjectionMatrix();
 sun.shadow.bias=-.00006;sun.shadow.normalBias=.035;
}

// 用同一块水平灰卡分离直射光和天空光，避免把灯强度数字误当成照度比。
function meterEnvironment(renderer,texture){
 const probe=new THREE.Scene(),camera=new THREE.OrthographicCamera(-1,1,1,-1,.1,10);
 camera.position.set(0,4,0);camera.up.set(0,0,-1);camera.lookAt(0,0,0);
 const material=new THREE.MeshStandardMaterial({color:'#808080',roughness:1,metalness:0});
 const card=new THREE.Mesh(new THREE.PlaneGeometry(2,2),material);card.rotation.x=-Math.PI/2;probe.add(card);
 const light=new THREE.DirectionalLight(LOOK.sunColor,LOOK.sunIntensity);light.position.copy(SUN_DIRECTION).multiplyScalar(5);probe.add(light);
 const target=new THREE.WebGLRenderTarget(1,1,{type:THREE.FloatType,depthBuffer:false});
 const previous=renderer.getRenderTarget(),toneMapping=renderer.toneMapping,pixel=new Float32Array(4);
 const sample=()=>{renderer.setRenderTarget(target);renderer.render(probe,camera);renderer.readRenderTargetPixels(target,0,0,1,1,pixel);return pixel[0]*.2126+pixel[1]*.7152+pixel[2]*.0722;};
 try{
  renderer.toneMapping=THREE.NoToneMapping;
  const direct=sample();light.intensity=0;probe.environment=texture;probe.environmentIntensity=1;
  const ambient=sample(),intensity=direct/(4*ambient);
  if(Number.isFinite(intensity)&&intensity>0){
   probe.environmentIntensity=intensity;
   const calibratedAmbient=sample();
   return {intensity,ratio:direct/calibratedAmbient,direct,ambient:calibratedAmbient};
  }
  throw new Error('天空照度测量失败，无法校准太阳与环境光比');
 }finally{renderer.setRenderTarget(previous);renderer.toneMapping=toneMapping;target.dispose();card.geometry.dispose();material.dispose();}
}

export async function createPipeline(renderer,scene,camera,{quality='standard'}={}){
 renderer.toneMapping=THREE.AgXToneMapping;renderer.toneMappingExposure=LOOK.exposure;
 renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
 const sky=new Sky();sky.name='day_sky';sky.scale.setScalar(1800);sky.material.depthWrite=false;
 Object.assign(sky.material.uniforms.turbidity,{value:2.5});sky.material.uniforms.rayleigh.value=1.2;
 sky.material.uniforms.mieCoefficient.value=.004;sky.material.uniforms.mieDirectionalG.value=.8;sky.material.uniforms.sunPosition.value.copy(SUN_DIRECTION);
 scene.add(sky);scene.background=new THREE.Color('#c7dce8');scene.fog=new THREE.FogExp2('#c7dce8',LOOK.fogDensity);
 const pmrem=new THREE.PMREMGenerator(renderer),environmentScene=new THREE.Scene();environmentScene.add(sky.clone());
 const environment=pmrem.fromScene(environmentScene,.02,.1,3000);scene.environment=environment.texture;pmrem.dispose();
 // 显示天空单独压低辐亮度，避免输出映射把近地平线挤成灰白；测光仍使用原始天空。
 sky.material=sky.material.clone();
 sky.material.fragmentShader=sky.material.fragmentShader.replace('vec4( retColor, 1.0 )',`vec4(
  mix(vec3(.30,.48,.70),vec3(.006,.19,.65),
   smoothstep(-.025,.20,normalize(vWorldPosition-cameraPosition).y)),1.0)`);
 const lighting=meterEnvironment(renderer,environment.texture);scene.environmentIntensity=lighting.intensity;
 const sun=new THREE.DirectionalLight(LOOK.sunColor,LOOK.sunIntensity);sun.castShadow=true;sun.shadow.mapSize.set(4096,4096);sun.shadow.autoUpdate=false;sun.shadow.radius=2;
 scene.add(sun,sun.target);
 const composer=new EffectComposer(renderer);composer.setSize(1920,1080);
 const renderPass=new RenderPass(scene,camera);composer.addPass(renderPass);
 const ao=new DeterministicGTAOPass(scene,camera,960,540,undefined,{radius:1.2,thickness:1,distanceFallOff:1});
 ao.blendIntensity=.45;composer.addPass(ao);
 // 半分辨率 AO 保留接触阴影，并控制正常导出开销。
 ao.setSize(960,540);
 const bloom=new UnrealBloomPass(new THREE.Vector2(960,540),.12,.35,1.5);composer.addPass(bloom);bloom.setSize(960,540);
 const grade=new ShaderPass(gradeShader);composer.addPass(grade);
 const smaa=new SMAAPass(1920,1080);composer.addPass(smaa);composer.addPass(new OutputPass());
 // 查找表必须在 ready 前解码，避免第一次定位与后续帧不同。
 await Promise.all([smaa.areaTexture.image,smaa.searchTexture.image].map(image=>image.decode()));
 smaa.areaTexture.needsUpdate=true;smaa.searchTexture.needsUpdate=true;
 const draft=quality==='draft';ao.enabled=!draft;bloom.enabled=!draft;
 let shadowKey=null;
 return {sky,sun,composer,ao,bloom,quality,draft,environment,
  render({shot,bounds,scale=100,macro=false,moving=false}){
   renderer.toneMappingExposure=LOOK.exposure;
   sky.visible=!macro;scene.fog=macro?null:(scene.fog||new THREE.FogExp2('#c7dce8',LOOK.fogDensity));
   scene.background.set(macro?'#142330':'#c7dce8');
   // 每个镜头使用固定外包，移动部件每帧重绘阴影；静态环绕复用阴影。
   if(shadowKey!==shot.id){fitSunShadow(sun,bounds);sun.shadow.needsUpdate=true;shadowKey=shot.id;}
   if(moving)sun.shadow.needsUpdate=true;
   ao.enabled=!draft&&!macro;bloom.enabled=!draft;
   ao.updateGtaoMaterial({radius:Math.max(.25,Math.min(2,scale*.012))});
   const perspective=camera.projectionMatrix.elements[15]===0?1:0;
   if(ao.gtaoMaterial.defines.PERSPECTIVE_CAMERA!==perspective){ao.gtaoMaterial.defines.PERSPECTIVE_CAMERA=perspective;ao.gtaoMaterial.needsUpdate=true;}
   // 正交镜头的近远面需要与投影矩阵一致，微距由上述分支绕过 AO。
   const start=performance.now();composer.render(0);
   return {submitMs:performance.now()-start,drawCalls:renderer.info.render.calls,quality,ao:ao.enabled,bloom:bloom.enabled,sunSkyRatio:lighting.ratio,environmentIntensity:lighting.intensity,sunIrradiance:lighting.direct,skyIrradiance:lighting.ambient};
  },
 };
}
