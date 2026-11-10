// 所有排版几何使用 1920×1080 画布坐标。
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

export function splitLeaderSlots(items){
 return [true,false].flatMap(left=>{
  const side=items.filter(item=>item.left===left).sort((a,b)=>a.y-b.y||a.id.localeCompare(b.id));
  const x=left?95:1590,endX=left?x+210:x;
  // 横线先到同一外侧折点列，再按相同顺序连接标签，避免交叉。
  const elbowX=left?Math.min(380,...side.map(v=>v.x-24)):Math.max(1510,...side.map(v=>v.x+24));
  const slots=[];let next=795;
  for(let i=side.length-1;i>=0;i--){slots[i]=Math.min(side[i].y,next-70);next=slots[i];}
  return side.map((v,i)=>({...v,label:{x,y:slots[i]-25},points:[{x:v.x,y:v.y},{x:elbowX,y:v.y},{x:endX,y:slots[i]}]}));
 });
}
