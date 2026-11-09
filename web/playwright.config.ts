import { defineConfig } from '@playwright/test';
import { mkdtempSync, cpSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ownsTestRoot=!process.env.KEPU_UI_TEST_ROOT;
const testRoot=process.env.KEPU_UI_TEST_ROOT || mkdtempSync(path.join(tmpdir(),'kepu-ui-'));
process.env.KEPU_UI_TEST_ROOT=testRoot;
if(ownsTestRoot) process.once('exit',()=>rmSync(testRoot,{recursive:true,force:true}));
mkdirSync(path.join(testRoot,'projects'),{recursive:true});
cpSync(path.join(root,'backend/tests/cassettes'),path.join(testRoot,'cassettes'),{recursive:true});
export default defineConfig({
 testDir:'./tests',timeout:120000,expect:{timeout:20000},fullyParallel:false,workers:1,
 use:{baseURL:'http://127.0.0.1:8766',viewport:{width:1920,height:1080},deviceScaleFactor:1,headless:true,launchOptions:{executablePath:process.env.KEPU_CHROMIUM_PATH,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}},
 projects:[
  {name:'player',testIgnore:'**/ui.spec.ts'},
  {name:'ui',testMatch:'**/ui.spec.ts',use:{baseURL:'http://127.0.0.1:8032'}},
 ],
 webServer:[
  {command:'node tools/serve.mjs --port 8766',url:'http://127.0.0.1:8766/player/',reuseExistingServer:!process.env.CI,timeout:20000},
  {command:'cd ../backend && uv run python -m app.main',url:'http://127.0.0.1:8032/api/projects',reuseExistingServer:false,timeout:60000,
   env:{KEPU_PROJECTS_DIR:path.join(testRoot,'projects'),KEPU_LLM_CASSETTES:path.join(testRoot,'cassettes'),KEPU_LLM_MODE:'replay',KEPU_TTS_ENGINE:'fake',KEPU_RENDER_MAX_S:'4',KEPU_PORT:'8032',UV_CACHE_DIR:path.join(testRoot,'uv-cache')}},
 ],
});
