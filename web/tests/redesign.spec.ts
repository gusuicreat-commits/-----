import {test,expect} from '@playwright/test';
import {readFile,mkdir,mkdtemp,rm,writeFile} from 'node:fs/promises';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {tmpdir} from 'node:os';
import path from 'node:path';
const exec=promisify(execFile);
const fixture=JSON.parse(await readFile(new URL('./fixtures/visual-redesign-timeline.json',import.meta.url),'utf8'));
test('T23视觉改版真实硬件样片',async({page})=>{
 test.setTimeout(process.env.KEPU_T23_FULL_RENDER==='1'?330000:120000);
 const dir=await mkdtemp(path.join(tmpdir(),'kepu-t23-'));
 try{
  const file=path.join(dir,'crane.glb');
  await exec(path.resolve('../backend/.venv/bin/python'),['-c',`from pathlib import Path\nfrom app.model3d.parametric import build_parametric\nimport sys\nbuild_parametric({'F_girder_length':104,'F_overall_height':51,'F_span':88,'F_wheel_count':64},Path(sys.argv[1]))`,file],{cwd:path.resolve('../backend')});
  const bytes=await readFile(file),timeline=structuredClone(fixture);timeline.render_mode='standard';timeline.model.glb='/fixtures/t23-crane.glb';timeline.model.rig.bbox_m={x:104,y:51,z:120};
  await page.route('**/t23-crane.glb',r=>r.fulfill({body:bytes,contentType:'model/gltf-binary'}));
  await page.route('**/t23-timeline.json',r=>r.fulfill({json:timeline}));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/player/index.html?timeline=/fixtures/t23-timeline.json&mode=render');await page.evaluate(()=>window.__player.ready);
  const device=await page.evaluate(async()=>{const {renderContext:ctx}=await import('/player/player.js');const gl=ctx.renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');return String(gl.getParameter(ext?ext.UNMASKED_RENDERER_WEBGL:gl.RENDERER));});
  expect(device).not.toMatch(/swiftshader|llvmpipe|software/i);
  const out=path.resolve('../outputs/visual-redesign-v1/after/final');await mkdir(out,{recursive:true});
  const provenance=[];
  for(const [kind,t] of [['title',2.5],['model_orbit',7.5],['motion',17.5],['analogy',12.5],['exploded',22.5],['data_card',27.5],['outro',47.5]] as const){
   await page.evaluate(t=>window.__player.seek(t),t);await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));const screenshot=await page.locator('#stage').screenshot({path:path.join(out,`${kind}.png`)});
   const whitePixels=await page.evaluate(async encoded=>{const image=new Image();image.src='data:image/png;base64,'+encoded;await image.decode();const c=document.createElement('canvas');c.width=1920;c.height=1080;const g=c.getContext('2d');g.drawImage(image,0,0);const p=g.getImageData(64,35,250,40).data;let white=0;for(let i=0;i<p.length;i+=4)if(p[i]>215&&p[i+1]>215&&p[i+2]>215)white++;return white;},screenshot.toString('base64'));
   provenance.push({kind,whitePixels});expect(whitePixels,`${kind} 实际截图左上来源白字`).toBeGreaterThan(120);
   const first=await page.locator('#scene').evaluate((c:HTMLCanvasElement)=>c.toDataURL());
   await page.evaluate(()=>window.__player.seek(42.5));await page.evaluate(t=>window.__player.seek(t),t);
   expect(await page.locator('#scene').evaluate((c:HTMLCanvasElement)=>c.toDataURL())).toBe(first);
   await expect(page.locator('#badge')).toContainText('参数化重建');await expect(page.locator('#badge')).toBeVisible();

  }
  await writeFile(path.join(out,'provenance.json'),JSON.stringify({device,provenance},null,2));
  // 四项参数沿单列排版，完整来源不得与字幕重叠。
  timeline.shots.find(s=>s.kind==='data_card').params.facts=['F_rated_load','F_span','F_overall_height','F_girder_length'];
  await page.goto('/player/index.html?timeline=/fixtures/t23-timeline.json&mode=render');await page.evaluate(()=>window.__player.ready);await page.evaluate(()=>window.__player.seek(27.5));
  const panel=await page.locator('.data-panel').boundingBox(),caption=await page.locator('#caption').boundingBox();expect(panel.y+panel.height).toBeLessThan(caption.y-12);await expect(page.locator('.data-panel .source')).toHaveCount(4);
  await page.locator('#stage').screenshot({path:path.join(out,'data_card-four.png')});
  expect(errors).toEqual([]);
  if(process.env.KEPU_T23_FULL_RENDER==='1'){
   const {createServer}=await import('node:http');const full=structuredClone(fixture);full.render_mode='standard';full.model.glb='/t23-crane.glb';full.model.rig.bbox_m={x:104,y:51,z:120};
   for(const a of Object.values(full.assets) as any[])a.url=new URL(a.url,'http://127.0.0.1:8766/fixtures/timeline.json').href;
   if(full.audio)full.audio=new URL(full.audio,'http://127.0.0.1:8766/fixtures/timeline.json').href;
   const server=createServer((req,res)=>{res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Content-Type',req.url==='/t23-crane.glb'?'model/gltf-binary':'application/json');res.end(req.url==='/t23-crane.glb'?bytes:JSON.stringify(full));});
   await new Promise<void>(resolve=>server.listen(0,'127.0.0.1',resolve));const address=server.address() as {port:number},file=path.resolve('../outputs/visual-redesign-v1/after/visual-preview.mp4'),start=performance.now();
   try{const rendered=await exec(process.execPath,['render/render.mjs','--url',`http://127.0.0.1:8766/player/index.html?timeline=http://127.0.0.1:${address.port}/timeline.json`,'--out',file],{timeout:300000});
    const elapsedMs=performance.now()-start,probe=await exec('ffprobe',['-v','error','-count_frames','-show_entries','stream=codec_type,width,height,nb_read_frames,duration','-of','json',file]);const streams=JSON.parse(probe.stdout).streams;
    await writeFile(path.resolve('../outputs/visual-redesign-v1/after/render-result.json'),JSON.stringify({elapsedMs,streams,render:rendered.stdout.trim().split('\n').at(-1)},null,2));expect(elapsedMs).toBeLessThanOrEqual(300000);expect(Number(streams.find(s=>s.codec_type==='video').nb_read_frames)).toBe(1500);
   }finally{await new Promise<void>(resolve=>server.close(()=>resolve()));}
  }
 }finally{await rm(dir,{recursive:true,force:true});}
});
