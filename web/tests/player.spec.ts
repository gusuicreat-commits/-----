import {test,expect} from '@playwright/test';
import {readFile,mkdir} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
const exec=promisify(execFile);
const fixture=JSON.parse(await readFile(new URL('./fixtures/timeline.json',import.meta.url),'utf8'));
declare global {interface Window {__player:{ready:Promise<void>;duration:number;seek:(t:number)=>Promise<void>;on:(event:string,cb:(shot:any)=>void)=>()=>void}}}
async function ready(page){await page.goto('/player/index.html?timeline=/fixtures/timeline.json&mode=render');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>Promise.race([window.__player.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error('加载超过20秒')),20000))]));}
async function pixels(page,buffer:Buffer){return page.evaluate(async data=>{const img=new Image();img.src='data:image/png;base64,'+data;await img.decode();const c=document.createElement('canvas');c.width=240;c.height=135;const g=c.getContext('2d')!;g.drawImage(img,0,0,240,135);return Array.from(g.getImageData(0,0,240,135).data);},buffer.toString('base64'));}
async function difference(page,a:Buffer,b:Buffer):Promise<number>{return page.evaluate(async([a,b])=>{const images=await Promise.all([a,b].map(async data=>{const img=new Image();img.src='data:image/png;base64,'+data;await img.decode();return img;}));const c=document.createElement('canvas');c.width=1920;c.height=1080;const g=c.getContext('2d')!;g.drawImage(images[0],0,0);const x=g.getImageData(0,0,1920,1080).data;g.clearRect(0,0,1920,1080);g.drawImage(images[1],0,0);const y=g.getImageData(0,0,1920,1080).data;let changed=0;for(let i=0;i<x.length;i+=4)if(Math.abs(x[i]-y[i])>2||Math.abs(x[i+1]-y[i+1])>2||Math.abs(x[i+2]-y[i+2])>2)changed++;return changed/(1920*1080);},[a.toString('base64'),b.toString('base64')]);}
test('所有资源就绪，时长正确',async({page})=>{const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));await ready(page);expect(await page.evaluate(()=>window.__player.duration)).toBe(fixture.duration_s);expect(errors).toEqual([]);});
test('十类镜头完整绘制且不是纯色',async({page})=>{await ready(page);await mkdir('test-results/shots',{recursive:true});for(const shot of fixture.shots){await page.evaluate(t=>window.__player.seek(t),(shot.start+shot.end)/2);const buffer=await page.screenshot({path:`test-results/shots/${shot.kind}.png`});const rgba=await pixels(page,buffer),values=rgba.filter((_,i)=>i%4!==3),mean=values.reduce((a,b)=>a+b,0)/values.length,variance=values.reduce((a,b)=>a+(b-mean)**2,0)/values.length;expect(variance,shot.kind).toBeGreaterThan(180);}});
test('逐镜头重复定位与乱序定位保持像素确定性',async({page})=>{await ready(page);for(const shot of fixture.shots){const t=(shot.start+shot.end)/2;await page.evaluate(t=>window.__player.seek(t),t);const a=await page.screenshot();await page.evaluate(t=>window.__player.seek(t),t);const b=await page.screenshot();expect(await difference(page,a,b),shot.kind).toBeLessThan(.005);await page.evaluate(()=>window.__player.seek(42));await page.evaluate(t=>window.__player.seek(t),t);const c=await page.screenshot();expect(await difference(page,a,c),shot.kind+'乱序').toBeLessThan(.005);}});
test('角标、字幕、出处与镜头事件符合时间线',async({page})=>{await ready(page);await page.evaluate(()=>{(window as any).events=[];window.__player.on('shot',s=>(window as any).events.push(s.id));});await page.evaluate(()=>window.__player.seek(7.5));await expect(page.locator('#badge')).toHaveText('三维模型渲染 · 参数化重建');await expect(page.locator('#caption')).toHaveText(fixture.captions[1].text);await expect(page.locator('#numbers')).toContainText('示例技术参数表.pdf 第2页');await page.evaluate(()=>window.__player.seek(32.5));await expect(page.locator('#badge')).toHaveText('参考实拍 · 非本机');await page.evaluate(()=>window.__player.seek(37.5));await expect(page.locator('#badge')).toHaveText('AI 创意画面');await page.evaluate(()=>window.__player.seek(42.5));await expect(page.locator('#badge')).toHaveText('信息图');expect(await page.evaluate(()=>(window as any).events)).toEqual(['S02','S07','S08','S09']);});
test('渲染器导出60帧视频和指定质检帧',async()=>{test.setTimeout(240000);const out=path.resolve('test-results/render-smoke.mp4');const result=await exec(process.execPath,['render/render.mjs','--url','http://127.0.0.1:8766/player/index.html?timeline=/fixtures/timeline.json','--out',out,'--from','0','--to','2'],{timeout:210000});expect(result.stdout).toContain('"done":true');const probe=await exec(process.env.FFPROBE||'ffprobe',['-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=width,height,nb_read_frames','-of','json',out]);expect(JSON.parse(probe.stdout).streams[0]).toMatchObject({width:1920,height:1080,nb_read_frames:'60'});const frames=await exec(process.execPath,['render/render.mjs','--url','http://127.0.0.1:8766/player/index.html?timeline=/fixtures/timeline.json','--frames-dir',path.resolve('test-results/qa'),'--frames-at','1.5,7.5'],{timeout:90000});expect(frames.stdout).toContain('"done":true');expect((await readFile('test-results/qa/frame-001-1.500.png')).length).toBeGreaterThan(10000);});
test('预览可播放、暂停并拖动时间轴',async({page})=>{await page.goto('/player/index.html?timeline=/fixtures/timeline.json&mode=preview');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);await page.getByRole('button',{name:'播放',exact:true}).click();await expect.poll(async()=>Number(await page.locator('#scrub').inputValue())).toBeGreaterThan(.3);await page.getByRole('button',{name:'暂停',exact:true}).click();await page.locator('#scrub').fill('17.5');await page.locator('#scrub').dispatchEvent('input');await expect(page.locator('#shot-info')).toContainText('S04');await expect(page.locator('#motion-info')).toContainText('×24 倍速');});
test('参照物、运动轴和创意配方分支均可定位',async({page})=>{
 const variants=structuredClone(fixture);variants.shots=[];variants.captions=[];variants.duration_s=60;
 const refs=[['football_field','length',105],['building_floor','height',3],['boeing747','length',64.4],['person','height',1.75],['bus','length',12]];
 for(const [i,[ref,axis,size]] of refs.entries()){const id=`A_${ref}`;variants.analogies[id]={id,ref,axis,ref_size_m:size,ratio:axis==='height'?51/Number(size):104/Number(size),fact:axis==='height'?'F_overall_height':'F_girder_length',text:'真实尺度对照'};variants.shots.push({id,kind:'analogy',source:'model',start:i*5,end:i*5+5,params:{analogy:id}});}
 for(const [i,axis] of ['trolley','hoist','gantry'].entries())variants.shots.push({id:axis,kind:'motion',source:'model',start:25+i*5,end:30+i*5,params:{axis,from_m:axis==='hoist'?5:-20,to_m:axis==='hoist'?40:20,speedup:1}});
 for(const [i,recipe] of ['sunrise_port','night_factory','blueprint_grid','particles'].entries())variants.shots.push({id:recipe,kind:'ai_broll',source:'ai',start:40+i*5,end:45+i*5,params:{recipe,palette:i%2?'cool':'steel'}});
 await page.route('**/variants.json',route=>route.fulfill({json:variants}));await page.goto('/player/index.html?timeline=/fixtures/variants.json&mode=render');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
 await mkdir('test-results/variants',{recursive:true});for(const s of variants.shots){await page.evaluate(t=>window.__player.seek(t),(s.start+s.end)/2);await page.screenshot({path:`test-results/variants/${s.id}.png`});await expect(page.locator('#error')).toBeHidden();}
});
test('视频按时间定位，音频驱动预览时钟',async({page})=>{
 const data=structuredClone(fixture);data.duration_s=2;data.audio='/fixtures/silence.wav';data.assets={V:{url:'/fixtures/clip.mp4',kind:'video',provenance:'own',credit:'本地程序测试素材'}};data.shots=[{id:'V1',kind:'real_media',source:'real',start:0,end:2,params:{asset:'V',effect:'none'}}];data.captions=[];
 await page.route('**/video.json',route=>route.fulfill({json:data}));await page.goto('/player/index.html?timeline=/fixtures/video.json&mode=preview');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);await page.evaluate(()=>window.__player.seek(1.25));expect(await page.locator('video').evaluate((el:HTMLVideoElement)=>el.currentTime)).toBeCloseTo(1.25,2);const a=await page.screenshot();await page.evaluate(()=>window.__player.seek(.25));await page.evaluate(()=>window.__player.seek(1.25));expect((await page.screenshot()).equals(a)).toBeTruthy();await expect(page.locator('#badge')).toHaveText('实拍');await page.evaluate(()=>window.__player.seek(0));await page.getByRole('button',{name:'播放',exact:true}).click();await expect.poll(async()=>Number(await page.locator('#scrub').inputValue())).toBeGreaterThan(.3);await page.getByRole('button',{name:'暂停',exact:true}).click();
});

// 纯几何验证不代替逐帧画面验收。
async function geometryContext(){
 const THREE=await import('three');const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
 const bytes=await readFile(new URL('./fixtures/crane.glb',import.meta.url));
 const gltf=await new GLTFLoader().parseAsync(bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),'');
 const scene=new THREE.Scene();scene.background=new THREE.Color();scene.add(gltf.scene);
 const originals:any[]=[];gltf.scene.traverse(n=>originals.push({n,p:n.position.clone(),s:n.scale.clone(),q:n.quaternion.clone()}));
 return {THREE,timeline:structuredClone(fixture),model:gltf.scene,scene,originals,camera:new THREE.PerspectiveCamera(40,1920/1080,.01,2500),center:new THREE.Vector3(0,25.5,0),size:new THREE.Vector3(104,51,20),diagonal:new THREE.Vector3(104,51,20).length(),content:{innerHTML:''},labels:{innerHTML:''},groups:new Map(),renderer:{toneMappingExposure:1},floor:{visible:true,material:{map:{offset:{y:0}}}}};
}
test('GLB节点层级和104×51×20米外包尺寸符合契约',async()=>{
 const ctx=await geometryContext();for(const name of ['crane','girder','leg_left','leg_right','trolley','hoist_hook','rope','rail_left','rail_right','cab'])expect(ctx.model.getObjectByName(name),name).toBeTruthy();
 for(const name of ['hoist_hook','rope'])expect(ctx.model.getObjectByName(name).parent.name).toBe('trolley');
 expect(ctx.model.getObjectByName('trolley').parent.name).toBe('crane');
 const size=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')).getSize(new ctx.THREE.Vector3());expect(size.x).toBeCloseTo(104);expect(size.y).toBeCloseTo(51);expect(size.z).toBeCloseTo(20);
});
test('参照物实际几何尺寸与输入尺度一致',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 for(const [ref,axis,refSize,dimension,expected] of [['football_field','length',105,'x',105],['building_floor','height',3,'y',51],['boeing747','length',64.4,'x',64.4],['person','height',1.75,'y',1.75],['bus','length',12,'x',12]] as const){
  ctx.timeline.analogies[ref]={ref,axis,ref_size_m:refSize,ratio:axis==='height'?51/refSize:104/refSize};
  module.setup(ctx,{id:ref,params:{analogy:ref}});const size=new ctx.THREE.Box3().setFromObject(ctx.groups.get(ref)).getSize(new ctx.THREE.Vector3());expect(size[dimension],ref).toBeCloseTo(expected,2);
 }
});
test('吊钩离地高度与钢丝绳顶部锚点一致',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/motion.js');
 const saved=(globalThis as any).document;(globalThis as any).document={getElementById:()=>({innerHTML:''})};
 try{for(const y of [2,23,47]){
  for(const o of ctx.originals){o.n.position.copy(o.p);o.n.scale.copy(o.s);}
  module.render(ctx,{params:{axis:'hoist',from_m:y,to_m:y}},2,5);ctx.scene.updateMatrixWorld(true);
  const hook=ctx.model.getObjectByName('hoist_hook').getWorldPosition(new ctx.THREE.Vector3()),rope=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('rope'));
  expect(hook.y).toBeCloseTo(y,5);expect(rope.min.y).toBeCloseTo(y,5);expect(rope.max.y).toBeCloseTo(48,5);
 }}finally{if(saved===undefined)delete (globalThis as any).document;else (globalThis as any).document=saved;}
});

function projectedBounds(ctx,bounds){
 const points=[];for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z])points.push(new ctx.THREE.Vector3(x,y,z).project(ctx.camera));
 return {left:Math.min(...points.map(p=>(p.x+1)/2)),right:Math.max(...points.map(p=>(p.x+1)/2)),top:Math.min(...points.map(p=>(1-p.y)/2)),bottom:Math.max(...points.map(p=>(1-p.y)/2))};
}
test('长度类比左端对齐、本体外留六米且双物体位于安全区',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 const girder=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('girder')),crane=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane'));
 for(const [ref,size] of [['football_field',105],['bus',12],['boeing747',64.4]] as const){
  ctx.timeline.analogies[ref]={ref,axis:'length',ref_size_m:size,ratio:104/size,fact:'F_girder_length',text:'真实尺度对照'};
  const shot={id:ref,params:{analogy:ref}};module.setup(ctx,shot);
  for(const time of [0,1,2.5,4.9]){
   ctx.camera.updateProjectionMatrix();module.render(ctx,shot,time,5);
   const reference=new ctx.THREE.Box3().setFromObject(ctx.groups.get(ref).userData.ref);
   expect(Math.abs(reference.min.x-girder.min.x)).toBeLessThan(.5);
   expect(crane.min.z-reference.max.z).toBeCloseTo(6,5);
   for(const bounds of [crane,reference]){const p=projectedBounds(ctx,bounds);expect(p.left).toBeGreaterThanOrEqual(.08);expect(p.right).toBeLessThanOrEqual(.92);expect(p.top).toBeGreaterThanOrEqual(.08);expect(p.bottom).toBeLessThanOrEqual(.92);}
   const p=projectedBounds(ctx,crane.clone().union(reference));
   expect(p.right-p.left).toBeGreaterThanOrEqual(.6);expect(p.right-p.left).toBeLessThanOrEqual(.75);
   const direction=ctx.camera.getWorldDirection(new ctx.THREE.Vector3());
   const elevation=ctx.THREE.MathUtils.radToDeg(Math.asin(-direction.y));
   expect(elevation).toBeGreaterThanOrEqual(30);expect(elevation).toBeLessThanOrEqual(40);expect(Math.abs(direction.x)).toBeGreaterThan(.1);
   expect(ctx.content.innerHTML).toContain('主梁 104 m');expect(ctx.content.innerHTML).toContain(`参照 ${size} m`);
   expect(ctx.labels.innerHTML).not.toContain('<text');
  }
 }
});
test('高度类比与支腿并排、同地面且标注双高度',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js'),crane=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')),leg=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('leg_right'));
 for(const [ref,size] of [['building_floor',3],['person',1.75]] as const){
  ctx.timeline.analogies[ref]={ref,axis:'height',ref_size_m:size,ratio:51/size,fact:'F_overall_height',text:'真实尺度对照'};
  const shot={id:ref,params:{analogy:ref}};module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
  const reference=new ctx.THREE.Box3().setFromObject(ctx.groups.get(ref).userData.ref);
  expect(reference.min.y).toBeCloseTo(crane.min.y,5);expect(reference.min.x-leg.max.x).toBeCloseTo(6,5);
  expect((ctx.labels.innerHTML.match(/class="dimension"/g)||[]).length).toBe(2);
  const p=projectedBounds(ctx,crane.clone().union(reference));
  expect(p.bottom-p.top).toBeGreaterThanOrEqual(.55);expect(p.bottom-p.top).toBeLessThanOrEqual(.70);
  expect(ctx.content.innerHTML).toContain('整机高度 51 m');
  expect(ctx.content.innerHTML).toContain(ref==='building_floor'?'参照 17 层 × 3 m':'参照 1.75 m');
 }
});
test('开场模型在右下区域并避开文字矩形',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/title.js');
 for(const height of [260,360]){
  (ctx.content as any).querySelector=()=>({offsetLeft:76,offsetWidth:720,offsetTop:140,offsetHeight:height});
  for(const t of [0,2.5,4.9]){module.render(ctx,{params:{}},t,5);const p=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')));expect(p.left*1920).toBeGreaterThan(76+720+20);expect(p.right).toBeLessThanOrEqual(.96);expect(p.bottom).toBeLessThanOrEqual(.87);expect(p.right-p.left).toBeGreaterThanOrEqual(.45);expect(p.right-p.left).toBeLessThanOrEqual(.55);expect((p.top+p.bottom)/2).toBeGreaterThan(.5);expect(ctx.renderer.toneMappingExposure).toBe(1.15);}
 }
});
test('开场双分辨率文字与模型投影不相交',async({page})=>{
 const ctx=await geometryContext(),module=await import('../player/shots/title.js');
 for(const viewport of [{width:1920,height:1080},{width:1366,height:768}]){
  await page.setViewportSize(viewport);await ready(page);await page.evaluate(()=>window.__player.seek(3));
  const layout=await page.locator('.opening').evaluate((el:HTMLElement)=>({top:el.offsetTop,height:el.offsetHeight}));
  (ctx.content as any).querySelector=()=>({offsetTop:layout.top,offsetHeight:layout.height});module.render(ctx,fixture.shots[0],3,5);
  const p=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane'))),stage=await page.locator('#stage').boundingBox(),text=await page.locator('.opening').boundingBox();
  const model={x:stage!.x+p.left*stage!.width,y:stage!.y+p.top*stage!.height,width:(p.right-p.left)*stage!.width,height:(p.bottom-p.top)*stage!.height};
  expect(rectanglesOverlap(model,text!)).toBe(false);
  expect(model.width/stage!.width).toBeGreaterThanOrEqual(.45);expect(model.width/stage!.width).toBeLessThanOrEqual(.55);
  await expect(page.locator('.opening')).toHaveCSS('background-image',/linear-gradient/);
 }
});
test('焊缝等比对照标签位于圆柱下方',async({page})=>{
 const ctx=await geometryContext(),module=await import('../player/shots/weld_macro.js'),shot=fixture.shots.find(s=>s.kind==='weld_macro');
 module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
 const p=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(ctx.groups.get(shot.id).userData.hairs));
 await ready(page);await page.evaluate(()=>window.__player.seek(42.5));
 const stage=await page.locator('#stage').boundingBox(),label=await page.locator('.hair-label').boundingBox();
 expect(label!.y).toBeGreaterThan(stage!.y+p.bottom*stage!.height);
 await expect(page.locator('.hair-label')).toHaveText('头发丝直径 0.07 mm');
});
test('创意粒子画布位于文字层下方',async({page})=>{
 await ready(page);await page.evaluate(()=>window.__player.seek(37.5));
 expect(await page.locator('#creative').evaluate(el=>Number(getComputedStyle(el).zIndex))).toBeLessThan(await page.locator('#content').evaluate(el=>Number(getComputedStyle(el).zIndex)));
});

function rectanglesOverlap(a,b){return a.x<b.x+b.width&&a.x+a.width>b.x&&a.y<b.y+b.height&&a.y+a.height>b.y;}
function projectedMeshArea(ctx,mesh){
 mesh.updateWorldMatrix(true,false);
 const positions=mesh.geometry.attributes.position,index=mesh.geometry.index;
 let area=0;
 for(let i=0;i<(index?.count??positions.count);i+=3){
  const points=[0,1,2].map(j=>new ctx.THREE.Vector3().fromBufferAttribute(positions,index?index.getX(i+j):i+j).applyMatrix4(mesh.matrixWorld).project(ctx.camera));
  const [a,b,c]=points;
  // 只累计朝向相机的三角形，返回占画布面积比例。
  area+=Math.max(0,(b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))/8;
 }
 return area;
}
test('飞机有可见实体投影、翼展沿x且与尺寸端点一致',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 ctx.timeline.analogies.plane={ref:'boeing747',axis:'length',ref_size_m:64.4,ratio:104/64.4,fact:'F_girder_length',text:'真实尺度对照'};
 const shot={id:'plane',params:{analogy:'plane'}};module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
 const ref=ctx.groups.get('plane').userData.ref,areas:number[]=[];
 ref.traverse(n=>{if(n.isMesh)areas.push(projectedMeshArea(ctx,n));});
 expect(Math.max(...areas)).toBeGreaterThan(.005);
 const bounds=new ctx.THREE.Box3().setFromObject(ref),wings=new ctx.THREE.Box3().setFromObject(ref.getObjectByName('wings'));
 expect(wings.min.x).toBeCloseTo(bounds.min.x,5);expect(wings.max.x).toBeCloseTo(bounds.max.x,5);
 expect(wings.max.x-wings.min.x).toBeCloseTo(64.4,3);
 expect(ref.getObjectByName('wings').material.color.getHexString()).toBe('d6dee4');
 expect(ref.getObjectByName('wings').children.some(n=>n.isLineSegments)).toBe(true);
 const path=[...ctx.labels.innerHTML.matchAll(/<path d="M ([\d.-]+) ([\d.-]+) L ([\d.-]+) ([\d.-]+)/g)][1];
 const tips=[-32.2,32.2].map(x=>ref.localToWorld(new ctx.THREE.Vector3(x,6,15)).project(ctx.camera));
 expect(Number(path[1])).toBeCloseTo((tips[0].x+1)*960,4);expect(Number(path[3])).toBeCloseTo((tips[1].x+1)*960,4);
});
test('焊缝头发丝沿z轴躺倒、细长且并排宽度匹配尺寸线',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/weld_macro.js'),shot=fixture.shots.find(s=>s.kind==='weld_macro');
 module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
 const {hairs,width,diameter}=ctx.groups.get(shot.id).userData;
 expect(hairs.children).toHaveLength(7);
 for(const hair of hairs.children){
  const p=hair.geometry.parameters;
  expect(p.height/(p.radiusTop*2)).toBeGreaterThanOrEqual(12);
  const axis=new ctx.THREE.Vector3(0,1,0).applyQuaternion(hair.quaternion);
  expect(Math.abs(axis.z)).toBeCloseTo(1,8);expect(axis.y).toBeCloseTo(0,8);
  expect(hair.material.color.getHexString()).toBe('382319');expect(hair.material.roughness).toBeLessThan(.3);
 }
 const row=new ctx.THREE.Box3().setFromObject(hairs),p=projectedBounds(ctx,row);
 expect(width).toBeCloseTo(.0005,8);expect(diameter).toBeCloseTo(.00007,8);
 expect((p.right-p.left)*1920).toBeCloseTo(440,4);
 const match=ctx.labels.innerHTML.match(/class="hair-dimension" d="M ([\d.]+) ([\d.]+) v 24 M ([\d.]+)/)!;
 expect(Number(match[3])-Number(match[1])).toBeCloseTo(440,4);
 expect(Number(match[2])).toBeGreaterThan(p.bottom*1080);
});
test('类比HTML标签清晰且高度标签在左右两侧不相交',async({page})=>{
 for(const ref of ['building_floor','person','football_field','boeing747','bus']){
  const data=structuredClone(fixture),height=['building_floor','person'].includes(ref),size={building_floor:3,person:1.75,football_field:105,boeing747:64.4,bus:12}[ref];
  data.analogies.A_length={ref,axis:height?'height':'length',ref_size_m:size,ratio:(height?51:104)/size,fact:height?'F_overall_height':'F_girder_length',text:'真实尺度对照'};
  await page.route('**/label-variant.json',route=>route.fulfill({json:data}));
  await page.goto('/player/index.html?timeline=/fixtures/label-variant.json&mode=render');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
  for(const t of [11,12.5,14.8]){
   await page.evaluate(t=>window.__player.seek(t),t);
   const labels=page.locator('.dimension-label');await expect(labels).toHaveCount(2);
   const a=await labels.nth(0).boundingBox(),b=await labels.nth(1).boundingBox();expect(rectanglesOverlap(a,b)).toBe(false);
   const stage=await page.locator('#stage').boundingBox();
   for(const box of [a!,b!]){expect(box.x).toBeGreaterThanOrEqual(stage!.x);expect(box.x+box.width).toBeLessThanOrEqual(stage!.x+stage!.width);}
   for(const label of [labels.nth(0),labels.nth(1)]){
    await expect(label).toHaveCSS('font-size','22px');await expect(label).toHaveCSS('color','rgb(255, 255, 255)');
    await expect(label).toHaveCSS('background-color',/^rgba\(17, 26, 36, 0\.90?2?\)$/);await expect(label).toHaveCSS('border-left-width','4px');
   }
   if(height){
    const left=await page.locator('.dimension-label.left').boundingBox(),right=await page.locator('.dimension-label.right').boundingBox();
    expect(left!.x+left!.width).toBeLessThan(right!.x);
    await expect(page.locator('.dimension-label.left')).toHaveText('整机高度 51 m');
    await expect(page.locator('.dimension-label.right')).toHaveText(ref==='building_floor'?'参照 17 层 × 3 m':'参照 1.75 m');
   }
  }
  await page.unroute('**/label-variant.json');
 }
});
