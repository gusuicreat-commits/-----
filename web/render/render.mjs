import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
const args=process.argv.slice(2),get=(key,fallback)=>{const i=args.indexOf(key);return i<0?fallback:args[i+1];};
let browser,encoder;
async function main(){
 const input=get('--url'),out=get('--out'),framesAt=get('--frames-at'),framesDir=get('--frames-dir'),fps=Number(get('--fps','30')),from=Number(get('--from','0'));
 if(!input || (!framesAt&&!out) || (framesAt&&!framesDir))throw new Error('需要 --url 和 --out，或 --frames-at 与 --frames-dir');
 if(!(fps>0&&fps<=120)||!Number.isFinite(from)||from<0)throw new Error('帧率或起始时间无效');
 const url=new URL(input);url.searchParams.set('mode','render');
 let page,lastError;
 const gpuArgs=process.platform==='darwin'?['--use-angle=metal']:[];
 for(const flags of [gpuArgs,['--use-angle=swiftshader','--enable-unsafe-swiftshader']]){try{browser=await chromium.launch({headless:true,executablePath:process.env.KEPU_CHROMIUM_PATH,args:flags});page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});await page.goto(url.href,{waitUntil:'load'});await page.waitForFunction(()=>window.__player,{timeout:20000});await page.evaluate(()=>Promise.race([window.__player.ready,new Promise((_,reject)=>setTimeout(()=>reject(new Error('播放器准备超时')),30000))]));break;}catch(e){lastError=e;await browser?.close();browser=null;}}
 if(!browser)throw lastError;
 const duration=await page.evaluate(()=>window.__player.duration),to=Number(get('--to',String(duration)));
 if(!Number.isFinite(to)||to>duration||from>=to)throw new Error('渲染区间超出时间线或为空');
 const times=framesAt?framesAt.split(',').map(Number):Array.from({length:Math.ceil((to-from)*fps-1e-8)},(_,i)=>from+i/fps);
 if(times.some(t=>!Number.isFinite(t)||t<0||t>duration))throw new Error('质检帧时间超出时间线');
 const start=performance.now();let encoderDone,encoderFailure,stderr='';
 if(framesAt)await mkdir(framesDir,{recursive:true});else{
  await mkdir(path.dirname(path.resolve(out)),{recursive:true});
  encoder=spawn(process.env.FFMPEG||'ffmpeg',['-hide_banner','-loglevel','error','-y','-f','image2pipe','-c:v','mjpeg','-r',String(fps),'-i','-','-an','-c:v','libx264','-pix_fmt','yuv420p','-crf','18','-preset','medium','-movflags','+faststart',out],{stdio:['pipe','ignore','pipe']});
  encoder.stderr.on('data',d=>{stderr=(stderr+d.toString()).slice(-4000);});encoder.stdin.on('error',e=>{encoderFailure=e;});
  encoderDone=new Promise(resolve=>{encoder.on('error',e=>{encoderFailure=e;resolve();});encoder.on('close',code=>{if(code!==0)encoderFailure=new Error(`视频编码失败：${stderr||code}`);resolve();});});
 }
 for(let i=0;i<times.length;i++){
  if(encoderFailure)throw encoderFailure;
  await page.evaluate(t=>window.__player.seek(t),times[i]);
  if(framesAt)await page.screenshot({type:'png',path:path.join(framesDir,`frame-${String(i+1).padStart(3,'0')}-${times[i].toFixed(3)}.png`)});
  else {const buffer=await page.screenshot({type:'jpeg',quality:92});await new Promise((resolve,reject)=>encoder.stdin.write(buffer,e=>e?reject(e):resolve()));}
  if((i+1)%30===0)console.log(JSON.stringify({frame:i+1,total:times.length,fps_render:Number(((i+1)*1000/(performance.now()-start)).toFixed(2))}));
 }
 if(encoder){encoder.stdin.end();await encoderDone;if(encoderFailure)throw encoderFailure;}
 console.log(JSON.stringify({done:true,out:framesAt?path.resolve(framesDir):path.resolve(out),seconds:Number(((performance.now()-start)/1000).toFixed(2))}));
}
try{await main();}catch(e){console.error(JSON.stringify({error:`渲染失败：${e.message}`}));process.exitCode=1;}finally{if(encoder&&!encoder.killed)encoder.kill();await browser?.close();}
