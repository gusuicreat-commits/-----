import {test,expect} from '@playwright/test';
async function mock(page,{configured=true,ready=false,shotCount=2}={}) {
 let state:any = {state:ready?'preview_ready':'idle',current:ready,can_produce:ready,can_download:false,plan_revision:ready?'revision-a':null,preview:ready?{timeline_url:'/files/P1/preview-timeline.json',keyframes_status:'realtime'}:null};
 const calls:any[]=[]; let failPreview=false;
 const shots=[{id:'S1',kind:'title',duration_s:5,narration:'看懂设备的第一步',fact_refs:['F_length']},{id:'S2',kind:'model_orbit',duration_s:5,narration:'有依据的结构讲解',fact_refs:['F_length']}];
 for(let i=shots.length;i<shotCount;i++) shots.push({id:`S${i+1}`,kind:'model_orbit',duration_s:5,narration:`有依据的第${i+1}镜讲解`,fact_refs:['F_length']});
 await page.route('**/api/**',async r=>{const u=new URL(r.request().url()),method=r.request().method(),body=method==='GET'?null:r.request().headers()['content-type']?.includes('application/json')?r.request().postDataJSON():null;calls.push({path:u.pathname,search:u.search,method,body});let result:any={};let status=200;
 if(u.pathname==='/api/workflow/capabilities') result={provider:{configured,mode:'live'},engines:[{id:'threejs',available:true},{id:'blender',available:true}]};
 else if(u.pathname==='/api/demo/seed') result={id:'D1',name:'起重机示例（模拟）'};
 else if(u.pathname==='/api/projects') result={id:'P1',name:'测试空白项目（模拟）'};
 else if(u.pathname.endsWith('/workflow/brief')) result=state;
 else if(u.pathname.endsWith('/workflow/preview')) {if(failPreview){status=503;result={error:'模拟模型服务暂时不可用，请重试'};failPreview=false;}else {state={state:'preview_ready',current:true,can_produce:true,can_download:false,plan_revision:'revision-a',preview:{timeline_url:'/files/P1/preview-timeline.json',keyframes_status:'realtime'}};result=state;}}
 else if(u.pathname.endsWith('/workflow/produce')) {state={...state,state:'production_done',can_produce:false,can_download:true,exports:{mp4:'/files/P1/final.mp4',project:'/files/P1/project.zip',sources:'/files/P1/report.html'}};result=state;}
 else if(u.pathname.endsWith('/workflow'))result=state;
 else if(u.pathname.endsWith('/shotlist'))result={shots};
 else if(u.pathname==='/api/projects/D1')result={id:'D1',name:'起重机示例（模拟）',brief:'用示例资料讲解起重机',target_s:40};
 else if(u.pathname==='/api/projects/P1')result={id:'P1',name:'测试项目（模拟）',brief:'给公众解释设备结构',target_s:30};
 else if(u.pathname.endsWith('/docs'))result={name:'test.pdf'};
 else if(u.pathname.endsWith('/revise')){state={...state,state:'stale',current:false,can_produce:false,can_download:false,exports:{}};result={};}
 await r.fulfill({status,contentType:'application/json',body:JSON.stringify(result)});
 });
 await page.route('**/files/P1/preview-timeline.json',r=>r.fulfill({contentType:'application/json',body:JSON.stringify({duration_s:10,shots:shots.map((s,i)=>({...s,start:i*5,end:(i+1)*5}))})}));
 await page.route('**/player/index.html?**',r=>r.fulfill({contentType:'text/html',body:'<html><body>模拟构图播放器<script>window.__player={ready:Promise.resolve(),seek:async(t)=>{window.lastSeek=t}}</script></body></html>'}));
 return {calls,keyframes:(frames)=>{state={...state,preview:{...state.preview,keyframes:frames}};},fail:()=>{failPreview=true;}};
}
test('mock: 空白创建、资料上传、独立引擎内容选择与模型门槛',async({page})=>{
 const m=await mock(page,{configured:false});await page.goto('/create.html');
 await expect(page.locator('#files')).toBeDisabled();await page.locator('#project-name').fill('我的设备');await page.locator('#create-project').click();await expect(page.locator('#files')).toBeEnabled();
 await page.locator('#files').setInputFiles({name:'test.pdf',mimeType:'application/pdf',buffer:Buffer.from('%PDF mock')});await expect(page.locator('#file-list')).toContainText('已上传');
 await page.locator('[data-panel="1"] [data-next="2"]').click();await page.locator('#brief').fill('讲给公众听，介绍设备结构');await page.locator('[data-panel="2"] [data-next="3"]').click();await page.locator('[data-engine="blender"]').click();await page.locator('[data-content="structure"]').click();await page.locator('[data-panel="3"] [data-next="4"]').click();
 await expect(page.locator('#brief-summary')).toContainText('精细制作');await expect(page.locator('#brief-summary')).toContainText('结构');await expect(page.locator('#preview-plan')).toBeDisabled();await expect(page.locator('#capabilities')).toContainText('AI 导演尚未就绪');expect(m.calls.find(c=>c.path.endsWith('/docs')).search).toBe('?sync=1');expect(m.calls.some(c=>c.path.endsWith('/run'))).toBeFalsy();
});
test('mock: 按方案版本制作，镜头可定位，编辑立即隐藏旧导出',async({page})=>{
 const m=await mock(page,{ready:true});await page.goto('/create.html?project=P1');await expect(page.locator('#produce')).toBeEnabled();await expect(page.locator('#workflow-player')).toHaveAttribute('data-ready','true');
 await page.locator('[data-shot="S2"]').click();await expect.poll(()=>page.locator('#workflow-player').evaluate((f:any)=>f.contentWindow.lastSeek)).toBe(5.05);
 await page.screenshot({path:'test-results/T27-workflow/preview-desktop.png',fullPage:true}); await page.locator('#produce').click();await page.locator('#refresh-result').click();await expect(page.locator('#final-video video')).toBeVisible();await expect(page.locator('#downloads a')).toHaveCount(3);expect(m.calls.find(c=>c.path.endsWith('/workflow/produce')).body).toEqual({plan_revision:'revision-a'});
 await page.locator('[data-step="2"]').click();await page.locator('#brief').fill('修改后创意');await expect(page.locator('#downloads a')).toHaveCount(0);await expect(page.locator('#final-video video')).toHaveCount(0);await expect(page.locator('#produce')).toBeDisabled();
 await page.screenshot({path:'test-results/T27-workflow/desktop.png',fullPage:true});
});
test('mock: 模型失败可恢复，镜头修改后只校验更新预览',async({page})=>{
 const m=await mock(page,{ready:true});await page.goto('/create.html?project=P1');await expect(page.locator('#produce')).toBeEnabled();await page.locator('#instruction').fill('台词更口语');await page.locator('#revise').click();await expect(page.locator('#produce')).toBeDisabled();
 m.fail();await page.locator('#repreview').click();await expect(page.locator('#notice')).toContainText('模拟模型服务暂时不可用');await expect(page.locator('#repreview')).toBeEnabled();await page.locator('#repreview').click();await page.locator('[data-step="6"]').click();await page.locator('#refresh-result').click();
 await page.locator('[data-step="5"]').click();await expect(page.locator('#produce')).toBeEnabled();expect(m.calls.filter(c=>c.path.endsWith('/workflow/preview')).every(c=>c.body.replan===false)).toBeTruthy();expect(m.calls.some(c=>c.path.endsWith('/workflow/produce'))).toBeFalsy();
});
test('mock: 手机六步布局无横向溢出',async({page})=>{
 await page.setViewportSize({width:390,height:844});await mock(page,{ready:true});await page.goto('/create.html?project=P1');await expect(page.locator('#shots')).toBeVisible();
 for(const step of [1,2,3,4,5,6]){await page.locator(`[data-step="${step}"]`).click();await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();}
 await page.screenshot({path:'test-results/T27-workflow/mobile.png',fullPage:true});
});

test('mock: 创意修改重新编排，预览不触发完整制作',async({page})=>{
 const m=await mock(page,{ready:true});await page.goto('/create.html?project=P1');await expect(page.locator('#produce')).toBeEnabled();await page.locator('[data-step="2"]').click();await page.locator('#brief').fill('重新用尺度比较引入故事');await page.locator('[data-step="5"]').click();await page.locator('#repreview').click();await expect(page.locator('#produce')).toBeEnabled();expect(m.calls.find(c=>c.path.endsWith('/workflow/preview')).body).toEqual({replan:true});expect(m.calls.some(c=>c.path.endsWith('/workflow/produce')||c.path.endsWith('/run'))).toBeFalsy();
});

test('mock: 起重机示例创建独立项目，40秒可保存',async({page})=>{
 const m=await mock(page);await page.goto('/create.html?project=P1');await expect(page.locator('#project-name')).toHaveValue('测试项目（模拟）');await page.locator('#seed-example').click();await expect(page).toHaveURL(/project=D1&example=crane/);await expect(page.locator('#example-notice')).toContainText('示例技术参数表');await expect(page.locator('#project-name')).toHaveValue('起重机示例（模拟）');await page.locator('[data-step="2"]').click();await expect(page.locator('#duration')).toHaveValue('40');await page.locator('[data-step="4"]').click();await page.locator('#preview-plan').click();await expect.poll(()=>m.calls.some(c=>c.path==='/api/projects/D1/workflow/brief')).toBeTruthy();expect(m.calls.find(c=>c.path==='/api/projects/D1/workflow/brief').body.target_s).toBe(40);expect(m.calls.some(c=>c.method!=='GET'&&c.path.startsWith('/api/projects/P1/'))).toBeFalsy();
});
test('mock: 精细关键帧与来源素材按实际引擎标注',async({page})=>{
 const m=await mock(page,{ready:true});m.keyframes([{shot:'S1',engine:'source',kind:'real_photo',url:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E'},{shot:'S2',engine:'blender',kind:'model_orbit',url:'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg"/%3E'}]);await page.goto('/create.html?project=P1');await expect(page.locator('#shot-detail')).toContainText('实拍图片素材');await expect(page.locator('#shot-detail')).not.toContainText('Blender');await expect(page.locator('[data-shot="S1"] img')).toHaveAttribute('alt','镜头 1 实拍图片素材');await page.locator('[data-shot="S2"]').click();await expect(page.locator('#shot-detail')).toContainText('Blender 精细关键帧');
});

test('mock: 八镜预览在390px内布局，时间轴内部可滚动并选择末镜',async({page})=>{
 await page.setViewportSize({width:390,height:844});await mock(page,{ready:true,shotCount:8});await page.goto('/create.html?project=P1');await expect(page.locator('#shots button')).toHaveCount(8);await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
 const timeline=page.locator('#shots');expect(await timeline.evaluate(el=>el.scrollWidth>el.clientWidth)).toBeTruthy();await timeline.evaluate(el=>{el.scrollLeft=el.scrollWidth;});expect(await timeline.evaluate(el=>el.scrollLeft)).toBeGreaterThan(0);await page.locator('[data-shot="S8"]').click();await expect(page.locator('#shot-position')).toHaveText('镜头 8 / 8');await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
});
