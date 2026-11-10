import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {backgroundFrame,backgroundURL,anchorPoints,showBackground} from '../player/background.js';
import {labelNodes} from '../player/shots/common.js';
const data=JSON.parse(await readFile(new URL('./fixtures/background/timeline.json',import.meta.url)));
const anchors=JSON.parse(await readFile(new URL('./fixtures/background/anchors.json',import.meta.url)));
const bg=data.shots[0].bg;
test('帧编号按四舍五入取值并限制首尾',()=>{
 for(const [t,expected] of [[-1,1],[0,1],[.249,1],[.25,2],[.5,2],[.75,3],[1.5,3],[100,3]]){
  assert.equal(backgroundFrame(bg,t),expected);
  assert.equal(backgroundURL(bg,expected),`frame_${String(expected).padStart(5,'0')}.jpg`);
 }
});
test('半分辨率锚点正确缩放并复用标注布局，隐藏节点不出现',()=>{
 const ctx={scene:{updateMatrixWorld(){}},camera:{updateMatrixWorld(){}},labels:{innerHTML:''}};
 labelNodes(ctx,['girder','trolley'],{pointSource:anchorPoints(anchors,2,bg)});
 assert.match(ctx.labels.innerHTML,/cx="840" cy="420"/);
 assert.doesNotMatch(ctx.labels.innerHTML,/data-part="trolley"/);
 assert.match(ctx.labels.innerHTML,/<path/);
});
test('seek等待当前帧解码且只保留后两帧预取',async()=>{
 const saved=globalThis.Image,loaded=[];
 globalThis.Image=class {set src(value){loaded.push(value);}};
 try{
  let finish;const img={src:'',hidden:true,decode:()=>new Promise(resolve=>finish=resolve)};
  const preloaded=new Map(),resolve=url=>`https://fixture.invalid/${url}`;
  let finished=false;
  const job=showBackground(img,bg,1,resolve,preloaded).then(()=>finished=true);
  assert.equal(finished,false);assert.equal(img.hidden,true);assert.equal(loaded.length,0);
  finish();await job;assert.equal(img.hidden,false);assert.equal(loaded.length,2);assert.equal(preloaded.size,2);
  img.decode=async()=>{};await showBackground(img,bg,3,resolve,preloaded);
  assert.equal(preloaded.size,0);assert.equal(loaded.length,2);
 }finally{globalThis.Image=saved;}
});

test('写实进度按镜头合并为一次工具调用',async()=>{
 const {mergeEvents}=await import('../app/common.js');
 const events=[];
 for(const shot of ['S1','S2'])for(const [status,frame] of [['start',null],['start',30],['start',60],['ok',null]]){
  events.push({run:'r1',tool:'render.blender',status,ts:'2026-11-10T00:00:00Z',detail:{shot,...(frame?{frame,total:60}:{})}});
 }
 const calls=mergeEvents(events);assert.equal(calls.length,2);
 assert.deepEqual(calls.map(call=>call.updates.length),[4,4]);
 assert.deepEqual(calls.map(call=>call.status),['ok','ok']);
});
