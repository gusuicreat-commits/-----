import { defineConfig } from '@playwright/test';
export default defineConfig({
 testDir:'./tests',timeout:120000,expect:{timeout:20000},fullyParallel:false,workers:1,
 use:{baseURL:'http://127.0.0.1:8766',viewport:{width:1920,height:1080},deviceScaleFactor:1,headless:true,launchOptions:{executablePath:process.env.KEPU_CHROMIUM_PATH,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}},
 webServer:{command:'node tools/serve.mjs --port 8766',url:'http://127.0.0.1:8766/player/',reuseExistingServer:!process.env.CI,timeout:20000},
});
