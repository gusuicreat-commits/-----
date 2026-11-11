import {defineConfig} from '@playwright/test';
import {fileURLToPath} from 'node:url';
const software=process.env.KEPU_SOFTWARE_LOOK==='1';
process.env.KEPU_HARDWARE_LOOK=software?'0':'1';
// 默认验收硬件；软件模式运行相同画面断言，仅跳过性能门槛。
export default defineConfig({
 testDir:'.',testMatch:'look.spec.ts',workers:1,timeout:120000,outputDir:software?'../test-results/look-software':'../test-results/look',
 use:{baseURL:'http://127.0.0.1:8766',viewport:{width:1920,height:1080},deviceScaleFactor:1,
  headless:true,launchOptions:{executablePath:process.env.KEPU_CHROMIUM_PATH,args:software?(process.env.KEPU_SWIFTSHADER_WEBGL==='1'?['--use-gl=angle','--use-angle=swiftshader-webgl']:['--use-angle=swiftshader','--enable-unsafe-swiftshader']):[]}},
 webServer:{cwd:fileURLToPath(new URL('..',import.meta.url)),command:'node tools/serve.mjs --port 8766',url:'http://127.0.0.1:8766/player/',reuseExistingServer:!process.env.CI,timeout:20000},
});
