import {defineConfig} from '@playwright/test';

// 纯几何与投影校验，不启动服务或浏览器。
export default defineConfig({
 testDir:'.',testMatch:'player.spec.ts',workers:1,timeout:30000,
 outputDir:'../test-results/geometry',
 grep:/T23开场|T23分解|GLB节点|参照物实际|吊钩离地|长度类比左端|高度类比与|开场模型|飞机有可见|焊缝头发丝|类比尺寸新|楼房窗片|飞机在轨道|钢板错边|旧头发丝/,
});
