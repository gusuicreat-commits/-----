import {createPipeline} from './pipeline.js';
import {createConcreteGround,placeConcreteGround,prepareRails,replaceCraneMaterials} from './materials.js';
import {createShipyard,shipyardPlacement,placeShipyard,createRailFoundations,fitShipyardBuildings} from './environment.js';
import {backgroundFrame,anchorPoints,dimensionPoints,loadBackgrounds,showBackground} from './background.js';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { clamp, esc, source, labelNodes } from './shots/common.js';
import * as title from './shots/title.js';
import * as model_orbit from './shots/model_orbit.js';
import * as analogy from './shots/analogy.js';
import * as motion from './shots/motion.js';
import * as exploded from './shots/exploded.js';
import * as data_card from './shots/data_card.js';
import * as real_media from './shots/real_media.js';
import * as ai_broll from './shots/ai_broll.js';
import * as weld_macro from './shots/weld_macro.js';
import * as outro from './shots/outro.js';
const kinds={title,model_orbit,analogy,motion,exploded,data_card,real_media,ai_broll,weld_macro,outro};
const $=id=>document.getElementById(id), query=new URLSearchParams(location.search), preview=query.get('mode')!=='render';
// 串行定位，避免视频解码与快速拖动交叉覆盖。
const listeners=new Map();let ctx,currentTime=0,lastShot=null,queue=Promise.resolve();
// 内部渲染状态供投影回归读取，不改变时间线或 window 播放器接口。
export {ctx as renderContext};
const api=window.__player={duration:0,ready:null,seek(t){const job=queue.then(()=>api.ready).then(()=>drawFrame(t));queue=job.catch(()=>{});return job;},on(event,cb){if(!listeners.has(event))listeners.set(event,new Set());listeners.get(event).add(cb);return()=>listeners.get(event).delete(cb);}};
function resize(){const availableH=innerHeight-(preview?58:0),scale=Math.min(innerWidth/1920,availableH/1080);$('stage').style.transform=`translate(${(innerWidth-1920*scale)/2}px,${(availableH-1080*scale)/2}px) scale(${scale})`;}
window.addEventListener('resize',resize);$('controls').hidden=!preview;$('controls').style.display=preview?'flex':'none';resize();
async function loadMedia(asset,resolve){
 const el=document.createElement(asset.kind==='video'?'video':'img');el.src=resolve(asset.url);if(asset.kind==='video'){el.muted=true;el.preload='auto';el.playsInline=true;await new Promise((ok,no)=>{el.onloadeddata=ok;el.onerror=()=>no(new Error('视频加载失败'));el.load();});}else await el.decode();return el;
}
api.ready=(async()=>{
 const timelineURL=new URL(query.get('timeline') || '/fixtures/timeline.json',location.href);
 const response=await fetch(timelineURL);if(!response.ok)throw new Error(`时间线加载失败（${response.status}）`);
 const timeline=await response.json();const resolve=url=>new URL(url,timelineURL).href;
 if(!timeline.shots?.length || !Number.isFinite(timeline.duration_s))throw new Error('时间线缺少镜头或有效时长');
 // 显式标准模式忽略离线背景；旧时间线仍可使用已提供的背景帧。
 if(timeline.render_mode==='standard')for(const shot of timeline.shots)delete shot.bg;
 const renderer=new THREE.WebGLRenderer({canvas:$('scene'),antialias:false,preserveDrawingBuffer:true});renderer.setSize(1920,1080);renderer.setPixelRatio(1);
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1920/1080,.1,2500);
 const pipeline=await createPipeline(renderer,scene,camera,{quality:query.get('quality')==='draft'?'draft':'standard'});
 const floor=createConcreteGround(camera);scene.add(floor);
 const photoreal=timeline.render_mode==='photoreal';
 const loadStart=performance.now();
 const gltf=timeline.model?.glb?await new GLTFLoader().loadAsync(resolve(timeline.model.glb)):null;const model=gltf?.scene || new THREE.Group();scene.add(model);
 const bounds=new THREE.Box3().setFromObject(model),size=bounds.isEmpty()?new THREE.Vector3(104,51,20):bounds.getSize(new THREE.Vector3()),center=bounds.isEmpty()?new THREE.Vector3(0,25,0):bounds.getCenter(new THREE.Vector3());
 if(timeline.model?.rig?.bbox_m){const b=timeline.model.rig.bbox_m;size.set(b.x,b.y,b.z);center.set(0,b.y/2,0);}
 const modelLoadMs=performance.now()-loadStart;
 const palette=replaceCraneMaterials(model,size.y,timeline.model?.kind);
 prepareRails(model);
 const yard=createShipyard(palette.glass),foundations=createRailFoundations(Number(timeline.facts?.F_span?.value||size.x*.85));scene.add(yard,foundations);
 const originals=[];model.traverse(n=>{originals.push({n,p:n.position.clone(),s:n.scale.clone(),q:n.quaternion.clone(),v:n.visible});if(n.isMesh){n.castShadow=!n.userData.noCastShadow;n.receiveShadow=true;}});
 const materials=[];model.traverse(n=>{if(n.isMesh)for(const m of [].concat(n.material))if(m.emissive)materials.push({m,e:m.emissive.clone(),i:m.emissiveIntensity});});
 const backgroundAnchors=new Map(),preloaded=new Map();
 for(const shot of timeline.shots.filter(s=>s.bg)){
  try{const anchors=await loadBackgrounds([shot],resolve);backgroundAnchors.set(shot.id,anchors.get(shot.id));}
  catch{delete shot.bg;console.warn(`镜头 ${shot.id} 背景不可用，已切换为标准画面`);}
 }
 const media=new Map();await Promise.all(Object.entries(timeline.assets||{}).map(async([id,a])=>media.set(id,await loadMedia(a,resolve))));
 await document.fonts.load('800 96px "PingFang SC"');await document.fonts.load('44px "Noto Sans SC"');await document.fonts.ready;
 ctx={photoreal,pipeline,yard,foundations,plans:new Map(),backgroundAnchors,preloaded,timeline,renderer,scene,model,floor,originals,materials,camera,center,diagonal:size.length(),size,media,content:$('content'),labels:$('labels'),creative:$('creative'),mediaLayer:$('media'),groups:new Map(),resolve};
 for(const shot of timeline.shots){shot.params ||= {};if(!kinds[shot.kind])throw new Error(`不支持的镜头类型：${shot.kind}`);await kinds[shot.kind].setup(ctx,{...shot,bg:undefined});}
 for(const group of ctx.groups.values())group.traverse(node=>{if(node.isMesh&&node.name==='building-window')node.material=palette.glass;});
 for(const shot of timeline.shots)await prepareShot(shot);
 api.metrics={modelLoadMs};
 api.duration=timeline.duration_s;$('scrub').max=api.duration;$('film-title').textContent=timeline.title || timeline.shots[0].params?.title || '工程的尺度';
 await drawFrame(0);if(preview)setupPreview();
})().catch(e=>{$('error').style.display='block';$('error').textContent=`播放器加载失败：${e.message}`;throw e;});
function resetScene(){
 ctx.originals.forEach(({n,p,s,q,v})=>{n.position.copy(p);n.scale.copy(s);n.quaternion.copy(q);n.visible=v;});
 ctx.materials.forEach(({m,e,i})=>{m.emissive.copy(e);m.emissiveIntensity=i;});
 ctx.camera.near=.1;ctx.camera.fov=40;ctx.camera.updateProjectionMatrix();ctx.model.visible=true;ctx.floor.visible=true;
 ctx.scene.background.set('#c7dce8');
 for(const g of ctx.groups.values())g.visible=false;
}
async function prepareShot(shot){
 if(shot.bg)return;
 resetScene();
 // 用固定镜头起点计算布景与阴影，首次 seek 的顺序不影响画面。
 const standardShot={...shot,bg:undefined};
 if(!['real_media','ai_broll'].includes(shot.kind))await kinds[shot.kind].render(ctx,standardShot,0,shot.end-shot.start);
 const bounds=new THREE.Box3().setFromObject(ctx.model);
 if(bounds.isEmpty())bounds.setFromCenterAndSize(ctx.center,ctx.size);
 for(const g of ctx.groups.values())if(g.visible&&shot.kind!=='weld_macro')bounds.union(new THREE.Box3().setFromObject(g));
 if(shot.kind==='exploded')bounds.expandByScalar(Number(shot.params.spread_m||12)*2);
 if(shot.kind==='motion'){
  const axis=ctx.timeline.model?.rig?.axes?.[shot.params.axis]?.axis;
  if(axis){const amount=Math.abs(Number(shot.params.to_m||0)-Number(shot.params.from_m||0));bounds.min[axis]-=amount;bounds.max[axis]+=amount;}
 }
 const placement=shipyardPlacement(ctx.camera,bounds),buildings=new Map();
 // 整个镜头使用同一组建筑：检查相机路径，禁止视锥边缘逐帧闪现。
 placeShipyard(ctx.yard,placement);
 for(let frame=0;frame<=32;frame++){
  resetScene();
  if(!['real_media','ai_broll'].includes(shot.kind))await kinds[shot.kind].render(ctx,standardShot,(shot.end-shot.start)*frame/32,shot.end-shot.start);
  fitShipyardBuildings(ctx.yard,ctx.camera);
  for(const mesh of ctx.yard.children)if(mesh.userData.building)buildings.set(mesh.name,(buildings.get(mesh.name)??true)&&mesh.visible);
 }
 ctx.plans.set(shot.id,{bounds,placement,buildings});
}
async function drawFrame(t){
 if(!Number.isFinite(Number(t)))throw new Error('播放时间必须为有效数字');t=clamp(Number(t),0,api.duration);currentTime=t;
 const shots=ctx.timeline.shots,shot=shots.find(s=>t>=s.start&&t<s.end)|| (t>=shots.at(-1).end?shots.at(-1):shots[0]),index=shots.indexOf(shot),dur=shot.end-shot.start,localT=clamp(t-shot.start,0,dur);
 resetScene();
 ctx.creative.style.display='none';ctx.mediaLayer.style.display='none';ctx.content.innerHTML='';ctx.labels.innerHTML='';$('numbers').innerHTML='';$('credit').textContent='';$('motion-info').innerHTML='';$('scene').style.visibility='visible';
 $('bg-frame').hidden=true;$('bg-frame').style.filter=shot.kind==='data_card'?'brightness(.78)':'';
 await kinds[shot.kind].render(ctx,shot,localT,dur);
 let hasBackground=Boolean(shot.bg);
 if(hasBackground){
  try{const frame=backgroundFrame(shot.bg,localT);
  await showBackground($('bg-frame'),shot.bg,frame,ctx.resolve,ctx.preloaded);
  $('scene').style.visibility='hidden';
  if(shot.kind==='analogy')analogy.renderBackground(ctx,shot,localT,dimensionPoints(ctx.backgroundAnchors.get(shot.id),frame,shot.bg));
  if(shot.kind==='exploded')exploded.renderBackground(ctx,shot,localT,anchorPoints(ctx.backgroundAnchors.get(shot.id),frame,shot.bg));
  if(shot.kind==='model_orbit')labelNodes(ctx,shot.params.highlight||[],{pointSource:anchorPoints(ctx.backgroundAnchors.get(shot.id),frame,shot.bg)});
  }catch{delete shot.bg;hasBackground=false;$('bg-frame').hidden=true;$('scene').style.visibility='visible';console.warn(`镜头 ${shot.id} 背景不可用，已切换为标准画面`);await prepareShot(shot);resetScene();ctx.labels.innerHTML='';await kinds[shot.kind].render(ctx,shot,localT,dur);}
 }
 if(!hasBackground&&!['real_media','ai_broll'].includes(shot.kind)){
  ctx.preloaded.clear();
  // 结构镜头由自身按时间逐项标注，避免重新叠加整屏引线。
  const plan=ctx.plans.get(shot.id),macro=shot.kind==='weld_macro';
  ctx.yard.visible=ctx.model.visible&&!macro;ctx.foundations.visible=ctx.model.visible&&!macro;
  placeShipyard(ctx.yard,plan.placement);
  for(const mesh of ctx.yard.children)if(mesh.userData.building)mesh.visible=plan.buildings.get(mesh.name)??false;
  placeConcreteGround(ctx.floor,ctx.camera);
  api.metrics={...api.metrics,...ctx.pipeline.render({shot,bounds:plan.bounds,scale:ctx.size.x,macro,moving:['motion','exploded'].includes(shot.kind)})};
 }
 $('vignette').style.display=hasBackground?'':'none';
 const asset=ctx.timeline.assets?.[shot.params?.asset];const badge=shot.bg?`三维模型渲染 · 写实（Blender） · ${ctx.timeline.model?.kind==='step'?'依据STEP':'参数化重建'}`:shot.source==='real'?(asset?.provenance==='reference'?'参考实拍 · 非本机':'实拍'):shot.source==='ai'?'AI 创意画面':shot.source==='model'?`三维模型渲染 · ${ctx.timeline.model?.kind==='step'?'依据STEP':'参数化重建'}`:'信息图';
 $('badge').textContent=badge;$('badge').style.setProperty('--badge-color',({model:'#38d1ff',real:'#3ad07a',ai:'#a77bff',graphic:'#8996a4'})[shot.source]);
 $('caption').textContent=(ctx.timeline.captions||[]).filter(c=>t>=c.start&&t<c.end).map(c=>c.text).join('\n');
 data_card.fitPanel(ctx.content,$('caption'));
 const caption=$('caption');$('credit').style.bottom=`${1080-(caption.textContent?caption.offsetTop:890)+12}px`;
 $('chapter').textContent=`${String(index+1).padStart(2,'0')} / ${String(shots.length).padStart(2,'0')}`;
 $('stage').dataset.shot=shot.kind;
 $('numbers').innerHTML=(['data_card','analogy'].includes(shot.kind)?[]:shot.text_overlays||[]).slice(0,1).map(o=>{const f=ctx.timeline.facts?.[o.fact];return f?`<div class="number-card"><div class="name">${esc(f.name)}</div><strong>${esc(f.value)}</strong><span class="unit">${esc(f.unit)}</span><div class="source">${source(f)}</div></div>`:`<div class="number-card">${esc(o.text)}</div>`;}).join('');
 const fadeIn=index>0?1-clamp(localT/.175):0,fadeOut=index<shots.length-1?1-clamp((dur-localT)/.175):0;$('fade').style.opacity=Math.max(fadeIn,fadeOut);
 $('scrub').value=t;$('time').textContent=`${t.toFixed(1)} / ${api.duration.toFixed(1)} 秒`;$('shot-info').textContent=`${shot.id} · ${shot.kind}`;
 if(preview)await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 if(lastShot!==shot.id){lastShot=shot.id;for(const cb of listeners.get('shot')||[])cb(shot);}
}
function setupPreview(){
 let playing=false,previous=0;const audio=ctx.timeline.audio?new Audio(ctx.resolve(ctx.timeline.audio)):null;
 function pause(){playing=false;audio?.pause();$('play').textContent='播放';}
 async function tick(now){if(!playing)return;const t=audio?audio.currentTime:currentTime+(now-previous)/1000;previous=now;try{await api.seek(t);}catch{pause();return;}if(t>=api.duration){pause();return;}requestAnimationFrame(tick);}
 $('play').onclick=async()=>{if(playing){pause();return;}if(currentTime>=api.duration)await api.seek(0);if(audio){audio.currentTime=currentTime;try{await audio.play();}catch(e){$('error').textContent=`音频播放失败：${e.message}`;$('error').style.display='block';return;}}playing=true;previous=performance.now();$('play').textContent='暂停';requestAnimationFrame(tick);};
 $('scrub').oninput=async e=>{const t=Number(e.target.value);if(audio)audio.currentTime=t;await api.seek(t);previous=performance.now();};audio?.addEventListener('ended',pause);
}
