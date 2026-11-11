import {defineConfig} from '@playwright/test';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../..',import.meta.url));
const scratch=mkdtempSync(path.join(tmpdir(),'kepu-scale-ui-'));
process.once('exit',()=>rmSync(scratch,{recursive:true,force:true}));
export default defineConfig({
 testDir:'.',testMatch:['scale-film-settings.spec.ts','director-settings.spec.ts'],workers:1,timeout:30000,
 outputDir:'../test-results/T25-scale-film',
 use:{baseURL:'http://127.0.0.1:8040',viewport:{width:1440,height:1000},headless:true,
 launchOptions:{executablePath:process.env.KEPU_CHROMIUM_PATH}},
 webServer:{cwd:path.join(root,'backend'),command:'.venv/bin/python -m app.main',url:'http://127.0.0.1:8040/api/projects',reuseExistingServer:false,
 env:{KEPU_PORT:'8040',KEPU_PROJECTS_DIR:scratch,KEPU_LLM_MODE:'replay',KEPU_TTS_ENGINE:'fake'}},
});
