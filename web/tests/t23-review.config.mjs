import base from './look.config.mjs';
export default {
 ...base,
 testMatch: 'player.spec.ts',
 outputDir: '../test-results/T23-aster-layout',
 grep: process.env.KEPU_FULL_PLAYER_REVIEW === '1' ? /./ : /角标、字幕|预览可播放|开场双分辨率|爆炸镜头实际标签|参数卡.*(?:项|片尾)|写实片尾副标题/,
 grepInvert: /渲染器导出60帧/,
};
