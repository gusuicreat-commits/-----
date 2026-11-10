import {test,expect} from '@playwright/test';
import {partBounds,fitBackgroundColumns} from '../player/shots/common.js';
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
 for(const [i,[ref,axis,size]] of refs.entries()){const id=`A_${ref}`;variants.analogies[id]={id,ref,axis,ref_size_m:size,ref_size:size,ref_unit:'m',ratio:axis==='height'?51/Number(size):104/Number(size),fact:axis==='height'?'F_overall_height':'F_girder_length',text:'真实尺度对照'};variants.shots.push({id,kind:'analogy',source:'model',start:i*5,end:i*5+5,params:{analogy:id}});}
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
  ctx.timeline.analogies[ref]={ref,axis,ref_size_m:refSize,ref_size:refSize,ref_unit:'m',ratio:axis==='height'?51/refSize:104/refSize};
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
test('长度类比左端对齐、轨道外留六米且双物体位于安全区',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 const girder=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('girder')),crane=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane'));
 const footprint=crane.clone();for(const name of ['rail_left','rail_right'])footprint.union(new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName(name)));
 for(const [ref,size] of [['football_field',105],['bus',12],['boeing747',64.4]] as const){
  ctx.timeline.analogies[ref]={ref,axis:'length',ref_size_m:size,ref_size:size,ref_unit:'m',ratio:104/size,fact:'F_girder_length',text:'真实尺度对照'};
  const shot={id:ref,params:{analogy:ref}};module.setup(ctx,shot);
  for(const time of [0,1,2.5,4.9]){
   ctx.camera.updateProjectionMatrix();module.render(ctx,shot,time,5);
   const reference=new ctx.THREE.Box3().setFromObject(ctx.groups.get(ref).userData.ref);
   expect(Math.abs(reference.min.x-girder.min.x)).toBeLessThan(.5);
   expect(footprint.min.z-reference.max.z).toBeCloseTo(6,5);
   for(const bounds of [crane,reference]){const p=projectedBounds(ctx,bounds);expect(p.left).toBeGreaterThanOrEqual(.08);expect(p.right).toBeLessThanOrEqual(.92);expect(p.top).toBeGreaterThanOrEqual(.08);expect(p.bottom).toBeLessThanOrEqual(.92);}
   const p=projectedBounds(ctx,crane.clone().union(reference));
   expect(p.right-p.left).toBeGreaterThanOrEqual(.45);expect(p.right-p.left).toBeLessThanOrEqual(.75);
   const direction=ctx.camera.getWorldDirection(new ctx.THREE.Vector3());
   const elevation=ctx.THREE.MathUtils.radToDeg(Math.asin(-direction.y));
   expect(elevation).toBeGreaterThanOrEqual(30);expect(elevation).toBeLessThanOrEqual(40);expect(Math.abs(direction.x)).toBeGreaterThan(.1);
   expect(ctx.content.innerHTML).toContain('主梁 104 m');expect(ctx.content.innerHTML).toContain(`参照 ${size} m`);
   expect(ctx.labels.innerHTML).not.toContain('<text');
  }
 }
});
test('高度类比与支腿并排、同地面且标注双高度',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js'),crane=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane'));
 for(const [ref,size] of [['building_floor',3],['person',1.75]] as const){
  ctx.timeline.analogies[ref]={ref,axis:'height',ref_size_m:size,ref_size:size,ref_unit:'m',ratio:51/size,fact:'F_overall_height',text:'真实尺度对照'};
  const shot={id:ref,params:{analogy:ref}};module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
  const reference=new ctx.THREE.Box3().setFromObject(ctx.groups.get(ref).userData.ref);
  expect(reference.min.y).toBeCloseTo(crane.min.y,5);expect(reference.min.x-crane.max.x).toBeCloseTo(6,5);expect(crane.intersectsBox(reference)).toBe(false);
  expect((ctx.labels.innerHTML.match(/class="dimension"/g)||[]).length).toBe(2);
  const p=projectedBounds(ctx,crane.clone().union(reference));
  // 安全区必须为两侧中点标签保留宽度，不再强制占满画面高度。
  expect(p.bottom-p.top).toBeGreaterThanOrEqual(.35);expect(p.bottom-p.top).toBeLessThanOrEqual(.70);
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
function pathSegments(d:string){
 const tokens=d.match(/[MLHVmlhv]|[-+]?(?:\d*\.)?\d+(?:e[-+]?\d+)?/g)||[];
 const result:any[]= [];let p={x:0,y:0};
 while(tokens.length){
  const command=tokens.shift()!,relative=command===command.toLowerCase(),type=command.toUpperCase();
  const q={...p};
  if(type==='M'||type==='L'){q.x=Number(tokens.shift())+(relative?p.x:0);q.y=Number(tokens.shift())+(relative?p.y:0);}
  else if(type==='H')q.x=Number(tokens.shift())+(relative?p.x:0);
  else if(type==='V')q.y=Number(tokens.shift())+(relative?p.y:0);
  else throw new Error('测试遇到未支持的尺寸线命令');
  if(type!=='M')result.push([p,q]);p=q;
 }
 return result;
}
function lineTouchesRect(a,b,r){
 const inside=p=>p.x>=r.x&&p.x<=r.x+r.width&&p.y>=r.y&&p.y<=r.y+r.height;
 if(inside(a)||inside(b))return true;
 for(const x of [r.x,r.x+r.width]){
  const t=(x-a.x)/(b.x-a.x),y=a.y+t*(b.y-a.y);
  if(t>=0&&t<=1&&y>=r.y&&y<=r.y+r.height)return true;
 }
 for(const y of [r.y,r.y+r.height]){
  const t=(y-a.y)/(b.y-a.y),x=a.x+t*(b.x-a.x);
  if(t>=0&&t<=1&&x>=r.x&&x<=r.x+r.width)return true;
 }
 return false;
}
async function assertDimensionClearance(page){
 const paths=await page.locator('#labels .dimension path').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('d')!));
 const stage=(await page.locator('#stage').boundingBox())!,scale=stage.width/1920;
 const segments=paths.flatMap(pathSegments);
 for(const label of await page.locator('.dimension-label').all()){
  const box=(await label.boundingBox())!,rect={x:(box.x-stage.x)/scale,y:(box.y-stage.y)/scale,width:box.width/scale,height:box.height/scale};
  for(const [a,b] of segments)expect(lineTouchesRect(a,b,rect),`标签与尺寸线相交：${await label.textContent()}`).toBe(false);
 }
 return paths.map(d=>pathSegments(d)[0]);
}
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
 ctx.timeline.analogies.plane={ref:'boeing747',axis:'length',ref_size_m:64.4,ref_size:64.4,ref_unit:'m',ratio:104/64.4,fact:'F_girder_length',text:'真实尺度对照'};
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
  data.analogies.A_length={ref,axis:height?'height':'length',ref_size_m:size,ref_size:size,ref_unit:'m',ratio:(height?51:104)/size,fact:height?'F_overall_height':'F_girder_length',text:'真实尺度对照'};
  await page.route('**/label-variant.json',route=>route.fulfill({json:data}));
  await page.goto('/player/index.html?timeline=/fixtures/label-variant.json&mode=render');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
  for(const t of [11,12.5,14.8]){
   await page.evaluate(t=>window.__player.seek(t),t);
   const lines=await assertDimensionClearance(page);
   if(height)expect(Math.abs(lines[0][0].y-lines[1][0].y)).toBeLessThan(4);
   await expect(page.locator('#numbers .number-card')).toHaveCount(0);
   const labels=page.locator('.dimension-label');await expect(labels).toHaveCount(2);
   const a=await labels.nth(0).boundingBox(),b=await labels.nth(1).boundingBox();expect(rectanglesOverlap(a,b)).toBe(false);
   const stage=await page.locator('#stage').boundingBox();
   for(const box of [a!,b!]){expect(box.x).toBeGreaterThanOrEqual(stage!.x);expect(box.x+box.width).toBeLessThanOrEqual(stage!.x+stage!.width);}
   for(const label of [labels.nth(0),labels.nth(1)]){
    await expect(label).toHaveCSS('font-size','22px');await expect(label).toHaveCSS('color','rgb(255, 255, 255)');
    await expect(label).toHaveCSS('background-color','rgb(17, 26, 36)');await expect(label).toHaveCSS('border-left-width','4px');
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

test('类比尺寸新单位与旧数据默认值一致',async()=>{
 const {referenceSize}=await import('../player/shots/analogy.js');
 expect(referenceSize({ref:'hair',ref_size:.07,ref_unit:'mm',ref_size_m:.00007})).toEqual({size:.07,unit:'mm',meters:.00007});
 expect(referenceSize({ref:'hair',ref_size_m:.07})).toEqual({size:.07,unit:'mm',meters:.00007});
 expect(referenceSize({ref:'building_floor',ref_size_m:3})).toEqual({size:3,unit:'m',meters:3});
 expect(referenceSize({ref:'building_floor',ref_size:3.5,ref_unit:'m',ref_size_m:3.5})).toEqual({size:3.5,unit:'m',meters:3.5});
});
test('楼房窗片与墙面分离且残余楼层窗片不相互交叠',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 for(const ratio of [17,17.1]){
  const id=`building-${ratio}`;ctx.timeline.analogies[id]={ref:'building_floor',axis:'height',ratio,ref_size:3,ref_unit:'m',ref_size_m:3};
  module.setup(ctx,{id,params:{analogy:id}});
  const ref=ctx.groups.get(id).userData.ref,wall=new ctx.THREE.Box3().setFromObject(ref.getObjectByName('building-wall'));
  const windows=ref.children.filter(n=>n.name==='building-window').map(n=>new ctx.THREE.Box3().setFromObject(n));
  expect(windows).toHaveLength(Math.ceil(ratio)*4);
  for(const window of windows){expect(window.min.z-wall.max.z).toBeGreaterThan(.05);expect(window.min.y).toBeGreaterThan(wall.min.y);expect(window.max.y).toBeLessThan(wall.max.y);}
  for(let i=0;i<windows.length;i++)for(let j=i+1;j<windows.length;j++)expect(windows[i].intersectsBox(windows[j])).toBe(false);
 }
});
test('飞机在轨道外侧落地且机身沿z轴无交叉',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 const a={ref:'boeing747',axis:'length',ref_size:64.4,ref_unit:'m',ref_size_m:64.4,ratio:104/64.4};
 ctx.timeline.analogies.plane=a;module.setup(ctx,{id:'plane',params:{analogy:'plane'}});
 const ref=ctx.groups.get('plane').userData.ref,bounds=new ctx.THREE.Box3().setFromObject(ref);
 const crane=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')),girder=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('girder'));
 expect(bounds.min.x).toBeCloseTo(girder.min.x,5);expect(bounds.min.y).toBeCloseTo(crane.min.y,5);expect(bounds.max.z).toBeLessThan(crane.min.z);
 for(const name of ['rail_left','rail_right'])expect(bounds.intersectsBox(new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName(name)))).toBe(false);
 const axis=new ctx.THREE.Vector3(0,1,0).applyQuaternion(ref.getObjectByName('fuselage').quaternion);
 expect(Math.abs(axis.z)).toBeCloseTo(1,8);
 for(const wheel of ref.children.filter(n=>n.name==='landing-wheel'))expect(new ctx.THREE.Box3().setFromObject(wheel).min.y).toBeCloseTo(crane.min.y,5);
});
test('钢板错边等于参数且尺寸线端点对应表面高度差',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/weld_macro.js'),shot=fixture.shots.find(s=>s.kind==='weld_macro');
 for(const millimeters of [.5,.2]){
  ctx.timeline.facts[shot.params.fact].value=millimeters;
  module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
  const {left,right,seam,weld,width}=ctx.groups.get(shot.id).userData;
  const l=new ctx.THREE.Box3().setFromObject(left),r=new ctx.THREE.Box3().setFromObject(right),s=new ctx.THREE.Box3().setFromObject(seam);
  expect(r.max.y-l.max.y).toBeCloseTo(millimeters/1000,8);expect(width).toBeCloseTo(millimeters/1000,8);
  expect(s.min.x).toBeCloseTo(l.max.x,8);expect(s.max.x).toBeCloseTo(r.min.x,8);
  const path=ctx.labels.innerHTML.match(/class="weld-step-dimension"><path d="M ([\d.-]+) ([\d.-]+) H [\d.-]+ M ([\d.-]+) ([\d.-]+)/)!;
  const points=[new ctx.THREE.Vector3(l.max.x,l.max.y,l.max.z),new ctx.THREE.Vector3(r.min.x,r.max.y,r.max.z)].map(p=>p.project(ctx.camera));
  expect(Number(path[2])).toBeCloseTo((1-points[0].y)*540,5);expect(Number(path[4])).toBeCloseTo((1-points[1].y)*540,5);
  const p=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(weld));expect(p.top*1080).toBeGreaterThan(440);expect(p.bottom*1080).toBeLessThan(860);
  expect(ctx.content.innerHTML).toContain('示意放大');
 }
});
test('旧头发丝字段不再生成巨型圆柱',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/weld_macro.js'),shot=fixture.shots.find(s=>s.kind==='weld_macro');
 const a=ctx.timeline.analogies[shot.params.analogy];delete a.ref_size;delete a.ref_unit;a.ref_size_m=.07;
 module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
 expect(ctx.groups.get(shot.id).userData.diameter).toBeCloseTo(.00007,8);
 expect(ctx.groups.get(shot.id).userData.hairs.children).toHaveLength(7);
 expect(ctx.labels.innerHTML).toContain('头发丝直径 0.07 mm');
});
test('焊缝文字参数卡与模型及尺寸标签在双分辨率下互不重叠',async({page})=>{
 const ctx=await geometryContext(),module=await import('../player/shots/weld_macro.js'),shot=fixture.shots.find(s=>s.kind==='weld_macro');module.setup(ctx,shot);
 for(const viewport of [{width:1920,height:1080},{width:1366,height:768}]){
  await page.setViewportSize(viewport);await ready(page);
  for(const t of [41,42.5,44.8]){
   await page.evaluate(t=>window.__player.seek(t),t);
   const copy=await page.locator('.weld-copy').evaluate((el:HTMLElement)=>({offsetTop:el.offsetTop,offsetHeight:el.offsetHeight}));
   (ctx.content as any).querySelector=()=>copy;module.render(ctx,shot,t-40,5);
   const stage=(await page.locator('#stage').boundingBox())!,text=(await page.locator('.weld-copy').boundingBox())!;
   for(const group of [ctx.groups.get(shot.id).userData.weld,ctx.groups.get(shot.id).userData.hairs]){
    const p=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(group));
    expect(rectanglesOverlap(text,{x:stage.x+p.left*stage.width,y:stage.y+p.top*stage.height,width:(p.right-p.left)*stage.width,height:(p.bottom-p.top)*stage.height})).toBe(false);
   }
   const card=await page.locator('#numbers').boundingBox();
   await expect(page.locator('#labels .label-background')).toHaveCount(4);
   const hairScale=(await page.locator('.hair-scale-label').boundingBox())!,hairLabel=(await page.locator('.hair-label').boundingBox())!,scale=stage.width/1920;
   expect((hairLabel.y-hairScale.y-hairScale.height)/scale).toBeGreaterThanOrEqual(10);
   const scaleBacking=(await page.locator('.hair-scale-label').evaluate(el=>el.previousElementSibling!.getBoundingClientRect().toJSON())),hairBacking=(await page.locator('.hair-label').evaluate(el=>el.previousElementSibling!.getBoundingClientRect().toJSON()));
   expect((hairBacking.y-scaleBacking.y-scaleBacking.height)/scale).toBeGreaterThanOrEqual(10);
   for(const text of await page.locator('#labels text').all())await expect(text).toHaveCSS('fill','rgb(255, 255, 255)');
   for(const label of await page.locator('#labels .label-background').all()){
    await expect(label).toHaveCSS('fill','rgb(17, 26, 36)');
    const rect=(await label.boundingBox())!;expect(rectanglesOverlap(card!,rect)).toBe(false);expect(rectanglesOverlap(text,rect)).toBe(false);
    expect(rect.y+rect.height).toBeLessThan(stage.y+stage.height*.82);
   }
  }
 }
});

test('实拍标题去前缀不折词且署名紧邻字幕上方',async({page})=>{
 for(const viewport of [{width:1920,height:1080},{width:1366,height:768}]){
  await page.setViewportSize(viewport);
  for(const caption of [fixture.shots.find(s=>s.kind==='real_media').params.caption,'',`参考实拍 · 非本机：${'造船厂门式起重机，'.repeat(12)}`]){
   const data=structuredClone(fixture);data.shots.find(s=>s.kind==='real_media').params.caption=caption;
   await page.route('**/media-layout.json',route=>route.fulfill({json:data}));
   await page.goto('/player/index.html?timeline=/fixtures/media-layout.json&mode=render');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
   for(const t of [30,32.5,34.9]){
    await page.evaluate(t=>window.__player.seek(t),t);
    const title=page.locator('.media-copy');await expect(title).not.toContainText('参考实拍');await expect(title).not.toContainText('非本机');
    const metrics=await title.evaluate((el:HTMLElement)=>({width:el.clientWidth,scroll:el.scrollWidth,height:el.clientHeight,line:parseFloat(getComputedStyle(el).lineHeight),size:parseFloat(getComputedStyle(el).fontSize)}));
    expect(metrics.width).toBeLessThanOrEqual(1720);expect(metrics.scroll).toBeLessThanOrEqual(metrics.width);expect(metrics.height-32).toBeLessThanOrEqual(metrics.line+1);
    const textWidth=await title.evaluate(el=>{const range=document.createRange();range.selectNodeContents(el);return range.getBoundingClientRect().width/(document.getElementById('stage')!.getBoundingClientRect().width/1920);});
    expect(metrics.width).toBeLessThanOrEqual(textWidth+40);
    expect(metrics.width).toBeGreaterThanOrEqual(textWidth+31);
    await expect(title).toHaveCSS('padding-left','16px');await expect(title).toHaveCSS('padding-right','16px');
    if(caption.length>100)expect(metrics.size).toBeLessThan(44);
    else await expect(title).toHaveText('造船厂门式起重机');
    await expect(title).toHaveCSS('word-break','keep-all');await expect(title).toHaveCSS('line-break','strict');await expect(title).toHaveCSS('background-image',/linear-gradient/);
    const stage=(await page.locator('#stage').boundingBox())!,credit=(await page.locator('#credit').boundingBox())!,scale=stage.width/1920;
    expect(credit.width).toBeLessThanOrEqual(stage.width*.6+.1);await expect(page.locator('#credit')).toHaveCSS('font-size','14px');await expect(page.locator('#credit')).toHaveCSS('text-overflow','clip');
    await expect(page.locator('#credit')).toHaveText('图：Hannah Forey / CC BY-SA 4.0\ncommons.wikimedia.org');
    const creditMetrics=await page.locator('#credit').evaluate((el:HTMLElement)=>({height:el.clientHeight,scroll:el.scrollHeight,width:el.clientWidth,scrollWidth:el.scrollWidth}));
    expect(creditMetrics.height).toBeLessThanOrEqual(52);expect(creditMetrics.scroll).toBe(creditMetrics.height);expect(creditMetrics.scrollWidth).toBeLessThanOrEqual(creditMetrics.width);
    if(t===32.5){const subtitle=(await page.locator('#caption').boundingBox())!;expect(Math.abs((subtitle.y-credit.y-credit.height)/scale-12)).toBeLessThan(1);}
    const transform=await page.locator('#media img').evaluate(el=>{const m=new DOMMatrix(getComputedStyle(el).transform);return {scale:m.a,x:m.e,y:m.f};});
    expect(transform.scale).toBeCloseTo(1+.08*(t-30)/5,5);expect(transform.x).toBe(0);expect(transform.y).toBe(0);
   }
   await page.unroute('**/media-layout.json');
  }
 }
});
test('参数面板与类比镜头不再重复显示数字卡且切镜恢复',async({page})=>{
 await ready(page);
 for(const t of [27.5,12.5,27.5]){await page.evaluate(t=>window.__player.seek(t),t);await expect(page.locator('#numbers .number-card')).toHaveCount(0);}
 await expect(page.locator('.data-panel .data-card')).toHaveCount(3);
 await page.evaluate(()=>window.__player.seek(7.5));await expect(page.locator('#numbers .number-card')).toHaveCount(1);
});
test('类比尺寸新排版的所有线段与标签、小车投影分离',async()=>{
 const module=await import('../player/shots/analogy.js');
 for(const ref of ['football_field','boeing747','bus','building_floor','person']){
  const ctx=await geometryContext(),height=['building_floor','person'].includes(ref),size={football_field:105,boeing747:64.4,bus:12,building_floor:3,person:1.75}[ref]!;
  ctx.timeline.analogies.variant={ref,axis:height?'height':'length',ref_size:size,ref_unit:'m',ref_size_m:size,ratio:(height?51:104)/size,fact:height?'F_overall_height':'F_girder_length',text:'真实尺度对照'};
  const shot={id:'variant',params:{analogy:'variant'}};module.setup(ctx,shot);
  for(const width of [220,340]){
   const nodes=[0,1].map(()=>({offsetWidth:width,offsetHeight:36,style:{}}));
   (ctx.content as any).querySelectorAll=()=>nodes;module.render(ctx,shot,2.5,5);
   const paths=[...ctx.labels.innerHTML.matchAll(/<path d="([^"]+)"/g)].map(m=>pathSegments(m[1]));
   const trolley=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('trolley')));
   const obstacle={x:trolley.left*1920,y:trolley.top*1080,width:(trolley.right-trolley.left)*1920,height:(trolley.bottom-trolley.top)*1080};
   const rects=nodes.map(n=>({x:parseFloat((n.style as any).left),y:parseFloat((n.style as any).top),width:n.offsetWidth,height:n.offsetHeight}));
   for(const rect of rects){
    expect(rect.y).toBeGreaterThan(80);expect(rect.y+rect.height).toBeLessThan(900);
    expect(rectanglesOverlap(rect,obstacle)).toBe(false);
    for(const [a,b] of paths.flat())expect(lineTouchesRect(a,b,rect)).toBe(false);
   }
   expect(rectanglesOverlap(rects[0],rects[1])).toBe(false);
   if(height)expect(Math.abs(paths[0][0][0].y-paths[1][0][0].y)).toBeLessThan(4);
  }
 }
});
test('高度类比与零地面对齐且顶端包含小车外包',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/analogy.js');
 // 模型底部偏离原点时，尺寸线仍必须从契约地面 y=0 起算。
 ctx.model.getObjectByName('crane').position.y=2;
 ctx.model.getObjectByName('trolley').position.y+=5;
 ctx.timeline.analogies.height={ref:'building_floor',axis:'height',ref_size:3,ref_unit:'m',ref_size_m:3,ratio:17,fact:'F_overall_height',text:'真实尺度对照'};
 const shot={id:'height',params:{analogy:'height'}};module.setup(ctx,shot);module.render(ctx,shot,2.5,5);
 const crane=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')),ref=new ctx.THREE.Box3().setFromObject(ctx.groups.get('height').userData.ref);
 expect(ref.min.y).toBeCloseTo(0,7);expect(crane.min.y).toBeCloseTo(2,7);
 const lines=[...ctx.labels.innerHTML.matchAll(/<path d="([^"]+)"/g)].map(m=>pathSegments(m[1])[0]);
 const z=Math.max(crane.max.z,ref.max.z),ys=[0,crane.max.y,ref.max.y].map(y=>(1-new ctx.THREE.Vector3(0,y,z).project(ctx.camera).y)*540);
 expect(lines[0][0].y).toBeCloseTo(ys[0],5);expect(lines[1][0].y).toBeCloseTo(ys[0],5);
 expect(lines[0][1].y).toBeCloseTo(ys[1],5);expect(lines[1][1].y).toBeCloseTo(ys[2],5);
 for(const [i,bounds] of [crane,ref].entries()){
  const p=projectedBounds(ctx,bounds);
  expect(Math.abs(lines[i][1].y-p.top*1080)).toBeLessThan(6);
  const ground=bounds.clone();ground.min.y=0;
  expect(Math.abs(lines[i][0].y-projectedBounds(ctx,ground).bottom*1080)).toBeLessThan(6);
 }
 expect(ref.min.x-crane.max.x).toBeGreaterThanOrEqual(6-1e-8);expect(crane.intersectsBox(ref)).toBe(false);
});
function segmentsIntersect(a,b,c,d){
 const cross=(p,q,r)=>(q.x-p.x)*(r.y-p.y)-(q.y-p.y)*(r.x-p.x);
 const inside=(p,q,r)=>Math.min(p.x,q.x)-1e-7<=r.x&&r.x<=Math.max(p.x,q.x)+1e-7&&Math.min(p.y,q.y)-1e-7<=r.y&&r.y<=Math.max(p.y,q.y)+1e-7;
 const values=[cross(a,b,c),cross(a,b,d),cross(c,d,a),cross(c,d,b)];
 if(values[0]*values[1]<0&&values[2]*values[3]<0)return true;
 return [[a,b,c,values[0]],[a,b,d,values[1]],[c,d,a,values[2]],[c,d,b,values[3]]].some(([p,q,r,v])=>Math.abs(v as number)<1e-7&&inside(p,q,r));
}
function explodedLabels(svg){
 return [...svg.matchAll(/data-part="([^"]+)" data-side="([^"]+)"><path d="([^"]+)"[\s\S]*?<circle cx="([^"]+)" cy="([^"]+)"[\s\S]*?<rect x="([^"]+)" y="([^"]+)"/g)].map(m=>({id:m[1],side:m[2],segments:pathSegments(m[3]),x:Number(m[4]),y:Number(m[5]),labelX:Number(m[6]),labelY:Number(m[7])}));
}
function assertLeadersSeparate(labels){
 for(let i=0;i<labels.length;i++)for(let j=i+1;j<labels.length;j++){
  for(const [a,b] of labels[i].segments)for(const [c,d] of labels[j].segments){
   expect(segmentsIntersect(a,b,c,d),`${labels[i].id} 与 ${labels[j].id} 引线交叉`).toBe(false);
  }
 }
}
test('GLB节点爆炸引线按世界左右及投影高度分槽且任意线段不交叉',async()=>{
 const ctx=await geometryContext(),module=await import('../player/shots/exploded.js');
 const shot=fixture.shots.find(s=>s.kind==='exploded');
 for(const t of [0,.1,.5,1,2.5,4.5,4.9,5]){
  for(const o of ctx.originals)o.n.position.copy(o.p);
  ctx.camera.updateProjectionMatrix();module.render(ctx,shot,t,5);
  const labels=explodedLabels(ctx.labels.innerHTML),center=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('crane')).getCenter(new ctx.THREE.Vector3());
  expect(labels).toHaveLength(5);expect(labels.map(v=>v.id)).toContain('cab');expect(ctx.labels.innerHTML).toContain('司机室');
  for(const v of labels){
   const node=ctx.model.getObjectByName(v.id),anchor=partBounds(node).getCenter(new ctx.THREE.Vector3()),left=anchor.x<center.x;
   anchor.project(ctx.camera);
   expect(v.x).toBeCloseTo((anchor.x+1)*960,5);expect(v.y).toBeCloseTo((1-anchor.y)*540,5);
   expect(v.side).toBe(left?'left':'right');expect(v.labelX).toBe(left?95:1590);
   expect(v.segments).toHaveLength(2);expect(v.segments[0][1].y).toBeCloseTo(v.y,5);
   expect(v.labelY).toBeGreaterThan(v.side==='left'?240:124);expect(v.labelY+50).toBeLessThan(800);
  }
  for(const side of ['left','right']){
   const column=labels.filter(v=>v.side===side);
   for(let i=1;i<column.length;i++){expect(column[i].y).toBeGreaterThanOrEqual(column[i-1].y);expect(column[i].labelY-column[i-1].labelY).toBeGreaterThanOrEqual(70-1e-6);}
  }
  assertLeadersSeparate(labels);
 }
});
test('GLB节点司机室随刚性腿移动且兼容父子层级和显式拆分列表',async()=>{
 const module=await import('../player/shots/exploded.js');
 for(const attached of [false,true])for(const explicit of [false,true]){
  const ctx=await geometryContext(),cab=ctx.model.getObjectByName('cab'),leg=ctx.model.getObjectByName('leg_left');
  if(attached)leg.attach(cab);
  const origins=[];ctx.model.traverse(n=>origins.push({n,p:n.position.clone()}));
  const relative=cab.getWorldPosition(new ctx.THREE.Vector3()).sub(leg.getWorldPosition(new ctx.THREE.Vector3()));
  const shot=structuredClone(fixture.shots.find(s=>s.kind==='exploded'));if(explicit)shot.params.parts.push('cab');
  for(const t of [2.5,0,4.8,1,5]){
   for(const o of origins)o.n.position.copy(o.p);
   module.render(ctx,shot,t,5);
   const actual=cab.getWorldPosition(new ctx.THREE.Vector3()).sub(leg.getWorldPosition(new ctx.THREE.Vector3()));
   expect(actual.distanceTo(relative)).toBeLessThan(1e-8);
   if(t===2.5)expect(leg.position.x).toBeLessThan(origins.find(o=>o.n===leg).p.x);
   expect(explodedLabels(ctx.labels.innerHTML).filter(v=>v.id==='cab')).toHaveLength(1);
  }
 }
});
test('GLB节点引线绕开其他部件矩形且避线算法处理斜线',async()=>{
 const {routeLeader,segmentIntersectsRect}=await import('../player/shots/layout.js');
 const obstacle={x:300,y:200,width:200,height:200},start={x:100,y:300},end={x:800,y:300};
 const route=routeLeader(start,end,[obstacle]);expect(route.length).toBeGreaterThan(2);expect(route[0]).toEqual(start);expect(route.at(-1)).toEqual(end);
 for(let i=1;i<route.length;i++)expect(lineTouchesRect(route[i-1],route[i],obstacle)).toBe(false);
 expect(segmentIntersectsRect({x:0,y:0},{x:600,y:600},obstacle)).toBe(true);
 expect(segmentIntersectsRect({x:0,y:0},{x:200,y:600},obstacle)).toBe(false);
});

test('实拍署名保留作者许可且来源链接只展示域名',async()=>{
 const {mediaCredit}=await import('../player/shots/real_media.js');
 expect(mediaCredit(fixture.assets.IMG_01.credit)).toBe('图：Hannah Forey / CC BY-SA 4.0\ncommons.wikimedia.org');
 expect(mediaCredit(fixture.assets.IMG_02.credit)).toBe('图：Federal Highway Administration / Public domain\ncommons.wikimedia.org');
 expect(mediaCredit('本设备实拍')).toBe('图：本设备实拍');expect(mediaCredit('')).toBe('');
});

test('所有镜头眉题有深色底片且切镜保持一致',async({page})=>{
 await ready(page);
 for(const shot of fixture.shots){
  await page.evaluate(t=>window.__player.seek(t),(shot.start+shot.end)/2);
  for(const eyebrow of await page.locator('.eyebrow,.section-title small').all()){
   await expect(eyebrow).toHaveCSS('background-color','rgba(17, 26, 36, 0.8)');
   await expect(eyebrow).toHaveCSS('border-radius','6px');await expect(eyebrow).toHaveCSS('padding','4px 10px');
  }
 }
});

test('爆炸镜头实际标签无引线交叉且避开标题字幕',async({page})=>{
 const ctx=await geometryContext(),module=await import('../player/shots/exploded.js'),{projectBounds}=await import('../player/shots/common.js');
 const shot=fixture.shots.find(s=>s.kind==='exploded');
 for(const viewport of [{width:1920,height:1080},{width:1366,height:768}]){
  await page.setViewportSize(viewport);await ready(page);
  for(const t of [20.1,21,22.5,24.9,21]){
   await page.evaluate(t=>window.__player.seek(t),t);
   const labels=explodedLabels(await page.locator('#labels').innerHTML());
   expect(labels).toHaveLength(5);assertLeadersSeparate(labels);
   await expect(page.locator('#labels [data-part="cab"] text')).toHaveText('司机室');
   const stage=(await page.locator('#stage').boundingBox())!,scale=stage.width/1920,measured={};
   for(const selector of ['#badge','.section-title','#film-title','#caption','footer']){
    const r=await page.locator(selector).boundingBox();if(r)measured[selector]={x:(r.x-stage.x)/scale,y:(r.y-stage.y)/scale,width:r.width/scale,height:r.height/scale};
   }
   mockHud(ctx,measured);for(const o of ctx.originals)o.n.position.copy(o.p);module.render(ctx,shot,t-shot.start,shot.end-shot.start);
   if(t===22.5){const rect=visibleModelRect(ctx);expect(rect.width/1920).toBeGreaterThanOrEqual(.6);expect(rect.width/1920).toBeLessThanOrEqual(.7);}
   const tb=partBounds(ctx.model.getObjectByName('trolley')),gb=partBounds(ctx.model.getObjectByName('girder'));
   const tr=projectBounds(ctx,tb),gr=projectBounds(ctx,gb),anchor=tb.getCenter(new ctx.THREE.Vector3()).project(ctx.camera);
   const trolley=labels.find(v=>v.id==='trolley')!,girder=labels.find(v=>v.id==='girder')!;
   expect(trolley.x).toBeCloseTo((anchor.x+1)*960,4);expect(trolley.y).toBeCloseTo((1-anchor.y)*540,4);
   expectInside({x:trolley.x,y:trolley.y,width:0,height:0},tr);
   expect(rectanglesOverlap(tr,gr)).toBe(false);expect(lineTouchesRect(trolley,trolley,gr)).toBe(false);
   expect(Math.hypot(trolley.x-girder.x,trolley.y-girder.y)).toBeGreaterThanOrEqual(24);
   const title=(await page.locator('.section-title').boundingBox())!,badge=(await page.locator('#badge').boundingBox())!,caption=await page.locator('#caption').boundingBox();
   const rects=[];
   for(const label of await page.locator('#labels [data-part] rect').all()){
    const rect=(await label.boundingBox())!;
    for(const obstacle of [title,badge,caption,...rects].filter(Boolean))expect(rectanglesOverlap(rect,obstacle)).toBe(false);
    rects.push(rect);
   }
  }
 }
});

function mockHud(ctx,rects,scale=1){
 const origin={x:13,y:9,width:1920*scale,height:1080*scale};
 const nodes=Object.fromEntries(Object.entries(rects).map(([selector,r]:[string,any])=>[selector,{textContent:'',getBoundingClientRect:()=>({x:origin.x+r.x*scale,y:origin.y+r.y*scale,width:r.width*scale,height:r.height*scale})}]));
 (ctx.content as any).ownerDocument={getElementById:id=>id==='stage'?{getBoundingClientRect:()=>origin,querySelector:selector=>nodes[selector]}:nodes[`#${id}`]};
 return nodes;
}
const hudRects={
 '#badge':{x:64,y:50,width:470,height:60},'.section-title':{x:76,y:124,width:400,height:92},
 '#film-title':{x:1450,y:65,width:400,height:40},'#caption':{x:170,y:826,width:1580,height:158},
 'footer':{x:64,y:1005,width:1792,height:45},'.analogy-copy':{x:80,y:850,width:800,height:70},
};
function expectInside(rect,safe){
 expect(rect.x).toBeGreaterThanOrEqual(safe.x-1e-5);expect(rect.y).toBeGreaterThanOrEqual(safe.y-1e-5);
 expect(rect.x+rect.width).toBeLessThanOrEqual(safe.x+safe.width+1e-5);expect(rect.y+rect.height).toBeLessThanOrEqual(safe.y+safe.height+1e-5);
}
test('安全区按实际HUD矩形换算画布坐标并同步当前字幕',async()=>{
 const {hudSafeArea}=await import('../player/shots/layout.js');
 for(const scale of [1,1366/1920,.5]){
  const ctx=await geometryContext(),nodes=mockHud(ctx,hudRects,scale);
  ctx.timeline.captions=[{start:11,end:13,text:'两行字幕\n第二行'}];
  const safe=hudSafeArea(ctx,{start:10},2);
  expect(safe).toMatchObject({x:40,y:232,width:1840,height:578});
  expect(nodes['#caption'].textContent).toBe('两行字幕\n第二行');
  expect(nodes['#badge'].textContent).toBe('三维模型渲染 · 参数化重建');
  hudSafeArea(ctx,{start:10},0);expect(nodes['#caption'].textContent).toBe('');
 }
});
test('S2高度尺寸线和中点标签及整体投影均在HUD安全区',async()=>{
 const module=await import('../player/shots/analogy.js'),{hudSafeArea}=await import('../player/shots/layout.js');
 for(const width of [220,340,480])for(const titleHeight of [65,130]){
  const ctx=await geometryContext();mockHud(ctx,{...hudRects,'.section-title':{...hudRects['.section-title'],height:titleHeight}},1366/1920);
  ctx.timeline.analogies.height={ref:'building_floor',axis:'height',ref_size_m:3,ratio:17,fact:'F_overall_height',text:'相当于17层楼的高度'};
  const shot={id:'height',start:10,params:{analogy:'height'}};module.setup(ctx,shot);
  const nodes=[0,1].map(()=>({offsetWidth:width,offsetHeight:36,style:{}}));(ctx.content as any).querySelectorAll=()=>nodes;
  let snapshot='';
  for(const t of [2.5,0,4.9,2.5]){
   module.render(ctx,shot,t,5);const safe=hudSafeArea(ctx,shot,t);
   const paths=[...ctx.labels.innerHTML.matchAll(/<path d="([^"]+)"/g)].map(m=>pathSegments(m[1]));
   for(const [i,node] of nodes.entries()){
    const rect={x:parseFloat((node.style as any).left),y:parseFloat((node.style as any).top),width,height:36};expectInside(rect,safe);
    const [a,b]=paths[i][0];expect(rect.y+18).toBeCloseTo((a.y+b.y)/2,5);
    if(i===0)expect(rect.x+width).toBeLessThan(a.x-10);else expect(rect.x).toBeGreaterThan(a.x+10);
    expect(b.y-(124+titleHeight)).toBeGreaterThanOrEqual(16);
    for(const obstacle of safe.obstacles){expect(rectanglesOverlap(rect,obstacle)).toBe(false);for(const [p,q] of paths.flat())expect(lineTouchesRect(p,q,obstacle)).toBe(false);}
   }
   for(const point of paths.flat(2))expectInside({...point,width:0,height:0},safe);
   for(const object of [ctx.model.getObjectByName('crane'),ctx.groups.get(shot.id).userData.ref]){
    const p=projectedBounds(ctx,new ctx.THREE.Box3().setFromObject(object));expectInside({x:p.left*1920,y:p.top*1080,width:(p.right-p.left)*1920,height:(p.bottom-p.top)*1080},safe);
   }
   if(t===2.5){if(snapshot)expect(ctx.labels.innerHTML).toBe(snapshot);snapshot=ctx.labels.innerHTML;}
  }
 }
});
test('爆炸小车本体Box3中心锚点与主梁分离且间距至少24像素',async()=>{
 const module=await import('../player/shots/exploded.js'),{projectBounds}=await import('../player/shots/common.js'),{hudSafeArea}=await import('../player/shots/layout.js');
 const ctx=await geometryContext(),shot=fixture.shots.find(s=>s.kind==='exploded');
 mockHud(ctx,{...hudRects,'.section-title':{x:76,y:154,width:500,height:104}});
 for(const t of [0,.1,1,2.5,4.9,5,2.5]){
  for(const o of ctx.originals)o.n.position.copy(o.p);
  module.render(ctx,shot,t,5);
  const labels=explodedLabels(ctx.labels.innerHTML),trolley=labels.find(v=>v.id==='trolley')!,girder=labels.find(v=>v.id==='girder')!;
  const tb=partBounds(ctx.model.getObjectByName('trolley')),gb=partBounds(ctx.model.getObjectByName('girder'));
  const tr=projectBounds(ctx,tb),gr=projectBounds(ctx,gb),anchor=tb.getCenter(new ctx.THREE.Vector3()).project(ctx.camera);
  expect(trolley.x).toBeCloseTo((anchor.x+1)*960,5);expect(trolley.y).toBeCloseTo((1-anchor.y)*540,5);
  expectInside({x:trolley.x,y:trolley.y,width:0,height:0},tr);
  expect(rectanglesOverlap(tr,gr)).toBe(false);expect(lineTouchesRect(trolley,trolley,gr)).toBe(false);
  expect(gr.y-tr.y-tr.height).toBeGreaterThanOrEqual(24);
  const safe=hudSafeArea(ctx,shot,t);
  for(const label of labels)expectInside({x:label.labelX,y:label.labelY,width:210,height:50},safe);
  expect(Math.hypot(trolley.x-girder.x,trolley.y-girder.y)).toBeGreaterThanOrEqual(24);
  assertLeadersSeparate(labels);
 }
});

test('S2双分辨率真实HUD避让与中点标签在乱序定位后保持一致',async({page})=>{
 const data=structuredClone(fixture);
 data.analogies.A_length={ref:'building_floor',axis:'height',ref_size_m:3,ratio:17,fact:'F_overall_height',text:'相当于17层楼的高度'};
 data.captions=[{start:11,end:14,text:'把高度放回日常\n每层楼以3米作参照'}];
 await page.route('**/height-safe.json',route=>route.fulfill({json:data}));
 for(const viewport of [{width:1920,height:1080},{width:1366,height:768}]){
  await page.setViewportSize(viewport);await page.goto('/player/index.html?timeline=/fixtures/height-safe.json&mode=render');await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
  let snapshot='';
  for(const t of [12.5,7,10,14.9,12.5]){
   await page.evaluate(t=>window.__player.seek(t),t);if(t===7)continue;
   const stage=(await page.locator('#stage').boundingBox())!,scale=stage.width/1920;
   const convert=r=>({x:(r.x-stage.x)/scale,y:(r.y-stage.y)/scale,width:r.width/scale,height:r.height/scale});
   const obstacles=[];
   for(const selector of ['#badge','.section-title','#film-title','#caption','footer','.analogy-copy']){
    const rect=await page.locator(selector).boundingBox();if(rect)obstacles.push(convert(rect));
   }
   const title=convert((await page.locator('.section-title').boundingBox())!);
   const paths=await page.locator('#labels .dimension path').evaluateAll(nodes=>nodes.map(n=>n.getAttribute('d')!));
   const segments=paths.flatMap(pathSegments),labels=[];
   for(const [i,label] of (await page.locator('.dimension-label').all()).entries()){
    const rect=convert((await label.boundingBox())!);labels.push(rect);
    const [a,b]=pathSegments(paths[i])[0];expect(rect.y+rect.height/2).toBeCloseTo((a.y+b.y)/2,1);
    expect(b.y-title.y-title.height).toBeGreaterThanOrEqual(16);
    if(i===0)expect(rect.x+rect.width).toBeLessThan(a.x-10);else expect(rect.x).toBeGreaterThan(a.x+10);
    for(const obstacle of obstacles)expect(rectanglesOverlap(rect,obstacle)).toBe(false);
   }
   for(const [a,b] of segments)for(const obstacle of obstacles)expect(lineTouchesRect(a,b,obstacle)).toBe(false);
   const top=Math.max(196,...obstacles.slice(0,3).map(r=>r.y+r.height))+16;
   const bottom=Math.min(880,...obstacles.slice(3).map(r=>r.y))-16;
   const safe={x:40,y:top,width:1840,height:bottom-top};
   for(const rect of labels)expectInside(rect,safe);
   for(const point of segments.flat())expectInside({...point,width:0,height:0},safe);
   if(t===12.5){const actual=JSON.stringify({paths,labels});if(snapshot)expect(actual).toBe(snapshot);snapshot=actual;}
  }
 }
});

function visibleModelRect(ctx){
 const points=[];
 ctx.model.traverseVisible(node=>{
  if(!node.isMesh)return;
  node.geometry.computeBoundingBox();node.updateWorldMatrix(true,false);
  const b=node.geometry.boundingBox;
  for(const x of [b.min.x,b.max.x])for(const y of [b.min.y,b.max.y])for(const z of [b.min.z,b.max.z]){
   const p=new ctx.THREE.Vector3(x,y,z).applyMatrix4(node.matrixWorld).project(ctx.camera);
   points.push({x:(p.x+1)*960,y:(1-p.y)*540});
  }
 });
 const x=Math.min(...points.map(p=>p.x)),y=Math.min(...points.map(p=>p.y));
 return {x,y,width:Math.max(...points.map(p=>p.x))-x,height:Math.max(...points.map(p=>p.y))-y};
}
test('T13c分解联合投影占宽60至70且高亮圆环完整可见',async()=>{
 const module=await import('../player/shots/exploded.js'),{hudSafeArea}=await import('../player/shots/layout.js');
 for(const titleHeight of [92,104])for(const spread of [8,12,18])for(const includeHook of [false,true]){
  const ctx=await geometryContext(),shot=structuredClone(fixture.shots.find(s=>s.kind==='exploded'));
  shot.params.spread_m=spread;if(includeHook)shot.params.parts.push('hoist_hook');
  mockHud(ctx,{...hudRects,'.section-title':{x:76,y:154,width:500,height:titleHeight}});
  let snapshot='';
  for(const t of [2.5,0,1,4.9,2.5]){
   for(const o of ctx.originals)o.n.position.copy(o.p);
   module.render(ctx,shot,t,5);
   const rect=visibleModelRect(ctx),safe=hudSafeArea(ctx,shot,t);
   expectInside(rect,{x:0,y:0,width:1920,height:1080});
   expect(rect.width/1920).toBeGreaterThanOrEqual(.6);expect(rect.width/1920).toBeLessThanOrEqual(.7);
   const rings=[...ctx.labels.innerHTML.matchAll(/data-highlight="([^"]+)" cx="([^"]+)" cy="([^"]+)" r="([^"]+)"/g)];
   expect(rings).toHaveLength(2);
   for(const [,id,x,y,r] of rings){
    expect(Number(r)*1366/1920).toBeGreaterThanOrEqual(14);
    expectInside({x:Number(x)-Number(r),y:Number(y)-Number(r),width:Number(r)*2,height:Number(r)*2},{x:0,y:0,width:1920,height:1080});
    expect(ctx.originals.find(o=>o.n.name===id).n.scale.equals(ctx.originals.find(o=>o.n.name===id).s)).toBe(true);
   }
   const labels=explodedLabels(ctx.labels.innerHTML);assertLeadersSeparate(labels);
   for(const label of labels)expectInside({x:label.labelX,y:label.labelY,width:210,height:50},safe);
   const tb=partBounds(ctx.model.getObjectByName('trolley')),gb=partBounds(ctx.model.getObjectByName('girder'));
   const {projectBounds}=await import('../player/shots/common.js');
   const tr=projectBounds(ctx,tb),gr=projectBounds(ctx,gb),trolley=labels.find(v=>v.id==='trolley')!;
   expect(rectanglesOverlap(tr,gr)).toBe(false);
   expectInside({x:trolley.x,y:trolley.y,width:0,height:0},tr);
   if(t===2.5){if(snapshot)expect(ctx.labels.innerHTML).toBe(snapshot);snapshot=ctx.labels.innerHTML;}
  }
 }
});
test('T13地面覆盖远裁剪范围且平移不改变世界网格定位',async()=>{
 const {createGround,createBackdrop,updateGround}=await import('../player/shots/common.js'),ctx=await geometryContext();
 const texture=new ctx.THREE.Texture(),floor=createGround(ctx.camera,texture);ctx.floor=floor;ctx.backdrop=createBackdrop();
 ctx.scene.fog=new ctx.THREE.Fog('#1d2b3a',230,650);ctx.scene.background.set('#142330');
 for(const x of [-120,0,240]){
  ctx.camera.position.set(x,80,160);texture.offset.set(0,.25);updateGround(ctx);
  expect(floor.geometry.parameters.width/2).toBeGreaterThanOrEqual(ctx.camera.far);
  expect(floor.geometry.parameters.height/2).toBeGreaterThanOrEqual(ctx.camera.far);
  expect(ctx.scene.fog.color.equals(ctx.scene.background)).toBe(true);
  expect(floor.userData.fadeUniforms.skyColor.value.equals(ctx.backdrop.material.uniforms.skyColor.value)).toBe(true);
  const extent=floor.geometry.parameters.width;
  // 世界原点的纹理坐标与相机平移无关；保留镜头自身的运动偏移。
  expect((.5-x/extent)*texture.repeat.x+texture.offset.x).toBeCloseTo(texture.repeat.x/2,8);
  expect((.5+160/extent)*texture.repeat.y+texture.offset.y).toBeCloseTo(texture.repeat.y/2+.25,8);
  expect(floor.userData.fadeUniforms.groundFadeNear.value).toBe(ctx.camera.near);
  expect(floor.userData.fadeUniforms.groundFadeFar.value).toBeGreaterThan(ctx.camera.near);
 }
});

// 只截三维画布，排除字幕底片、数字卡和转场；不裁掉画布底部。
test('T13b三维镜头左右背景列无硬边且过渡带至少15%',async({page},testInfo)=>{
 await ready(page);
 for(const kind of ['model_orbit','exploded','analogy']){
  const shot=fixture.shots.find(s=>s.kind===kind);
  for(const fraction of [.2,.5,.8]){
   await page.evaluate(t=>window.__player.seek(t),shot.start+(shot.end-shot.start)*fraction);
   const ctx=await geometryContext(),module=await import(`../player/shots/${kind}.js`);
   const measured=await page.evaluate(()=>{
    const stage=document.getElementById('stage')!.getBoundingClientRect(),scale=stage.width/1920,result={};
    for(const selector of ['#badge','.section-title','#film-title','#caption','footer','.analogy-copy']){
     const r=document.querySelector(selector)?.getBoundingClientRect();
     if(r?.width&&r.height)result[selector]={x:(r.x-stage.x)/scale,y:(r.y-stage.y)/scale,width:r.width/scale,height:r.height/scale};
    }
    return result;
   });
   mockHud(ctx,measured);module.setup(ctx,shot);module.render(ctx,shot,(shot.end-shot.start)*fraction,shot.end-shot.start);
   if(kind==='model_orbit')fitBackgroundColumns(ctx);
   // 模型及参照物必须离开两侧各 8% 的采样竖条。
   for(const object of [ctx.model,...ctx.groups.values()].filter(n=>n.visible)){
    const r=visibleModelRect({...ctx,model:object});
    expect(r.x,`${kind} 左侧背景列被模型侵入`).toBeGreaterThanOrEqual(1920*.08);
    expect(r.x+r.width,`${kind} 右侧背景列被模型侵入`).toBeLessThanOrEqual(1920*.92);
   }
   const data=await page.locator('#scene').evaluate((canvas:HTMLCanvasElement)=>canvas.toDataURL('image/png'));
   const buffer=Buffer.from(data.split(',')[1],'base64');
   await testInfo.attach(`${kind}-${fraction}.png`,{body:buffer,contentType:'image/png'});
   const result=await page.evaluate(async src=>{
    const image=new Image();image.src=src;await image.decode();
    const canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;
    const g=canvas.getContext('2d')!;g.drawImage(image,0,0);const pixels=g.getImageData(0,0,canvas.width,canvas.height).data;
    const strip=Math.floor(canvas.width*.08),columns=[[0,strip],[canvas.width-strip,canvas.width]],results=[];
    for(const [left,right] of columns){
     let previous=0,maximum=0,row=0;const means=[];
     for(let y=0;y<canvas.height;y++){
      let mean=0;for(let x=left;x<right;x++){const i=(y*canvas.width+x)*4;mean+=.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2];}
      mean/=right-left;means.push(mean);
      if(y&&Math.abs(mean-previous)>maximum){maximum=Math.abs(mean-previous);row=y;}previous=mean;
     }
     const low=Math.min(...means),range=Math.max(...means)-low;
     const first=means.findIndex(v=>v>=low+range*.1),last=means.findIndex(v=>v>=low+range*.9);
     results.push({maximum,row,range,transition:(last-first)/canvas.height});
    }
    return results;
   },data);
   for(const [side,r] of result.entries()){
    expect(r.range,`${kind} 背景不能为纯色`).toBeGreaterThan(30);
    expect(r.maximum,`${kind} ${side?'右':'左'}背景第 ${r.row} 行亮度突变`).toBeLessThan(12);
    expect(r.transition,`${kind} 背景过渡带太窄`).toBeGreaterThanOrEqual(.15);
   }
  }
 }
});
test('T13分解圆环在双分辨率下清晰且切镜恢复轨道',async({page})=>{
 for(const viewport of [{width:1920,height:1080},{width:1366,height:768}]){
  await page.setViewportSize(viewport);await ready(page);
  await page.evaluate(()=>window.__player.seek(7.5));const before=await page.locator('#scene').evaluate((c:HTMLCanvasElement)=>c.toDataURL());
  for(const t of [22.5,21,24,22.5]){
   await page.evaluate(t=>window.__player.seek(t),t);
   const rings=page.locator('#labels .part-highlight');await expect(rings).toHaveCount(2);
   for(const ring of await rings.all()){
    const box=(await ring.boundingBox())!;expect(box.width/2).toBeGreaterThanOrEqual(14);expect(box.height/2).toBeGreaterThanOrEqual(14);
    await expect(ring).toHaveCSS('fill','none');await expect(ring).toHaveCSS('stroke-width','3px');
   }
  }
  await page.evaluate(()=>window.__player.seek(7.5));expect(await page.locator('#scene').evaluate((c:HTMLCanvasElement)=>c.toDataURL())).toBe(before);
 }
});


test('T13c保留T12斜俯视并收紧分解位移且主梁净空至少6米',async()=>{
 const module=await import('../player/shots/exploded.js'),{ease}=await import('../player/shots/common.js');
 for(const spread of [0,8,12,18]){
  const ctx=await geometryContext(),shot=structuredClone(fixture.shots.find(s=>s.kind==='exploded'));
  shot.params.spread_m=spread;shot.params.parts.push('hoist_hook');
  mockHud(ctx,{...hudRects,'.section-title':{x:76,y:154,width:500,height:104}});
  const hook=ctx.model.getObjectByName('hoist_hook'),trolley=ctx.model.getObjectByName('trolley'),rope=ctx.model.getObjectByName('rope');
  const hookRelative=hook.position.clone(),ropeRelative=rope.position.clone();
  for(const t of [2.5,0,.1,1,4.9,5,2.5]){
   for(const o of ctx.originals)o.n.position.copy(o.p);
   module.render(ctx,shot,t,5);
   const girder=new ctx.THREE.Box3().setFromObject(ctx.model.getObjectByName('girder'));
   for(const id of ['leg_left','leg_right']){
    const leg=ctx.model.getObjectByName(id),bounds=new ctx.THREE.Box3().setFromObject(leg);
    expect(girder.min.y).toBeGreaterThan(bounds.max.y);
    expect(girder.min.y-bounds.max.y).toBeGreaterThanOrEqual(6-1e-8);
    const original=ctx.originals.find(o=>o.n===leg).p;
    expect(leg.position.y).toBeCloseTo(original.y,8);expect(leg.position.z).toBeCloseTo(original.z,8);
    expect((leg.position.x-original.x)*(id==='leg_left'?-1:1)).toBeCloseTo(ease(Math.min(t/5*3,(1-t/5)*3))*spread*.6,8);
   }
   expect(hook.position.x).toBeCloseTo(hookRelative.x,8);
   expect(hook.position.y-hookRelative.y).toBeCloseTo(-ease(Math.min(t/5*3,(1-t/5)*3))*spread*.6,8);
   expect(rope.position.distanceTo(ropeRelative)).toBeLessThan(1e-8);
   expect(partBounds(hook).max.y).toBeLessThan(partBounds(trolley).min.y);
   const direction=ctx.camera.getWorldDirection(new ctx.THREE.Vector3());
   const elevation=ctx.THREE.MathUtils.radToDeg(Math.asin(Math.abs(direction.y)));
   const azimuth=ctx.THREE.MathUtils.radToDeg(Math.atan2(-direction.x,-direction.z));
   expect(elevation).toBeCloseTo(14,8);expect(azimuth).toBeCloseTo(13,8);
   expect(ctx.camera.projectionMatrix.elements[11]).toBe(0);expect(ctx.camera.projectionMatrix.elements[15]).toBe(1);
   const rect=visibleModelRect(ctx);expect(rect.width/1920).toBeGreaterThanOrEqual(.6);expect(rect.width/1920).toBeLessThanOrEqual(.7);
  }
 }
});

test('T13b背景采样竖条不包含模型或类比参照物',async()=>{
 for(const kind of ['model_orbit','exploded','analogy'])for(const fraction of [.2,.5,.8]){
  const ctx=await geometryContext(),shot=fixture.shots.find(s=>s.kind===kind),module=await import(`../player/shots/${kind}.js`);
  mockHud(ctx,hudRects);module.setup(ctx,shot);module.render(ctx,shot,(shot.end-shot.start)*fraction,shot.end-shot.start);
   if(kind==='model_orbit')fitBackgroundColumns(ctx);
  for(const object of [ctx.model,...ctx.groups.values()].filter(n=>n.visible)){
   const r=visibleModelRect({...ctx,model:object});
   expect(r.x,`${kind} 左侧背景列被模型侵入`).toBeGreaterThanOrEqual(1920*.08);
   expect(r.x+r.width,`${kind} 右侧背景列被模型侵入`).toBeLessThanOrEqual(1920*.92);
  }
 }
});

test('T16写实背景帧锚点与网页三维切换保持确定性',async({page})=>{
 const requests:string[]=[];page.on('request',request=>requests.push(request.url()));
 await page.goto('/player/index.html?timeline=/fixtures/background/timeline.json&mode=render');
 await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
 const bg=page.locator('#bg-frame');
 for(const [t,frame,x,y] of [[0,1,720,360],[.5,2,840,420],[1.49,3,1080,460],[.25,2,840,420],[0,1,720,360]]){
  await page.evaluate(t=>window.__player.seek(t),t);
  await expect(bg).toBeVisible();await expect(bg).toHaveAttribute('src',new RegExp(`frame_0000${frame}\\.jpg$`));
  await expect(page.locator('#scene')).toHaveCSS('visibility','hidden');
  await expect(page.locator('#labels [data-part=trolley]')).toHaveCount(0);
  const dot=page.locator('#labels [data-part=girder] circle');
  expect(Math.abs(Number(await dot.getAttribute('cx'))-x)).toBeLessThanOrEqual(2);
  expect(Math.abs(Number(await dot.getAttribute('cy'))-y)).toBeLessThanOrEqual(2);
  const rgb=await bg.evaluate((img:HTMLImageElement)=>{
   const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
   const context=canvas.getContext('2d')!;context.drawImage(img,0,0,1,1);return Array.from(context.getImageData(0,0,1,1).data).slice(0,3);
  });
  expect(rgb[frame-1]).toBeGreaterThan(245);for(let c=0;c<3;c++)if(c!==frame-1)expect(rgb[c]).toBeLessThan(10);
  await expect(page.locator('#badge')).toHaveText('三维模型渲染 · 写实（Blender） · 参数化重建');
  await expect(page.locator('#caption')).toHaveText('写实背景锚点验证');
 }
 expect(requests.some(url=>url.endsWith('frame_00002.jpg'))).toBe(true);
 expect(requests.some(url=>url.endsWith('frame_00003.jpg'))).toBe(true);
 await page.evaluate(()=>window.__player.seek(2.5));
 await expect(page.locator('#content h1')).toHaveText('写实开场');
 await expect(page.locator('#scene')).toHaveCSS('visibility','hidden');
 await page.evaluate(()=>window.__player.seek(3.5));
 await expect(page.locator('#motion-info')).toContainText('×2 倍速');
 await expect(bg).toBeVisible();
 await page.evaluate(()=>window.__player.seek(5));
 await expect(bg).toBeHidden();await expect(page.locator('#scene')).toHaveCSS('visibility','visible');
 await expect(page.locator('#badge')).toHaveText('三维模型渲染 · 参数化重建');
 await page.evaluate(()=>window.__player.seek(.5));
 await expect(bg).toHaveAttribute('src',/frame_00002\.jpg$/);
});

test('写实爆炸背景引线终点精确使用表面锚点且就近放置',async({page})=>{
 const anchors=JSON.parse(await readFile(new URL('./fixtures/background/exploded-anchors.json',import.meta.url),'utf8'));
 await page.goto('/player/index.html?timeline=/fixtures/background/exploded-timeline.json&mode=render');
 await page.waitForFunction(()=>!!window.__player);await page.evaluate(()=>window.__player.ready);
 let first='';
 for(const [t,frame] of [[0,1],[1.49,3],[.5,2],[0,1]]){
  await page.evaluate(t=>window.__player.seek(t),t);
  await expect(page.locator('#scene')).toHaveCSS('visibility','hidden');
  await expect(page.locator('#bg-frame')).toBeVisible();
  await expect(page.locator('#labels g[data-part]')).toHaveCount(6);

  await expect(page.locator('#content .section-title')).toContainText('从整体，读懂协同');
  const nodes=anchors.frames[frame-1].nodes;
  const leaders=explodedLabels(await page.locator('#labels').innerHTML());
  assertLeadersSeparate(leaders);
  for(const v of leaders){
   for(const [a,b] of v.segments)expect(a.x===b.x||a.y===b.y,`${v.id} 引线必须正交`).toBe(true);
   expect(v.segments.filter(([a,b])=>a.y!==b.y).length).toBeLessThanOrEqual(1);
  }
  const boxes=Object.values(nodes).map((v:any)=>v.bbox.map((n:number)=>n*2));
  const leftX=Math.max(40,Math.min(1920*.74-210,Math.min(...boxes.map(b=>b[0]))-238))+210;
  const rightX=Math.max(40,Math.min(1920*.74-210,Math.max(...boxes.map(b=>b[2]))+28));
  for(const v of leaders.filter(v=>['hoist_hook','trolley'].includes(v.id))){
   expect(v.side).toBe(Math.abs(v.x-leftX)<=Math.abs(v.x-rightX)?'left':'right');
  }

  for(const [id,value] of Object.entries(nodes)){
   const node=value as {x:number,y:number,bbox:number[],pin:{x:number,y:number}};
   const point=await page.locator(`#labels g[data-part=${id}] path`).evaluate((path:SVGPathElement)=>{
    const end=path.getPointAtLength(path.getTotalLength());return {x:end.x,y:end.y};
   });
   expect(Math.abs(point.x-node.pin.x*2),id).toBeLessThanOrEqual(2);
   expect(Math.abs(point.y-node.pin.y*2),id).toBeLessThanOrEqual(2);
  }
  for(const id of ['hoist_hook','trolley']){
   await expect(page.locator(`[data-highlight=${id}]`)).toHaveAttribute('cx',String(nodes[id].pin.x*2));
   await expect(page.locator(`[data-highlight=${id}]`)).toHaveAttribute('cy',String(nodes[id].pin.y*2));
  }
  const left=await page.locator('#labels g[data-side=left]').evaluateAll(groups=>groups.map(g=>({id:g.getAttribute('data-part')!,right:Number(g.querySelector('rect')!.getAttribute('x'))+210})));
  const edge=Math.min(...left.map(v=>nodes[v.id].bbox[0]*2));
  for(const label of left){expect(edge-label.right).toBeGreaterThanOrEqual(0);expect(edge-label.right).toBeLessThanOrEqual(40);}
  const html=await page.locator('#labels').innerHTML();
  if(frame===1){if(first)expect(html).toBe(first);else first=html;}
 }
 await page.evaluate(()=>window.__player.seek(2));
 await expect(page.locator('#scene')).toHaveCSS('visibility','visible');
 await expect(page.locator('#bg-frame')).toBeHidden();
 await page.evaluate(()=>window.__player.seek(.5));
 await expect(page.locator('#scene')).toHaveCSS('visibility','hidden');
 await expect(page.locator('#labels [data-part=cab]')).toBeVisible();
});

for(const mode of ['standard','photoreal'])for(const count of [2,3,4]){
 test(`${mode}模式${count}项参数卡完整容纳项目且位于字幕上方`,async({page})=>{
  const data=structuredClone(fixture);data.render_mode=mode;
  const ids=Object.keys(data.facts).slice(0,count);
  const card={...data.shots.find(s=>s.kind==='data_card'),id:'CARD',start:0,end:6,params:{facts:ids}};
  if(mode==='photoreal'){
   const bg=JSON.parse(await readFile(new URL('./fixtures/background/timeline.json',import.meta.url),'utf8')).shots[0].bg;
   card.bg={...bg,frames:'/fixtures/background/frame_%05d.jpg',anchors:'/fixtures/background/anchors.json'};
  }
  data.shots=[card];data.duration_s=6;data.captions=[{start:0,end:6,text:'参数来自已核验技术资料\n完整来源保留在每个数值下方'}];
  await page.route('**/cards-t18.json',route=>route.fulfill({json:data}));
  for(const size of [{width:1920,height:1080},{width:960,height:540}]){
   await page.setViewportSize(size);
   await page.goto('/player/index.html?timeline=/fixtures/cards-t18.json&mode=render');
   await page.evaluate(()=>window.__player.ready);
   for(const t of [2,0,5,2]){
    await page.evaluate(t=>window.__player.seek(t),t);
    const panel=(await page.locator('.data-panel').boundingBox())!,caption=(await page.locator('#caption').boundingBox())!;
    expect(panel.y+panel.height).toBeLessThan(caption.y-12*size.width/1920);
    await expect(page.locator('.data-card')).toHaveCount(count);
    for(const item of await page.locator('.data-card,.data-card .source').all()){
     const box=(await item.boundingBox())!;
     expect(box.x).toBeGreaterThanOrEqual(panel.x);expect(box.y).toBeGreaterThanOrEqual(panel.y);
     expect(box.x+box.width).toBeLessThanOrEqual(panel.x+panel.width+1);
     expect(box.y+box.height).toBeLessThanOrEqual(panel.y+panel.height+1);
    }
    if(count===4){
     const boxes=await Promise.all((await page.locator('.data-card').all()).map(el=>el.boundingBox()));
     expect(boxes[0]!.y).toBeCloseTo(boxes[1]!.y,1);expect(boxes[2]!.y).toBeCloseTo(boxes[3]!.y,1);
     expect(boxes[2]!.y).toBeGreaterThan(boxes[0]!.y);
    }
    if(mode==='photoreal')await expect(page.locator('#bg-frame')).toHaveCSS('filter','brightness(0.78)');
   }
  }
 });
}

test('写实类比背景左上为深蓝且焊缝切换不破坏主题，标准默认画面一致',async({page})=>{
 const colors:Record<string,number[]>={};
 for(const mode of ['default','standard','photoreal']){
  const data=structuredClone(fixture);if(mode!=='default')data.render_mode=mode;
  await page.route(`**/theme-${mode}.json`,route=>route.fulfill({json:data}));
  await page.goto(`/player/index.html?timeline=/fixtures/theme-${mode}.json&mode=render`);
  await page.evaluate(()=>window.__player.ready);
  const analogy=data.shots.find(s=>s.kind==='analogy'),weld=data.shots.find(s=>s.kind==='weld_macro');
  const sample=()=>page.locator('#scene').evaluate((canvas:HTMLCanvasElement)=>{
   const c=document.createElement('canvas');c.width=1920;c.height=1080;
   const g=c.getContext('2d')!;g.drawImage(canvas,0,0);return Array.from(g.getImageData(10,10,1,1).data);
  });
  await page.evaluate(t=>window.__player.seek(t),(analogy.start+analogy.end)/2);colors[mode]=await sample();
  await page.evaluate(t=>window.__player.seek(t),(weld.start+weld.end)/2);await expect(page.locator('#error')).toBeHidden();
  await page.evaluate(t=>window.__player.seek(t),(analogy.start+analogy.end)/2);expect(await sample()).toEqual(colors[mode]);
 }
 expect(colors.standard).toEqual(colors.default);
 const [r,,b]=colors.photoreal;expect(b).toBeGreaterThan(r+8);expect(r).toBeLessThan(95);
 expect(colors.photoreal).not.toEqual(colors.standard);
});

test('参数卡与片尾背景切换恢复亮度且片尾保留标题',async({page})=>{
 const data=JSON.parse(await readFile(new URL('./fixtures/background/timeline.json',import.meta.url),'utf8'));
 data.render_mode='photoreal';data.shots=[
  {...data.shots[0],id:'CARD',kind:'data_card',start:0,end:2,params:{facts:[]}},
  {...data.shots[0],id:'END',kind:'outro',start:2,end:4,params:{title:'宏大来自精确'}}];
 data.duration_s=4;
 await page.route('**/background/graphic-t18.json',route=>route.fulfill({json:data}));
 await page.goto('/player/index.html?timeline=/fixtures/background/graphic-t18.json&mode=render');
 await page.evaluate(()=>window.__player.ready);await page.evaluate(()=>window.__player.seek(1));
 await expect(page.locator('#bg-frame')).toHaveCSS('filter','brightness(0.78)');
 await page.evaluate(()=>window.__player.seek(3));
 await expect(page.locator('#bg-frame')).toBeVisible();await expect(page.locator('#scene')).toHaveCSS('visibility','hidden');
 await expect(page.locator('#bg-frame')).toHaveCSS('filter','none');await expect(page.locator('.outro h1')).toHaveText('宏大来自精确');
});

test('写实片尾副标题和来源在浅色天空上的像素对比度至少4.5',async({page})=>{
 const data=JSON.parse(await readFile(new URL('./fixtures/background/timeline.json',import.meta.url),'utf8'));
 data.render_mode='photoreal';data.duration_s=4;
 data.facts={F_span:{name:'跨度',value:88,unit:'m',source:{doc:'设备技术参数与结构说明.pdf',page:2}}};
 data.shots=[{...data.shots[0],id:'END',kind:'outro',start:0,end:4,
  params:{title:'宏大来自精确',subtitle:'每一次协同，都有真实工程依据'},
  bg:{...data.shots[0].bg,frames:'bright-frame_%05d.jpg'}}];
 data.captions=[{start:0,end:4,text:'以事实丈量工程'}];
 await page.route('**/background/contrast-t18b.json',route=>route.fulfill({json:data}));
 await page.route('**/background/bright-frame_*.jpg',route=>route.fulfill({contentType:'image/svg+xml',body:
  '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"><defs><linearGradient id="sky"><stop stop-color="#e5eef5"/><stop offset="1" stop-color="#ffffff"/></linearGradient></defs><path fill="url(#sky)" d="M0 0H1920V1080H0Z"/></svg>'}));
 for(const size of [{width:1920,height:1080},{width:960,height:540}]){
  await page.setViewportSize(size);
  await page.goto('/player/index.html?timeline=/fixtures/background/contrast-t18b.json&mode=render');
  await page.evaluate(()=>window.__player.ready);await page.evaluate(()=>window.__player.seek(2));
  await expect(page.locator('.outro-shade')).toBeVisible();
  const paragraph=page.locator('.outro-background p');
  const rows=await paragraph.evaluate(el=>{
   const box=el.getBoundingClientRect();
   return [...el.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE&&node.textContent?.trim()).map(node=>{
    const range=document.createRange();range.selectNodeContents(node);
    return [...range.getClientRects()].map(r=>({x:r.x-box.x,y:r.y-box.y,width:r.width,height:r.height}));
   });
  });
  expect(rows).toHaveLength(3);
  const foreground=(await paragraph.screenshot()).toString('base64');
  // 同一坐标隐藏字形及阴影，保留遮罩和段落底色，取得真实文字背后的像素。
  await paragraph.evaluate((el:HTMLElement)=>{el.style.color='transparent';el.style.textShadow='none';});
  const background=(await paragraph.screenshot()).toString('base64');
  await paragraph.evaluate((el:HTMLElement)=>{el.style.removeProperty('color');el.style.removeProperty('text-shadow');});
  const samples=await page.evaluate(async({foreground,background,rows})=>{
   const load=async(data:string)=>{
    const img=new Image();img.src='data:image/png;base64,'+data;await img.decode();
    const canvas=document.createElement('canvas');canvas.width=img.width;canvas.height=img.height;
    const g=canvas.getContext('2d')!;g.drawImage(img,0,0);
    return {width:img.width,height:img.height,rgba:g.getImageData(0,0,img.width,img.height).data};
   };
   const ink=await load(foreground),back=await load(background);
   const luminance=(rgb:number[])=>rgb.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;})
    .reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
   return rows.map(rects=>{
    let count=0,min=Infinity;
    for(const r of rects)for(let y=Math.max(0,Math.ceil(r.y));y<Math.min(ink.height,r.y+r.height);y++){
     for(let x=Math.max(0,Math.ceil(r.x));x<Math.min(ink.width,r.x+r.width);x++){
      const i=(y*ink.width+x)*4,fg=Array.from(ink.rgba.slice(i,i+3));
      // 只取字形内部实色像素，排除抗锯齿边缘及阴影。
      if(!fg.every((v,j)=>Math.abs(v-[245,247,250][j])<=8))continue;
      const bg=Array.from(back.rgba.slice(i,i+3));
      min=Math.min(min,(luminance(fg)+.05)/(luminance(bg)+.05));count++;
     }
    }
    return {count,min};
   });
  },{foreground,background,rows});
  for(const [i,sample] of samples.entries()){
   expect(sample.count,`第 ${i+1} 行须采到字形内部像素`).toBeGreaterThan(30);
   expect(sample.min,`第 ${i+1} 行文字对比度`).toBeGreaterThanOrEqual(4.5);
  }
 }
});

for(const [shotIndex,axis] of ['height','length'].entries())test(`T19写实类比${axis}尺寸线与帧锚点一致`,async({page})=>{
 const anchors=JSON.parse(await readFile(new URL(`./fixtures/background/analogy-${axis}-anchors.json`,import.meta.url),'utf8'));
 await page.goto('/player/index.html?timeline=/fixtures/background/analogy-timeline.json&mode=render');
 await page.evaluate(()=>window.__player.ready);
 for(const [local,frame] of [[.5,2],[1,3],[0,1],[.5,2]]){
  await page.evaluate(t=>window.__player.seek(t),shotIndex*1.5+local);
  await expect(page.locator('#scene')).toHaveCSS('visibility','hidden');
  await expect(page.locator('#bg-frame')).toBeVisible();
  await expect(page.locator('.dimension-label')).toHaveCount(2);
  const paths=await page.locator('#labels .dimension path').evaluateAll(nodes=>nodes.map(node=>{
   const values=node.getAttribute('d')!.match(/^M ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+)/)!;
   return values.slice(1).map(Number);
  }));
  const keys=axis==='height'?[['crane_bottom','crane_top'],['ref_bottom','ref_top']]:[['crane_left','crane_right'],['ref_left','ref_right']];
  for(let i=0;i<2;i++){
   const [a,b]=keys[i].map(k=>anchors.frames[frame-1].dims[k]);
   [a.x*2,a.y*2,b.x*2,b.y*2].forEach((expected,j)=>expect(Math.abs(paths[i][j]-expected)).toBeLessThanOrEqual(2));
  }
 }
});
