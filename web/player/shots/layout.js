// 所有排版几何使用 1920×1080 画布坐标。
export function hudSafeArea(ctx,shot,t){
 const doc=ctx.content.ownerDocument,stage=doc?.getElementById('stage');
 // 镜头先于播放器 HUD 更新；测量当前帧文字，避免乱序 seek 使用上一帧尺寸。
 if(doc){
  const badge=doc.getElementById('badge'),caption=doc.getElementById('caption');
  if(badge)badge.textContent=`三维模型渲染 · ${ctx.timeline.model?.kind==='step'?'依据STEP':'参数化重建'}`;
  if(caption)caption.textContent=(ctx.timeline.captions||[]).filter(c=>t+(shot.start||0)>=c.start&&t+(shot.start||0)<c.end).map(c=>c.text).join('\n');
 }
 const origin=stage?.getBoundingClientRect(),scale=origin?.width/1920;
 const measure=selector=>{
  const node=stage?.querySelector(selector),r=node?.getBoundingClientRect();
  return r?.width&&r.height&&scale?{x:(r.x-origin.x)/scale,y:(r.y-origin.y)/scale,width:r.width/scale,height:r.height/scale}:null;
 };
 const top=['#badge','.section-title','#film-title'].map(measure).filter(Boolean);
 const bottom=['#caption','footer','.analogy-copy'].map(measure).filter(Boolean);
 const y=Math.max(196,...top.map(r=>r.y+r.height))+16;
 const end=Math.min(880,...bottom.map(r=>r.y))-16;
 return {x:40,y,width:1840,height:Math.max(1,end-y),obstacles:[...top,...bottom]};
}
// 平行投影同时平移目标点和调整视野，将完整包围矩形放入安全区。
export function fitProjection(ctx,rect,safe){
 const factor=Math.min(1,safe.width/rect.width,safe.height/rect.height);
 const cx=rect.x+rect.width/2,cy=rect.y+rect.height/2;
 const dx=(cx-960)-(safe.x+safe.width/2-960)/factor;
 const dy=(cy-540)-(safe.y+safe.height/2-540)/factor;
 const camera=ctx.camera,e=camera.projectionMatrix.elements;
 camera.position.add(camera.position.clone().set(1,0,0).applyQuaternion(camera.quaternion).multiplyScalar(dx/(960*e[0])));
 camera.position.add(camera.position.clone().set(0,1,0).applyQuaternion(camera.quaternion).multiplyScalar(-dy/(540*e[5])));
 e[0]*=factor;e[5]*=factor;
 camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();camera.updateMatrixWorld();
}
export function enclosingRect(rects){
 const x=Math.min(...rects.map(r=>r.x)),y=Math.min(...rects.map(r=>r.y));
 return {x,y,width:Math.max(...rects.map(r=>r.x+r.width))-x,height:Math.max(...rects.map(r=>r.y+r.height))-y};
}
export function segmentIntersectsRect(a,b,r){
 let low=0,high=1;
 for(const [origin,delta,min,max] of [[a.x,b.x-a.x,r.x,r.x+r.width],[a.y,b.y-a.y,r.y,r.y+r.height]]){
  if(Math.abs(delta)<1e-9){if(origin<min||origin>max)return false;continue;}
  const t1=(min-origin)/delta,t2=(max-origin)/delta;
  low=Math.max(low,Math.min(t1,t2));high=Math.min(high,Math.max(t1,t2));
  if(low>high)return false;
 }
 return true;
}
export function placeDimensionLabel(a,b,width,height,side,segments=[],obstacles=[]){
 const center={x:(a.x+b.x)/2,y:(a.y+b.y)/2};
 const x=side==='left'?center.x-width-14:side==='right'?center.x+14:center.x-width/2;
 const rect={x:Math.max(40,Math.min(1880-width,x)),y:side==='center'?Math.min(a.y,b.y)-height-14:center.y-height/2,width,height};
 const overlaps=r=>rect.x<r.x+r.width&&rect.x+width>r.x&&rect.y<r.y+r.height&&rect.y+height>r.y;
 // 只向线的外侧上移；不以向下堆叠的方式把文字推回尺寸线上。
 while(segments.some(([p,q])=>segmentIntersectsRect(p,q,rect))||obstacles.some(overlaps))rect.y-=height+14;
 return rect;
}
export function routeLeader(start,end,obstacles){
 // 锚点被其他部件遮挡时无法避开起始投影，仍保留真实锚点。
 const blocks=obstacles.filter(r=>!segmentIntersectsRect(start,start,r)&&!segmentIntersectsRect(end,end,r));
 const nodes=[start,end,...blocks.flatMap(r=>[
  {x:r.x-4,y:r.y-4},{x:r.x+r.width+4,y:r.y-4},
  {x:r.x-4,y:r.y+r.height+4},{x:r.x+r.width+4,y:r.y+r.height+4},
 ])];
 const distances=nodes.map(()=>Infinity),previous=[],visited=new Set();distances[0]=0;
 for(let step=0;step<nodes.length;step++){
  let best=-1;
  for(let i=0;i<nodes.length;i++)if(!visited.has(i)&&(best<0||distances[i]<distances[best]))best=i;
  if(best<0||!Number.isFinite(distances[best]))break;
  if(best===1){const path=[];for(let i=1;i!==undefined;i=previous[i])path.unshift(nodes[i]);return path;}
  visited.add(best);
  for(let i=0;i<nodes.length;i++){
   if(visited.has(i)||blocks.some(r=>segmentIntersectsRect(nodes[best],nodes[i],r)))continue;
   const cost=distances[best]+Math.hypot(nodes[i].x-nodes[best].x,nodes[i].y-nodes[best].y);
   if(cost<distances[i]){distances[i]=cost;previous[i]=best;}
  }
 }
 return [start,end];
}

export function splitLeaderSlots(items,safe={y:250,height:540}){
 return [true,false].flatMap(left=>{
  const side=items.filter(item=>item.left===left).sort((a,b)=>a.y-b.y||a.id.localeCompare(b.id));
  const x=left?95:1590,endX=left?x+210:x;
  // 横线先到同一外侧折点列，再按相同顺序连接标签，避免交叉。
  const elbowX=left?Math.min(380,...side.map(v=>v.x-24)):Math.max(1510,...side.map(v=>v.x+24));
  const slots=[];let next=Math.min(795,safe.y+safe.height);
  for(let i=side.length-1;i>=0;i--){slots[i]=Math.min(side[i].y,next-70);next=slots[i];}
  let previous=Math.max(250,safe.y)+25-70;
  for(let i=0;i<slots.length;i++){slots[i]=Math.max(slots[i],previous+70);previous=slots[i];}
  return side.map((v,i)=>({...v,label:{x,y:slots[i]-25},points:[{x:v.x,y:v.y},{x:elbowX,y:v.y},{x:endX,y:slots[i]}]}));
 });
}
