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

// 引线落在包围盒靠标签一侧，并向内缩进；小部件最多缩到中心。
export function bboxLeaderPoint(bbox,label,inset=8){
 const [x0,y0,x1,y1]=bbox,ix=Math.min(inset,(x1-x0)/2),iy=Math.min(inset,(y1-y0)/2);
 return {x:Math.max(x0+ix,Math.min(x1-ix,label.x)),
         y:Math.max(y0+iy,Math.min(y1-iy,label.y))};
}

export function splitLeaderSlots(items,safe={y:250,height:540}){
 return [true,false].flatMap(left=>{
  const side=items.filter(item=>item.left===left).sort((a,b)=>a.y-b.y||a.id.localeCompare(b.id));
  const x=left?95:Math.min(1590,(safe.x??40)+(safe.width??1840)-210),endX=left?x+210:x;
  // 横线先到同一外侧折点列，再按相同顺序连接标签，避免交叉。
  const elbowX=left?Math.min(380,...side.map(v=>v.x-24)):Math.max(1510,...side.map(v=>v.x+24));
  const slots=[];let next=Math.min(795,safe.y+safe.height);
  for(let i=side.length-1;i>=0;i--){slots[i]=Math.min(side[i].y,next-70);next=slots[i];}
  let previous=Math.max(250,safe.y)+25-70;
  for(let i=0;i<slots.length;i++){slots[i]=Math.max(slots[i],previous+70);previous=slots[i];}
  return side.map((v,i)=>{
   const end={x:endX,y:slots[i]},point=v.bbox?bboxLeaderPoint(v.bbox,end):{x:v.x,y:v.y};
   return {...v,...point,label:{x,y:slots[i]-25},points:[point,{x:v.bbox?endX+(left?24:-24):elbowX,y:point.y},end]};
  });
 });
}

// 正交引线的触碰、重叠也算相交。
export function leadersIntersect(a,b){
 return a.slice(1).some((p,i)=>b.slice(1).some((q,j)=>segmentIntersectsRect(a[i],p,{
  x:Math.min(b[j].x,q.x),y:Math.min(b[j].y,q.y),
  width:Math.abs(b[j].x-q.x),height:Math.abs(b[j].y-q.y),
 })));
}

// 保留表面 pin；只允许水平段和至多一段竖直段。
export function nearLeaderSlots(items,safe={x:40,y:250,width:1840,height:540},parts=items){
 if(!items.length)return [];
 const top=safe.y+25,bottom=safe.y+safe.height-25;
 const rectFor=p=>p.rect||(p.bbox?{x:p.bbox[0],y:p.bbox[1],width:p.bbox[2]-p.bbox[0],height:p.bbox[3]-p.bbox[1]}:null);
 const obstacles=v=>parts.filter(p=>p.id!==v.id).map(rectFor).filter(Boolean);
 const crossed=(points,blocks)=>points.slice(1).reduce((sum,p,i)=>sum+blocks.filter(r=>segmentIntersectsRect(points[i],p,r)).length,0);
 const column=side=>{
  const left=side[0].left;
  const edge=left?Math.min(...side.map(v=>v.bbox?.[0]??v.x))-28:Math.max(...side.map(v=>v.bbox?.[2]??v.x))+28;
  return Math.max(safe.x??40,Math.min((safe.x??40)+(safe.width??1840)-210,left?edge-210:edge));
 };
 // 以全部部件的两侧列为固定参照，避免避障时把吊钩、小车改派到远侧。
 const leftEnd=column(items.map(v=>({...v,left:true})))+210;
 const rightEnd=column(items.map(v=>({...v,left:false})));
 const nearest=v=>Math.abs(v.x-leftEnd)<=Math.abs(v.x-rightEnd);
 const locked=v=>['hoist_hook','trolley'].includes(v.id);
 const route=(v,end,routed)=>{
  const start={x:v.x,y:v.y},blocks=obstacles(v);
  const xs=[end.x,start.x+(v.left?-8:8),end.x+(v.left?14:-14),
   ...blocks.flatMap(r=>[r.x-4,r.x+r.width+4])];
  let best=null,bestScore=Infinity;
  for(const x of xs){
   if(x<Math.min(start.x,end.x)||x>Math.max(start.x,end.x))continue;
   const points=[start,{x,y:start.y},{x,y:end.y},end].filter((p,i,a)=>!i||p.x!==a[i-1].x||p.y!==a[i-1].y);
   const score=routed.filter(other=>leadersIntersect(points,other.points)).length*1e9+crossed(points,blocks)*1e6+
    points.slice(1).reduce((sum,p,i)=>sum+Math.abs(p.x-points[i].x)+Math.abs(p.y-points[i].y),0);
   if(score<bestScore){best={...v,label:{x:v.labelX,y:end.y-25},points};bestScore=score;}
  }
  return best;
 };
 const score=result=>result.reduce((sum,v,i)=>sum+result.slice(0,i).filter(other=>leadersIntersect(v.points,other.points)).length*1e9+
  crossed(v.points,obstacles(v))*1e6+(v.left!==items.find(p=>p.id===v.id).left?1e3:0)+Math.abs(v.label.y+25-v.y),0);
 const layout=assignment=>{
  const slots=[true,false].flatMap(left=>{
   const side=assignment.filter(v=>v.left===left).sort((a,b)=>a.y-b.y||a.id.localeCompare(b.id));
   if(!side.length)return [];
   const x=column(side),ys=side.map(v=>Math.max(top,Math.min(bottom,v.y)));
   for(let i=1;i<ys.length;i++)ys[i]=Math.max(ys[i],ys[i-1]+56);
   ys[ys.length-1]=Math.min(bottom,ys.at(-1));
   for(let i=ys.length-2;i>=0;i--)ys[i]=Math.min(ys[i],ys[i+1]-56);
   return side.map((v,i)=>({...v,labelX:x,slotY:ys[i]}));
  });
  const build=()=>{
   const result=[];
   for(const v of slots)result.push(route(v,{x:v.left?v.labelX+210:v.labelX,y:v.slotY},result));
   return result;
  };
  let result=build(),cost=score(result);
  // 同侧按 pin 高度排槽后，交换交叉引线的槽位，严格降低代价才保留。
  for(let pass=0;pass<slots.length;pass++){
   let improved=false;
   for(let i=0;i<slots.length;i++)for(let j=i+1;j<slots.length;j++){
    if(slots[i].left!==slots[j].left||!leadersIntersect(result[i].points,result[j].points))continue;
    [slots[i].slotY,slots[j].slotY]=[slots[j].slotY,slots[i].slotY];
    const candidate=build(),next=score(candidate);
    if(next<cost){result=candidate;cost=next;improved=true;}
    else [slots[i].slotY,slots[j].slotY]=[slots[j].slotY,slots[i].slotY];
   }
   // 单段竖线绕过高大部件时，槽位允许贴近其上、下边界。
   for(let i=0;i<slots.length;i++){
    const v=slots[i],original=v.slotY;
    const candidates=[top,bottom,v.y,...obstacles(v).flatMap(r=>[r.y-4,r.y+r.height+4]),
     ...slots.filter(other=>other!==v&&other.left===v.left).flatMap(other=>[other.slotY-56,other.slotY+56])];
    let chosen=original;
    for(const y of candidates){
     if(y<top||y>bottom||slots.some(other=>other!==v&&other.left===v.left&&Math.abs(other.slotY-y)<56))continue;
     v.slotY=y;
     const candidate=build(),next=score(candidate);
     if(next<cost){result=candidate;cost=next;chosen=y;improved=true;}
    }
    v.slotY=chosen;
   }
   if(!improved)break;
  }
  return result;
 };
 let best=null,bestScore=Infinity;
 for(let mask=0;mask<2**items.length;mask++){
  const assignment=items.map((v,i)=>({...v,left:!!(mask&(2**i))}));
  if(assignment.some(v=>locked(v)&&v.left!==nearest(v)))continue;
  const candidate=layout(assignment),cost=score(candidate);
  if(cost<bestScore){best=candidate;bestScore=cost;}
 }
 return best;
}
