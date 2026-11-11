import {test,expect} from '@playwright/test';
test('讲解方式持久化并从分镜规划重跑，原画面设置保留',async({page,request})=>{
 const created=await request.post('/api/projects',{data:{name:'讲解方式验收',brief:'用十五秒讲清主梁尺度'}});
 expect(created.ok()).toBeTruthy();const project=await created.json();
 await page.goto('/');await page.locator('#project-select').selectOption(project.id);
 await page.getByRole('button',{name:'讲解方式',exact:true}).click();
 await page.getByLabel('讲解重点').selectOption('scale');await page.getByLabel('目标时长（秒）').fill('15');
 await page.getByRole('button',{name:'保存讲解方式',exact:true}).click();
 await expect(page.locator('#director-settings')).not.toBeVisible();
 await expect(page.locator('#rerun-stage')).toHaveValue('plan');
 const saved=await (await request.get(`/api/projects/${project.id}`)).json();
 expect(saved.director_recipe).toBe('scale');expect(saved.target_s).toBe(15);expect(saved.render_mode).toBe('standard');
 await page.reload();await page.getByRole('button',{name:'讲解方式',exact:true}).click();
 await expect(page.getByLabel('讲解重点')).toHaveValue('scale');await expect(page.getByLabel('目标时长（秒）')).toHaveValue('15');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await page.screenshot({path:'test-results/T24-director-settings/settings.png'});
 await page.getByRole('button',{name:'取消',exact:true}).click();
});
