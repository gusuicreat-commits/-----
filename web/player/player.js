import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { clamp, esc, source, sceneBackground, createBackdrop, createGround, updateGround, fitBackgroundColumns, labelNodes } from './shots/common.js';
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
const api=window.__player={duration:0,ready:null,seek(t){const job=queue.then(()=>api.ready).then(()=>drawFrame(t));queue=job.catch(()=>{});return job;},on(event,cb){if(!listeners.has(event))listeners.set(event,new Set());listeners.get(event).add(cb);return()=>listeners.get(event).delete(cb);}};
function resize(){const availableH=innerHeight-(preview?58:0),scale=Math.min(innerWidth/1920,availableH/1080);$('stage').style.transform=`translate(${(innerWidth-1920*scale)/2}px,${(availableH-1080*scale)/2}px) scale(${scale})`;}
window.addEventListener('resize',resize);$('controls').hidden=!preview;$('controls').style.display=preview?'flex':'none';resize();
function gridTexture(){const c=document.createElement('canvas');c.width=c.height=512;const g=c.getContext('2d');g.fillStyle='#a3adb4';g.fillRect(0,0,512,512);g.strokeStyle='#98a5af';g.lineWidth=2;for(let x=0;x<=512;x+=64){g.beginPath();g.moveTo(x,0);g.lineTo(x,512);g.moveTo(0,x);g.lineTo(512,x);g.stroke();}g.strokeStyle='#b1bdc6';g.lineWidth=3;g.strokeRect(0,0,512,512);const tex=new THREE.CanvasTexture(c);tex.wrapS=tex.wrapT=THREE.RepeatWrapping;tex.repeat.set(24,24);tex.colorSpace=THREE.SRGBColorSpace;return tex;}
async function loadMedia(asset,resolve){
 const el=document.createElement(asset.kind==='video'?'video':'img');el.src=resolve(asset.url);if(asset.kind==='video'){el.muted=true;el.preload='auto';el.playsInline=true;await new Promise((ok,no)=>{el.onloadeddata=ok;el.onerror=()=>no(new Error('视频加载失败'));el.load();});}else await el.decode();return el;
}
api.ready=(async()=>{
 const timelineURL=new URL(query.get('timeline') || '/fixtures/timeline.json',location.href);
 const response=await fetch(timelineURL);if(!response.ok)throw new Error(`时间线加载失败（${response.status}）`);
 const timeline=await response.json();const resolve=url=>new URL(url,timelineURL).href;
 if(!timeline.shots?.length || !Number.isFinite(timeline.duration_s))throw new Error('时间线缺少镜头或有效时长');
 const renderer=new THREE.WebGLRenderer({canvas:$('scene'),antialias:true,preserveDrawingBuffer:true});renderer.setSize(1920,1080);renderer.setPixelRatio(1);renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
 const scene=new THREE.Scene();scene.background=new THREE.Color(sceneBackground);scene.fog=new THREE.Fog(sceneBackground,230,650);
 const camera=new THREE.PerspectiveCamera(40,1920/1080,.01,2500);
 const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();scene.environment=pmrem.fromScene(room,.04).texture;room.dispose();pmrem.dispose();
 const sun=new THREE.DirectionalLight('#fff1dc',3.2);sun.position.set(-70,120,65);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);Object.assign(sun.shadow.camera,{left:-110,right:110,top:110,bottom:-110,near:1,far:350});sun.shadow.bias=-.001;scene.add(sun);scene.add(new THREE.HemisphereLight('#bbdcff','#46505c',2.2));
 const floor=createGround(camera,gridTexture());scene.add(floor);
 const backdrop=createBackdrop();scene.add(backdrop);
 const gltf=timeline.model?.glb?await new GLTFLoader().loadAsync(resolve(timeline.model.glb)):null;const model=gltf?.scene || new THREE.Group();scene.add(model);
 const bounds=new THREE.Box3().setFromObject(model),size=bounds.isEmpty()?new THREE.Vector3(104,51,20):bounds.getSize(new THREE.Vector3()),center=bounds.isEmpty()?new THREE.Vector3(0,25,0):bounds.getCenter(new THREE.Vector3());
 if(timeline.model?.rig?.bbox_m){const b=timeline.model.rig.bbox_m;size.set(b.x,b.y,b.z);center.set(0,b.y/2,0);}
 const originals=[];model.traverse(n=>{originals.push({n,p:n.position.clone(),s:n.scale.clone(),q:n.quaternion.clone(),v:n.visible});if(n.isMesh){n.castShadow=true;n.receiveShadow=true;n.material=Array.isArray(n.material)?n.material.map(m=>m.clone()):n.material.clone();}});
 const materials=[];model.traverse(n=>{if(n.isMesh)for(const m of [].concat(n.material))if(m.emissive)materials.push({m,e:m.emissive.clone(),i:m.emissiveIntensity});});
 const media=new Map();await Promise.all(Object.entries(timeline.assets||{}).map(async([id,a])=>media.set(id,await loadMedia(a,resolve))));
 await document.fonts.load('800 96px "PingFang SC"');await document.fonts.load('44px "Noto Sans SC"');await document.fonts.ready;
 ctx={timeline,renderer,scene,model,floor,backdrop,originals,materials,camera,center,diagonal:size.length(),size,media,content:$('content'),labels:$('labels'),creative:$('creative'),mediaLayer:$('media'),groups:new Map(),resolve};
 for(const shot of timeline.shots){shot.params ||= {};if(!kinds[shot.kind])throw new Error(`不支持的镜头类型：${shot.kind}`);await kinds[shot.kind].setup(ctx,shot);}
 api.duration=timeline.duration_s;$('scrub').max=api.duration;$('film-title').textContent=timeline.title || timeline.shots[0].params?.title || '工程的尺度';
 await drawFrame(0);if(preview)setupPreview();
})().catch(e=>{$('error').style.display='block';$('error').textContent=`播放器加载失败：${e.message}`;throw e;});
async function drawFrame(t){
 if(!Number.isFinite(Number(t)))throw new Error('播放时间必须为有效数字');t=clamp(Number(t),0,api.duration);currentTime=t;
 const shots=ctx.timeline.shots,shot=shots.find(s=>t>=s.start&&t<s.end)|| (t>=shots.at(-1).end?shots.at(-1):shots[0]),index=shots.indexOf(shot),dur=shot.end-shot.start,localT=clamp(t-shot.start,0,dur);
 ctx.originals.forEach(({n,p,s,q,v})=>{n.position.copy(p);n.scale.copy(s);n.quaternion.copy(q);n.visible=v;});ctx.materials.forEach(({m,e,i})=>{m.emissive.copy(e);m.emissiveIntensity=i;});ctx.camera.near=.01;ctx.camera.updateProjectionMatrix();ctx.model.visible=true;ctx.floor.visible=true;ctx.floor.material.map.offset.set(0,0);ctx.scene.background.set(sceneBackground);ctx.renderer.toneMappingExposure=1.15;
 for(const g of ctx.groups.values())g.visible=false;
 ctx.creative.style.display='none';ctx.mediaLayer.style.display='none';ctx.content.innerHTML='';ctx.labels.innerHTML='';$('numbers').innerHTML='';$('credit').textContent='';$('motion-info').innerHTML='';$('scene').style.visibility='visible';
 await kinds[shot.kind].render(ctx,shot,localT,dur);
 if(shot.kind==='model_orbit'){fitBackgroundColumns(ctx);labelNodes(ctx,shot.params.highlight||[]);}
 updateGround(ctx);ctx.renderer.render(ctx.scene,ctx.camera);
 const asset=ctx.timeline.assets?.[shot.params?.asset];const badge=shot.source==='real'?(asset?.provenance==='reference'?'参考实拍 · 非本机':'实拍'):shot.source==='ai'?'AI 创意画面':shot.source==='model'?`三维模型渲染 · ${ctx.timeline.model?.kind==='step'?'依据STEP':'参数化重建'}`:'信息图';
 $('badge').textContent=badge;$('badge').style.setProperty('--badge-color',({model:'#38d1ff',real:'#3ad07a',ai:'#a77bff',graphic:'#8996a4'})[shot.source]);
 $('caption').textContent=(ctx.timeline.captions||[]).filter(c=>t>=c.start&&t<c.end).map(c=>c.text).join('\n');
 const caption=$('caption');$('credit').style.bottom=`${1080-(caption.textContent?caption.offsetTop:890)+12}px`;
 $('chapter').textContent=`${String(index+1).padStart(2,'0')} / ${String(shots.length).padStart(2,'0')}`;
 $('numbers').innerHTML=(['data_card','analogy'].includes(shot.kind)?[]:shot.text_overlays||[]).map(o=>{const f=ctx.timeline.facts?.[o.fact];return f?`<div class="number-card"><div class="name">${esc(f.name)}</div><strong>${esc(f.value)}</strong><span class="unit">${esc(f.unit)}</span><div class="source">${source(f)}</div></div>`:`<div class="number-card">${esc(o.text)}</div>`;}).join('');
 const fadeIn=index>0?1-clamp(localT/.175):0,fadeOut=index<shots.length-1?1-clamp((dur-localT)/.175):0;$('fade').style.opacity=Math.max(fadeIn,fadeOut);
 $('scrub').value=t;$('time').textContent=`${t.toFixed(1)} / ${api.duration.toFixed(1)} 秒`;$('shot-info').textContent=`${shot.id} · ${shot.kind}`;
 await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
 if(lastShot!==shot.id){lastShot=shot.id;for(const cb of listeners.get('shot')||[])cb(shot);}
}
function setupPreview(){
 let playing=false,previous=0;const audio=ctx.timeline.audio?new Audio(ctx.resolve(ctx.timeline.audio)):null;
 function pause(){playing=false;audio?.pause();$('play').textContent='播放';}
 async function tick(now){if(!playing)return;const t=audio?audio.currentTime:currentTime+(now-previous)/1000;previous=now;try{await api.seek(t);}catch{pause();return;}if(t>=api.duration){pause();return;}requestAnimationFrame(tick);}
 $('play').onclick=async()=>{if(playing){pause();return;}if(currentTime>=api.duration)await api.seek(0);if(audio){audio.currentTime=currentTime;try{await audio.play();}catch(e){$('error').textContent=`音频播放失败：${e.message}`;$('error').style.display='block';return;}}playing=true;previous=performance.now();$('play').textContent='暂停';requestAnimationFrame(tick);};
 $('scrub').oninput=async e=>{const t=Number(e.target.value);if(audio)audio.currentTime=t;await api.seek(t);previous=performance.now();};audio?.addEventListener('ended',pause);
}
