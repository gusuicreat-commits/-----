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
