// Run against a completed local acceptance project; never starts a render.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
const base=process.env.KEPU_ACCEPT_BASE || 'http://127.0.0.1:8047';
const pid=process.env.KEPU_ACCEPT_PID;
if(!pid)throw new Error('Set KEPU_ACCEPT_PID to the completed example project');
const api=async(path,body)=>{
 const response=await fetch(`${base}/api/projects/${pid}${path}`,body?{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});
 assert(response.ok,await response.clone().text());return response.json();
};
const before=await api('');assert.equal(before.scale_film_ready,true);
const browser=await chromium.launch({headless:true,executablePath:process.env.KEPU_CHROMIUM_PATH});
const out='test-results/T25-scale-film';mkdirSync(out,{recursive:true});
let changed=false;
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto(base);await page.locator('#project-select').selectOption(pid);
 await page.locator('#scale-film-preview').waitFor({state:'visible'});
 await page.waitForFunction(()=>document.querySelector('#scale-film-preview')?.readyState>=1);
 const media=await page.locator('#scale-film-preview').evaluate(v=>({duration:v.duration,width:v.videoWidth,height:v.videoHeight}));
 assert.equal(media.duration,15);assert.equal(media.width,1920);assert.equal(media.height,1080);
 assert.equal(await page.locator('#player-frame').count(),0);
 await page.locator('[data-shot="S2"]').click();
 await page.waitForFunction(()=>{const v=document.querySelector('#scale-film-preview');return v.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-4.6)<.1;});
 await page.screenshot({path:`${out}/actual-film.png`});
 await page.getByRole('button',{name:'讲解方式',exact:true}).click();
 await page.getByLabel('目标时长（秒）').fill('20');
 changed=true;
 await page.getByRole('button',{name:'保存讲解方式',exact:true}).click();
 await page.locator('#director-settings').waitFor({state:'hidden'});
 assert.equal((await api('')).scale_film_ready,false);
 await page.locator('#scale-film-preview').waitFor({state:'hidden'});
 await page.waitForFunction(()=>document.querySelectorAll('#film-links a').length===0);
 await page.reload();await page.getByText('参数或分镜已有变化，需重新生成当前版本；旧片不会作为新结果展示。',{exact:true}).waitFor();
 assert.equal(await page.locator('#scale-film-preview').count(),0);
 assert.equal(await page.locator('#open-film').isDisabled(),true);
 assert.equal(await page.locator('#film-links a').count(),0);
 await page.screenshot({path:`${out}/stale-film-hidden.png`});
 await api('/settings',{target_s:before.target_s});changed=false;
 assert.equal((await api('')).scale_film_ready,true);
 await page.reload();await page.locator('#scale-film-preview').waitFor({state:'visible'});
 await page.setViewportSize({width:390,height:844});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 await page.locator('#scale-film-preview').evaluate(v=>{v.currentTime=6;});
 await page.waitForFunction(()=>{const v=document.querySelector('#scale-film-preview');return v.readyState>=2&&!v.seeking&&Math.abs(v.currentTime-6)<.1;});
 await page.screenshot({path:`${out}/mobile-final.png`,fullPage:true});
 writeFileSync(`${out}/actual-film-check.json`,JSON.stringify({pid,media,actualNativeVideo:true,shotSeek:true,staleAfterTargetChange:true,staleVideoAndDownloadHidden:true,originalTargetRestored:true,mobileNoOverflow:true},null,2));
 console.log('Actual final MP4 preview, shot seek, stale-output hiding, restoration and mobile width passed.');
}finally{
 if(changed)await api('/settings',{target_s:before.target_s});
 await browser.close();
}
