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

const explodedAnchors=JSON.parse(await readFile(new URL('./fixtures/background/exploded-anchors.json',import.meta.url)));
const explodedTimeline=JSON.parse(await readFile(new URL('./fixtures/background/exploded-timeline.json',import.meta.url)));
const {renderBackground,render:renderExploded}=await import('../player/shots/exploded.js');
const {bboxLeaderPoint,nearLeaderSlots,segmentIntersectsRect,leadersIntersect}=await import('../player/shots/layout.js');
test('爆炸背景标注跟随表面锚点，避障换侧且乱序定位一致',()=>{
 const shot=explodedTimeline.shots[0];
 const ctx={scene:{updateMatrixWorld(){}},camera:{updateMatrixWorld(){}},
  timeline:explodedTimeline,content:{innerHTML:''},labels:{innerHTML:''}};
 // 背景路径不读取模型，也不修改模型几何。
 renderExploded(ctx,shot,0,1.5);
 const saved=new Map();
 for(const frame of [1,3,2,1]){
  const points=anchorPoints(explodedAnchors,frame,shot.bg);
  assert.equal(points('cab').left,true);
  assert.ok(points('cab').x>960);
  renderBackground(ctx,shot,0,points);
  const labels=[...ctx.labels.innerHTML.matchAll(/<g data-part="([^"]+)" data-side="([^"]+)"><path d="M ([\d.]+) ([\d.]+)[^"]*"\/><circle cx="([\d.]+)" cy="([\d.]+)"/g)];
  assert.equal(labels.length,6);
  const paths=[...ctx.labels.innerHTML.matchAll(/<path d="([^\"]+)"/g)].map(([,d])=>
   [...d.matchAll(/[ML] ([\d.]+) ([\d.]+)/g)].map(([,x,y])=>({x:+x,y:+y})));
  for(const [i,path] of paths.entries()){
   assert.ok(path.slice(1).every((p,j)=>p.x===path[j].x||p.y===path[j].y));
   assert.ok(path.slice(1).filter((p,j)=>p.y!==path[j].y).length<=1);
   for(const other of paths.slice(0,i))assert.equal(leadersIntersect(path,other),false);
  }

  for(const [,id,side,x,y,cx,cy] of labels){
   const p=points(id),[x0,y0,x1,y1]=p.bbox;
   assert.equal(+cx,p.pin.x);assert.equal(+cy,p.pin.y);
   assert.ok(+cx>=x0&&+cx<=x1&&+cy>=y0&&+cy<=y1,id);
  }
  for(const id of ['hoist_hook','trolley']){
   const p=points(id);
   assert.ok(ctx.labels.innerHTML.includes(`data-highlight="${id}" cx="${p.x}" cy="${p.y}"`));
  }
  if(saved.has(frame))assert.equal(ctx.labels.innerHTML,saved.get(frame));
  saved.set(frame,ctx.labels.innerHTML);
 }
});
test('小包围盒内缩不越界，标注落点取靠近标签的边缘',()=>{
 assert.deepEqual(bboxLeaderPoint([100,200,160,300],{x:0,y:250}),{x:108,y:250});
 assert.deepEqual(bboxLeaderPoint([100,200,160,300],{x:999,y:999}),{x:152,y:292});
 assert.deepEqual(bboxLeaderPoint([100,200,106,208],{x:0,y:0}),{x:103,y:204});
});

test('就近标签在安全区内至少间隔56像素，终点保持pin且绕开其他部件',()=>{
 const shot=explodedTimeline.shots[0],source=anchorPoints(explodedAnchors,1,shot.bg);
 const items=Object.keys(explodedAnchors.frames[0].nodes).map(id=>({id,...source(id)}));
 const safe={x:40,y:250,width:1840,height:600};
 const result=nearLeaderSlots(items,safe);
 for(const left of [true,false]){
  const side=result.filter(v=>v.left===left).sort((a,b)=>a.label.y-b.label.y);
  const edge=left?Math.min(...side.map(v=>v.bbox[0])):Math.max(...side.map(v=>v.bbox[2]));
  side.forEach((v,i)=>{
   assert.ok(v.label.y>=safe.y&&v.label.y+50<=safe.y+safe.height);
   if(i)assert.ok(v.label.y-side[i-1].label.y>=56);
   assert.equal(left?edge-v.label.x-210:v.label.x-edge,28);
   assert.deepEqual(v.points[0],v.pin);
   for(const other of items.filter(p=>p.id!==v.id)){
    for(let j=1;j<v.points.length;j++)assert.equal(segmentIntersectsRect(v.points[j-1],v.points[j],other.rect),false,`${v.id} 引线穿过 ${other.id}`);
   }
  });
 }
});
test('直连受阻的标签通过正交绕行或换侧避障',()=>{
 const a={id:'cab',x:600,y:500,pin:{x:600,y:500},left:true,bbox:[580,480,620,520]};
 const blocker={id:'leg_left',x:550,y:500,left:true,bbox:[540,450,560,550]};
 const result=nearLeaderSlots([a],undefined,[a,blocker])[0];
 for(let i=1;i<result.points.length;i++)assert.equal(segmentIntersectsRect(result.points[i-1],result.points[i],{x:540,y:450,width:20,height:100}),false);
});
const {render:renderCard,fitPanel}=await import('../player/shots/data_card.js');
for(const count of [2,3,4])test(`${count}项参数卡保留全部来源并按项数切换网格`,()=>{
 const facts=Object.fromEntries(Array.from({length:count},(_,i)=>[`F_${i}`,{name:'参数',value:100+i,unit:'m',source:{doc:'参数表.pdf',page:i+1}}]));
 const ctx={content:{innerHTML:''},timeline:{facts}};
 renderCard(ctx,{bg:{},params:{facts:Object.keys(facts)}},2,6);
 assert.equal((ctx.content.innerHTML.match(/class="data-card"/g)||[]).length,count);
 assert.equal((ctx.content.innerHTML.match(/来源：参数表.pdf/g)||[]).length,count);
 assert.equal(ctx.content.innerHTML.includes('data-grid'),count>=4);
 const panel={style:{},offsetTop:145,offsetHeight:count*205+100};
 fitPanel({querySelector:()=>panel},{textContent:'两行字幕',offsetTop:826});
 const scale=panel.style.transform?Number(panel.style.transform.match(/scale\(([^)]+)/)[1]):1;
 assert.ok(panel.offsetTop+panel.offsetHeight*scale<826-12);
});

test('黄昏纹理、暖光与无网格地面保持到乱序更新',async()=>{
 const THREE=await import('three');
 const {applyTwilight}=await import('../player/shots/theme.js');
 const {updateGround}=await import('../player/shots/common.js');
 const {render:renderMotion}=await import('../player/shots/motion.js');
 const previous=globalThis.document,stops=[];
 const canvas={getContext:()=>({createLinearGradient:()=>({addColorStop:(p,c)=>stops.push([p,c])}),fillRect(){}})};
 globalThis.document={createElement:()=>canvas,getElementById:()=>({innerHTML:''})};
 try{
  const scene=new THREE.Scene();scene.fog=new THREE.Fog('#ffffff',230,650);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(100,100),new THREE.MeshStandardMaterial());
  const ctx={scene,floor,renderer:{toneMappingExposure:1.15},sun:new THREE.DirectionalLight(),
   hemisphere:new THREE.HemisphereLight(),backdrop:{visible:true},camera:new THREE.PerspectiveCamera(40,1920/1080,.01,2500),center:new THREE.Vector3(0,25,0),
   model:new THREE.Group(),timeline:{},content:{innerHTML:''},diagonal:120};
  const sky=applyTwilight(ctx);assert.equal(sky.isCanvasTexture,true);
  assert.deepEqual(stops,[[0,'#17324F'],[1,'#B89F86']]);
  assert.equal(ctx.floor.material.map,null);assert.equal(ctx.floor.material.color.getHexString(),'3b3e42');
  assert.equal(ctx.sun.color.getHexString(),'ffd2a0');assert.ok(ctx.sun.position.y<40);
  assert.equal(ctx.hemisphere.color.getHexString(),'6f8fb3');assert.equal(ctx.hemisphere.groundColor.getHexString(),'2a2d31');
  renderMotion(ctx,{params:{axis:'gantry',from_m:0,to_m:20}},2,6);
  updateGround({...ctx,photoreal:true});
  assert.equal(ctx.scene.background,sky);assert.equal(ctx.scene.fog.color.getHexString(),'3a4552');
  assert.equal(ctx.backdrop.visible,false);assert.equal(ctx.renderer.toneMappingExposure,1);
 }finally{globalThis.document=previous;}
});

for(const width of [1840,1380.8])for(const shift of [0,-400])test(`写实引线正交无交叉且小车吊钩保持水平近侧 ${width}/${shift}`,()=>{
 const shot=explodedTimeline.shots[0],safe={x:40,y:250,width,height:600};
 for(const frame of [1,3,2,1]){
  const source=anchorPoints(explodedAnchors,frame,shot.bg);
  const items=Object.keys(explodedAnchors.frames[0].nodes).map(id=>{
   const p=source(id);
   if(['hoist_hook','trolley'].includes(id)){
    p.x+=shift;p.pin.x+=shift;p.bbox[0]+=shift;p.bbox[2]+=shift;p.rect.x+=shift;
   }
   return {id,...p};
  });
  const result=nearLeaderSlots(items,safe);
  const leftX=Math.max(safe.x,Math.min(safe.x+width-210,Math.min(...items.map(v=>v.bbox[0]))-238))+210;
  const rightX=Math.max(safe.x,Math.min(safe.x+width-210,Math.max(...items.map(v=>v.bbox[2]))+28));
  for(const [i,v] of result.entries()){
   assert.deepEqual(v.points[0],v.pin);
   const segments=v.points.slice(1).map((p,i)=>[v.points[i],p]);
   assert.ok(segments.every(([a,b])=>a.x===b.x||a.y===b.y),v.id);
   assert.ok(segments.filter(([a,b])=>a.y!==b.y).length<=1,v.id);
   for(const other of result.slice(0,i))assert.equal(leadersIntersect(v.points,other.points),false,`${v.id}/${other.id}`);
   if(['hoist_hook','trolley'].includes(v.id))assert.equal(v.left,Math.abs(v.x-leftX)<=Math.abs(v.x-rightX));
  }
 }
});
