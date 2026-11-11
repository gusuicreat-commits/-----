import {test,expect,Page} from '@playwright/test';
import {readFile,mkdtemp,rm,mkdir,writeFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {tmpdir} from 'node:os';
import path from 'node:path';
const exec=promisify(execFile);
const fixture=JSON.parse(await readFile(new URL('./fixtures/timeline.json',import.meta.url),'utf8'));
let model:Buffer,temp:string;
test.beforeAll(async()=>{
 temp=await mkdtemp(path.join(tmpdir(),'kepu-t22-browser-'));
 const out=path.join(temp,'crane.glb');
 await exec(path.resolve('../backend/.venv/bin/python'),['-c',`from pathlib import Path
from app.model3d.parametric import build_parametric
import sys
build_parametric({'F_girder_length':104,'F_overall_height':51,'F_span':88,'F_wheel_count':64},Path(sys.argv[1]))`,out],{cwd:path.resolve('../backend')});
 model=await readFile(out);
});
test.afterAll(async()=>{if(temp)await rm(temp,{recursive:true,force:true});});
async function ready(page:Page,{quality='standard',mode='standard',bg=false,building=false}={}){
 await page.route('**/favicon.ico',route=>route.fulfill({status:204}));
 const timeline=structuredClone(fixture);timeline.render_mode=mode;timeline.model.glb='/fixtures/t22-crane.glb';
 timeline.model.rig.bbox_m={x:104,y:51,z:120};
 if(building){timeline.analogies.A_t22_height={fact:'F_overall_height',ref:'building_floor',axis:'height',ratio:17,text:'相当于17层楼',ref_size:3,ref_size_m:3,ref_unit:'m'};timeline.shots.find(s=>s.kind==='analogy').params.analogy='A_t22_height';}
 if(bg)timeline.shots.find(s=>s.kind==='model_orbit').bg={anchors:'/fixtures/missing-anchors.json',frames:'/fixtures/missing_%05d.jpg',fps:30,count:150,width:1920,height:1080};
 await page.route('**/t22-crane.glb',route=>route.fulfill({body:model,contentType:'model/gltf-binary'}));
 await page.route('**/t22-timeline.json',route=>route.fulfill({json:timeline}));
 await page.goto(`/player/index.html?timeline=/fixtures/t22-timeline.json&mode=render&quality=${quality}`);
 await page.evaluate(()=>window.__player.ready);return timeline;
}
async function canvasPixels(page:Page){return page.locator('#scene').evaluate((canvas:HTMLCanvasElement)=>canvas.toDataURL('image/png'));}

// 精确比较编码后的画布；跨镜头和重新加载也不能依赖历史帧。
test('T22每类标准镜头重复和乱序定位像素完全相同',async({page},info)=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 const data=await ready(page),times=data.shots.filter(s=>!['real_media','ai_broll'].includes(s.kind)).map(s=>(s.start+s.end)/2);
 for(const t of times){
  await page.evaluate(t=>window.__player.seek(t),t);const a=await canvasPixels(page);
  await page.evaluate(t=>window.__player.seek(t),t);expect(await canvasPixels(page)).toEqual(a);
  await page.evaluate(()=>window.__player.seek(42));await page.evaluate(t=>window.__player.seek(t),t);expect(await canvasPixels(page)).toEqual(a);
  await info.attach(`标准画面-${t}`,{body:Buffer.from(a.split(',')[1],'base64'),contentType:'image/png'});
 }
 expect(errors).toEqual([]);
});

test('T22c整段镜头的厂房显隐固定且不被上边缘截断',async({page})=>{
 const data=await ready(page);
 for(const shot of data.shots.filter(s=>!['real_media','ai_broll','weld_macro'].includes(s.kind))){
  let initial;
  for(const f of [0,.125,.25,.5,.75,.875,.999]){
   await page.evaluate(t=>window.__player.seek(t),shot.start+(shot.end-shot.start)*f);
   const state=await page.evaluate(async()=>{
    const THREE=await import('/vendor/three/build/three.module.js');
    const {renderContext:ctx}=await import('/player/player.js');
    return ctx.yard.children.filter(n=>n.userData.building).map(n=>{
     if(n.visible){n.computeBoundingBox();const b=n.boundingBox.clone().applyMatrix4(n.matrixWorld);
      for(const x of [b.min.x,b.max.x])for(const y of [b.min.y,b.max.y])for(const z of [b.min.z,b.max.z]){
       const q=new THREE.Vector3(x,y,z).project(ctx.camera);if(Math.abs(q.y)>.94||Math.abs(q.x)>.97)throw new Error('厂房裁切');
      }}
     return [n.name,n.visible];
    });
   });
   initial??=state;expect(state).toEqual(initial);
  }
 }
});

test('T22门机受光面橙红、天空偏蓝且不过曝',async({page},info)=>{
 const data=await ready(page),shot=data.shots.find(s=>s.kind==='model_orbit');
 await page.evaluate(t=>window.__player.seek(t),(shot.start+shot.end)/2);
 const result=await page.locator('#scene').evaluate(async(canvas:HTMLCanvasElement)=>{
  const THREE=await import('/vendor/three/build/three.module.js');
  const {renderContext}=await import('/player/player.js');
  const camera=renderContext.camera;
  const c=document.createElement('canvas');c.width=1920;c.height=1080;const g=c.getContext('2d')!;g.drawImage(canvas,0,0);
  const pixels=g.getImageData(0,0,1920,1080).data;
  // 直接采样主梁前腹板内部世界坐标，不按目标色筛选，以免掩盖偏色。
  const samples:number[][]=[];
  for(let x=-48;x<=48;x+=1.25)for(const y of [40,41,42,43,44]){
   const q=new THREE.Vector3(x,y,4.505).project(camera),px=Math.round((q.x+1)*960),py=Math.round((1-q.y)*540);
   if(px<0||px>=1920||py<0||py>=1080)continue;
   const index=(py*1920+px)*4,r=pixels[index]/255,gr=pixels[index+1]/255,b=pixels[index+2]/255,max=Math.max(r,gr,b),min=Math.min(r,gr,b),d=max-min;
   const h=d===0?0:((max===r?(gr-b)/d:max===gr?(b-r)/d+2:(r-gr)/d+4)*60+360)%360;
   samples.push([h,max===0?0:d/max,max]);
  }
  const mean=(i:number)=>samples.reduce((sum,p)=>sum+p[i],0)/samples.length;
  return {count:samples.length,hue:mean(0),saturation:mean(1),clipped:samples.filter(p=>p[2]>.985).length/samples.length,sky:Array.from(pixels.slice((24*1920+24)*4,(24*1920+24)*4+3))};
 });
 await writeFile(info.outputPath('color.json'),JSON.stringify(result,null,2));
 await info.attach('颜色测量',{body:JSON.stringify(result),contentType:'application/json'});
 expect(result.count).toBeGreaterThan(250);expect(result.hue).toBeGreaterThanOrEqual(10);expect(result.hue).toBeLessThanOrEqual(25);expect(result.saturation).toBeGreaterThanOrEqual(.55);expect(result.clipped).toBeLessThan(.02);
 expect(result.sky[2]).toBeGreaterThan(result.sky[0]+24);
 expect(await page.evaluate(()=>(window.__player as any).metrics.sunSkyRatio)).toBeCloseTo(4,1);
});

test('T22混凝土大板细缝无密集高对比网格',async({page},info)=>{
 await ready(page);await page.evaluate(()=>window.__player.seek(7.5));
 const result=await page.evaluate(async()=>{
  const {concreteTextures}=await import('/player/materials.js'),{map}=concreteTextures(),canvas=map.image as HTMLCanvasElement;
  const p=canvas.getContext('2d')!.getImageData(0,0,2048,2048).data;
  const means=Array.from({length:2048},(_,x)=>{let sum=0;for(let y=0;y<2048;y++)sum+=p[(y*2048+x)*4];return sum/2048;});
  const jumps=means.slice(1).filter((v,i)=>Math.abs(v-means[i])>3).length;
  const deviation=Math.sqrt(means.reduce((sum,v)=>sum+(v-156)**2,0)/means.length);
  map.dispose();return {jumps,deviation};
 });
 await info.attach('地面纹理测量',{body:JSON.stringify(result),contentType:'application/json'});
 // 允许每12m一道细缝，不允许旧式每小格一条高对比线。
 expect(result.jumps).toBeLessThanOrEqual(8);expect(result.deviation).toBeGreaterThan(.3);expect(result.deviation).toBeLessThan(12);
 const ground=await page.locator('#scene').evaluate((canvas:HTMLCanvasElement)=>{const c=document.createElement('canvas');c.width=240;c.height=120;const g=c.getContext('2d')!;g.drawImage(canvas,280,930,240,120,0,0,240,120);const pixels=g.getImageData(0,0,240,120).data;const columns=Array.from({length:240},(_,x)=>{let sum=0;for(let y=0;y<120;y++)sum+=pixels[(y*240+x)*4];return sum/120;});const mean=[0,0,0];for(let i=0;i<pixels.length;i+=4)for(let c=0;c<3;c++)mean[c]+=pixels[i+c]/(240*120);return {jumps:columns.slice(1).filter((v,i)=>Math.abs(v-columns[i])>5).length,mean};});
 expect(ground.jumps,'实际地面不能出现密集高对比竖线').toBeLessThan(12);
 expect(Math.abs(ground.mean[0]-ground.mean[1]),'混凝土不能偏棕黄').toBeLessThan(18);
 expect(ground.mean[0]-ground.mean[2],'混凝土红蓝差不能过大').toBeLessThan(28);
 const screenshot=await canvasPixels(page);await info.attach('地面实际画面',{body:Buffer.from(screenshot.split(',')[1],'base64'),contentType:'image/png'});
});

test('T22标准与缺少写实帧的回退一致，草稿关闭AO和泛光',async({page})=>{
 await ready(page);await page.evaluate(()=>window.__player.seek(7.5));const standard=await canvasPixels(page);
 await ready(page,{mode:'photoreal',bg:true});await page.evaluate(()=>window.__player.seek(7.5));expect(await canvasPixels(page)).toEqual(standard);
 await expect(page.locator('#bg-frame')).toBeHidden();await expect(page.locator('#error')).toBeHidden();
 await page.route('**/missing-anchors.json',route=>route.fulfill({json:{frames:[]}}));
 await ready(page,{mode:'photoreal',bg:true});await page.evaluate(()=>window.__player.seek(7.5));expect(await canvasPixels(page)).toEqual(standard);
 await ready(page,{mode:'standard',bg:true});await page.evaluate(()=>window.__player.seek(7.5));expect(await canvasPixels(page)).toEqual(standard);
 await ready(page,{quality:'draft'});await page.evaluate(()=>window.__player.seek(7.5));
 expect(await page.evaluate(()=>(window.__player as any).metrics)).toMatchObject({quality:'draft',ao:false,bloom:false});
});

test('T22新模型楼房类比与焊缝微距往返正常',async({page})=>{
 const data=await ready(page,{building:true}),a=data.shots.find(s=>s.kind==='analogy'),w=data.shots.find(s=>s.kind==='weld_macro');
 const t=(a.start+a.end)/2;await page.evaluate(t=>window.__player.seek(t),t);const before=await canvasPixels(page);
 await expect(page.locator('.dimension-label')).toHaveCount(2);
 await page.evaluate(t=>window.__player.seek(t),(w.start+w.end)/2);await expect(page.locator('.weld-step-dimension')).toBeVisible();await expect(page.locator('#error')).toBeHidden();
 await page.evaluate(t=>window.__player.seek(t),t);expect(await canvasPixels(page)).toEqual(before);
});

test('T22本机1080p完整GPU单帧不超过120ms且GLB加载不超过1秒',async({page},info)=>{
 test.skip(process.env.KEPU_HARDWARE_LOOK!=='1','硬件性能验收使用 look.config.mjs，默认套件使用软件光栅化');
 const data=await ready(page),times=data.shots.filter(s=>!['real_media','ai_broll','weld_macro'].includes(s.kind)).map(s=>(s.start+s.end)/2);
 const timing=await page.evaluate(async times=>{
  const canvas=document.getElementById('scene') as HTMLCanvasElement,gl=canvas.getContext('webgl2')!,debug=gl.getExtension('WEBGL_debug_renderer_info');
  const device=debug?String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)):String(gl.getParameter(gl.RENDERER));
  const samples:number[]=[];
  for(const t of times){await window.__player.seek(t);gl.finish();for(let i=0;i<5;i++){const start=performance.now();await window.__player.seek(t+i/30);gl.finish();samples.push(performance.now()-start);}}
  return {device,samples,modelLoadMs:(window.__player as any).metrics.modelLoadMs};
 },times);
 await writeFile(info.outputPath('timing.json'),JSON.stringify(timing,null,2));
 await info.attach('完整GPU计时',{body:JSON.stringify(timing),contentType:'application/json'});
 expect(timing.device,'性能验收必须使用本机硬件GPU，请用 look.config.mjs').not.toMatch(/swiftshader|llvmpipe|software/i);
 expect(timing.modelLoadMs).toBeLessThanOrEqual(1000);expect(Math.max(...timing.samples)).toBeLessThanOrEqual(120);
});

test('T22整片标准模式输出50秒且总耗时不超过5分钟',async({},info)=>{
 test.skip(process.env.KEPU_LOOK_FULL_RENDER!=='1','整片耗时须在沙箱外显式运行');test.setTimeout(330000);
 // 与浏览器测试相同的新模型，通过独立临时HTTP服务供逐帧进程读取。
 const {createServer}=await import('node:http');const timeline=structuredClone(fixture);timeline.render_mode='standard';timeline.model.glb='/t22-crane.glb';timeline.model.rig.bbox_m={x:104,y:51,z:120};
 for(const asset of Object.values(timeline.assets) as any[])asset.url=new URL(asset.url,'http://127.0.0.1:8766/fixtures/timeline.json').href;
 if(timeline.audio)timeline.audio=new URL(timeline.audio,'http://127.0.0.1:8766/fixtures/timeline.json').href;
 const server=createServer((req,res)=>{res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Content-Type',req.url==='/t22-crane.glb'?'model/gltf-binary':'application/json');res.end(req.url==='/t22-crane.glb'?model:JSON.stringify(timeline));});
 await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));const address=server.address() as {port:number},out=path.resolve('test-results/T22-final/standard-full.mp4');
 const start=performance.now();
 try{
  const rendered=await exec(process.execPath,['render/render.mjs','--url',`http://127.0.0.1:8766/player/index.html?timeline=http://127.0.0.1:${address.port}/timeline.json`,'--out',out],{timeout:300000});
  expect(performance.now()-start).toBeLessThanOrEqual(300000);
  const probe=await exec(process.env.FFPROBE||'ffprobe',['-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=nb_read_frames','-of','json',out]);const frames=Number(JSON.parse(probe.stdout).streams[0].nb_read_frames);await writeFile(path.resolve('test-results/T22-final/full-render.json'),JSON.stringify({elapsedMs:performance.now()-start,frames,renderer:rendered.stdout.trim().split('\n').at(-1)},null,2));expect(frames).toBe(1500);
 }finally{await new Promise<void>(resolve=>server.close(()=>resolve()));}
});

async function projectionMeasurement(page:Page){
 await page.route('**/t22-mask-metrics.js',route=>route.fulfill({body:readMetrics,contentType:'text/javascript'}));
 return page.evaluate(async()=>{
  const THREE=await import('/vendor/three/build/three.module.js');
  const {renderContext:ctx}=await import('/player/player.js');
  const {measureProjection}=await import('/t22-mask-metrics.js');
  const canvas=document.getElementById('scene') as HTMLCanvasElement;
  const copy=document.createElement('canvas');copy.width=1920;copy.height=1080;
  const g=copy.getContext('2d')!;g.drawImage(canvas,0,0);
  const pixels=g.getImageData(0,0,1920,1080).data;
  // 从正在显示的同一场景和相机生成 ID mask，无重新猜测的相机，也无目标色筛选。
  const body=new Set();ctx.model.traverseVisible(n=>{
   if(!n.isMesh)return;
   for(let owner=n;owner;owner=owner.parent)if(['rail_left','rail_right'].includes(owner.name))return;
   body.add(n.uuid);
  });
  const originals=[];ctx.scene.traverse(n=>{if(n.isMesh)originals.push(n);});
  const scene=ctx.scene.clone(true),materials=[];let index=0;
  scene.background=new THREE.Color(0);scene.environment=null;scene.fog=null;
  scene.getObjectByName('day_sky').visible=false;
  scene.traverse(n=>{
   if(!n.isMesh)return;const original=originals[index++];
   const mapped=[].concat(original.material).map(m=>{
    const material=new THREE.MeshBasicMaterial({color:body.has(original.uuid)?m.name==='paint'?0xffffff:0xff0000:0x000000,side:m.side,fog:false,toneMapped:false});
    materials.push(material);return material;
   });n.material=Array.isArray(original.material)?mapped:mapped[0];
  });
  const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true});renderer.setSize(1920,1080);renderer.setPixelRatio(1);
  try{
   renderer.render(scene,ctx.camera.clone());
   const maskCanvas=document.createElement('canvas');maskCanvas.width=1920;maskCanvas.height=1080;
   const mg=maskCanvas.getContext('2d')!;mg.drawImage(renderer.domElement,0,0);
   const mask=mg.getImageData(0,0,1920,1080).data;
   const gl=ctx.renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');
   return {metrics:measureProjection(pixels,mask,1920,1080),mask:maskCanvas.toDataURL('image/png'),canvas:copy.toDataURL('image/png'),
    device:ext?String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)):String(gl.getParameter(gl.RENDERER))};
  }finally{materials.forEach(m=>m.dispose());renderer.dispose();renderer.forceContextLoss();}
 });
}
const readMetrics=await readFile(new URL('./projection-metrics.mjs',import.meta.url),'utf8');

for(const quality of ['standard','draft'])test(`T22b独立投影mask亮度与橙红色及逐镜头截图-${quality}`,async({page},info)=>{
 test.setTimeout(300000);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 const data=await ready(page,{quality,building:true});
 const shots=data.shots.filter(s=>!['real_media','ai_broll'].includes(s.kind)&&(quality==='standard'||s.kind==='model_orbit'));
 const directory=path.resolve('test-results/T22c-shots',process.env.KEPU_HARDWARE_LOOK==='1'?'hardware':'software',quality);
 await mkdir(directory,{recursive:true});
 for(const shot of shots)for(const fraction of shot.kind==='outro'?[.5,.85]:[.5]){
  await page.evaluate(t=>window.__player.seek(t),shot.start+(shot.end-shot.start)*fraction);
  const name=`${shot.id}-${shot.kind}-${fraction}`,file=path.join(directory,name);
  await page.locator('#stage').screenshot({path:`${file}.png`});
  if(shot.kind==='weld_macro')continue;
  const result=await projectionMeasurement(page),m=result.metrics;
  if(process.env.KEPU_SOFTWARE_LOOK==='1')expect.soft(result.device,'必须实际使用软件光栅化').toMatch(/swiftshader|llvmpipe|software/i);
  await writeFile(`${file}-mask.png`,Buffer.from(result.mask.split(',')[1],'base64'));
  await writeFile(`${file}-canvas.png`,Buffer.from(result.canvas.split(',')[1],'base64'));
  await writeFile(`${file}.json`,JSON.stringify({device:result.device,...m},null,2));
  await info.attach(name,{body:JSON.stringify({device:result.device,...m}),contentType:'application/json'});
  expect.soft(m.count,`${name} 设备投影不得为空`).toBeGreaterThanOrEqual(5000);
  expect.soft(m.paintCount,`${name} 漆面投影覆盖不足`).toBeGreaterThanOrEqual(3000);
  expect.soft(m.brightness,`${name} 整机平均亮度`).toBeGreaterThanOrEqual(.25);
  expect.soft(m.paintBrightness,`${name} 漆面平均亮度`).toBeGreaterThanOrEqual(.25);
  expect.soft(m.hue,`${name} 漆面色相下界`).toBeGreaterThanOrEqual(10);
  expect.soft(m.hue,`${name} 漆面色相上界`).toBeLessThanOrEqual(25);
  expect.soft(m.saturation,`${name} 漆面饱和度`).toBeGreaterThanOrEqual(.55);
  expect.soft(m.contrast,`${name} 受光背光明暗差`).toBeGreaterThan(.04);
  expect.soft(m.clipped,`${name} 漆面过曝占比`).toBeLessThan(.02);
  if(shot.kind==='model_orbit'){
   // T23以透视焦点安全区替代旧固定全景占宽和右上数字卡限制。
   const framing=await page.evaluate(async()=>{const THREE=await import('/vendor/three/build/three.module.js');const {renderContext:ctx}=await import('/player/player.js');const p=new THREE.Box3().setFromObject(ctx.model.getObjectByName('girder')).getCenter(new THREE.Vector3()).project(ctx.camera);return {perspective:ctx.camera.projectionMatrix.elements[15]===0,x:p.x,y:p.y};});
   expect(framing.perspective).toBe(true);expect(Math.abs(framing.x)).toBeLessThan(.8);expect(Math.abs(framing.y)).toBeLessThan(.8);
  }
 }
 expect(errors).toEqual([]);
});

const lightingMetrics=await readFile(new URL('./lighting-metrics.mjs',import.meta.url),'utf8');
test('T22c硬件朝阳背阳光比诊断和地面投影比',async({page},info)=>{
 test.skip(process.env.KEPU_HARDWARE_LOOK!=='1','亮度比由硬件GPU验收');
 test.setTimeout(180000);
 const data=await ready(page),shot=data.shots.find(s=>s.kind==='model_orbit');
 await page.evaluate(t=>window.__player.seek(t),(shot.start+shot.end)/2);
 await page.route('**/t22-lighting-metrics.js',r=>r.fulfill({body:lightingMetrics,contentType:'text/javascript'}));
 const result=await page.evaluate(async()=>{
  const THREE=await import('/vendor/three/build/three.module.js');
  const {renderContext:ctx}=await import('/player/player.js');
  const {SUN_DIRECTION}=await import('/player/pipeline.js');
  // 成片机位面向太阳，背阳mask为空；诊断用固定双面观察机位，不改变成片相机。
  const {cameraArc}=await import('/player/camera.js');
  cameraArc(ctx,{angle:24,elevation:8,distance:190,target:new THREE.Vector3(0,26,0),fov:40});
  const diagnosticShot=ctx.timeline.shots.find(s=>s.kind==='model_orbit');
  ctx.pipeline.render({shot:diagnosticShot,bounds:ctx.plans.get(diagnosticShot.id).bounds,scale:ctx.size.x});
  const {measureLighting,luminance}=await import('/t22-lighting-metrics.js');
  const gl=ctx.renderer.getContext(),debug=gl.getExtension('WEBGL_debug_renderer_info');
  const device=debug?String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)):String(gl.getParameter(gl.RENDERER));
  const w=1920,h=1080,canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
  const g=canvas.getContext('2d')!;g.drawImage(ctx.renderer.domElement,0,0);
  const pixels=g.getImageData(0,0,w,h).data;
  const clone=ctx.scene.clone(true),materials=[];
  clone.background=new THREE.Color(0);clone.environment=null;clone.fog=null;clone.getObjectByName('day_sky').visible=false;
  clone.traverse(n=>{if(!n.isMesh)return;
   const original=[].concat(n.material),paint=original.some(m=>m.name==='paint');
   const m=paint?new THREE.ShaderMaterial({uniforms:{sun:{value:SUN_DIRECTION}},
    vertexShader:'varying vec3 world;void main(){world=(modelMatrix*vec4(position,1.)).xyz;gl_Position=projectionMatrix*viewMatrix*vec4(world,1.);}',
    fragmentShader:'uniform vec3 sun;varying vec3 world;void main(){vec3 n=normalize(cross(dFdx(world),dFdy(world)));n*=gl_FrontFacing?1.:-1.;float d=dot(n,sun);gl_FragColor=vec4(d>.3?vec3(1,0,0):d<-.3?vec3(0,1,0):vec3(0),1);}',
    side:original[0].side}):new THREE.MeshBasicMaterial({color:0,side:original[0].side});
   materials.push(m);n.material=m;
  });
  const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true});renderer.setSize(w,h);
  let face,mask;
  try{renderer.render(clone,ctx.camera.clone());g.drawImage(renderer.domElement,0,0);mask=canvas.toDataURL();face=measureLighting(pixels,g.getImageData(0,0,w,h).data,w,h);}
  finally{materials.forEach(m=>m.dispose());renderer.dispose();renderer.forceContextLoss();}
  // 在真实地面取固定世界网格，几何射线判定是否被门机遮住太阳；不按图像深浅选样。
  const meshes=[];ctx.model.traverseVisible(n=>{if(n.isMesh&&!n.userData.noCastShadow)meshes.push(n);});
  const ray=new THREE.Raycaster(),viewRay=new THREE.Raycaster(),samples=[];
  for(let x=-80;x<=130;x+=4)for(let z=-110;z<=40;z+=4){
   const point=new THREE.Vector3(x,-.079,z),q=point.clone().project(ctx.camera);
   if(Math.abs(q.x)>.9||Math.abs(q.y)>.85)continue;
   viewRay.setFromCamera(new THREE.Vector2(q.x,q.y),ctx.camera);
   const hits=viewRay.intersectObjects(ctx.scene.children,true).filter(h=>h.object.visible&&h.object.name!=='day_sky');
   if(hits[0]?.object!==ctx.floor)continue;
   ray.set(point.clone().add(new THREE.Vector3(0,.02,0)),SUN_DIRECTION);
   if(!ray.intersectObjects(meshes,false).length)continue;
   const px=Math.round((q.x+1)*w/2),py=Math.round((1-q.y)*h/2),i=(py*w+px)*4;
   samples.push({i,shadow:luminance(pixels,i)});
  }
  // 同位置无投影参考，排除板块底色、透视、雾与暗角造成的虚假比值。
  const cast=meshes.map(n=>n.castShadow);
  try{
   meshes.forEach(n=>n.castShadow=false);ctx.pipeline.sun.shadow.needsUpdate=true;
   const current=ctx.timeline.shots.find(s=>s.kind==='model_orbit');
   ctx.pipeline.render({shot:current,bounds:ctx.plans.get(current.id).bounds,scale:ctx.size.x});
   g.drawImage(ctx.renderer.domElement,0,0);const lit=g.getImageData(0,0,w,h).data;
   const shadow=samples.reduce((s,p)=>s+p.shadow,0)/samples.length;
   const reference=samples.reduce((s,p)=>s+luminance(lit,p.i),0)/samples.length;
   return {device,face,ground:{count:samples.length,shadow,lit:reference,ratio:shadow/reference},mask};
  }finally{meshes.forEach((n,i)=>n.castShadow=cast[i]);ctx.pipeline.sun.shadow.needsUpdate=true;}
 });
 await info.attach('受光分区mask',{body:Buffer.from(result.mask.split(',')[1],'base64'),contentType:'image/png'});
 await writeFile(info.outputPath('lighting.json'),JSON.stringify({view:'固定双面诊断机位；成片机位背阳mask为空',device:result.device,face:result.face,ground:result.ground},null,2));
 await info.attach('实际画面光比',{body:JSON.stringify({view:'固定双面诊断机位；成片机位背阳mask为空',device:result.device,face:result.face,ground:result.ground}),contentType:'application/json'});
 expect(result.device,'亮度比验收必须使用硬件GPU').not.toMatch(/swiftshader|llvmpipe|software/i);
 expect(result.face.sunCount).toBeGreaterThan(100);expect(result.face.shadeCount).toBeGreaterThan(100);
 // 用户于 2026-11-10 选择自然光候选：gamma / linear 朝背阳比仅诊断，观感由人工验收。
 for(const metric of ['sun','shade','ratio','linearSun','linearShade','linearRatio']){
  expect(Number.isFinite(result.face[metric]),`朝背阳诊断 ${metric} 必须为有限值`).toBe(true);
 }
 expect(result.ground.count).toBeGreaterThan(12);
 expect(result.ground.ratio,'投影/同位置受光地面 sRGB 亮度比').toBeLessThanOrEqual(.55);
});
