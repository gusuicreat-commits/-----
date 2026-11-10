// 帧编号、锚点换算与预取共用同一时间基准。
export function backgroundFrame(bg,localT){
 return Math.max(0,Math.min(bg.count-1,Math.round(localT*bg.fps)))+1;
}
export function backgroundURL(bg,index){return bg.frames.replace('%05d',String(index).padStart(5,'0'));}
export function anchorPoints(payload,index,bg){
 const nodes=payload?.frames?.find(frame=>frame.frame===index)?.nodes || {};
 const sx=1920/(payload?.width||bg.width),sy=1080/(payload?.height||bg.height);
 return id=>{
  const point=nodes[id];
  if(!point?.visible || !Number.isFinite(point.x) || !Number.isFinite(point.y))return null;
  const pin=point.pin;
  const x=(Number.isFinite(pin?.x)?pin.x:point.x)*sx,y=(Number.isFinite(pin?.y)?pin.y:point.y)*sy;
  const box=point.bbox;
  const bbox=Array.isArray(box)&&box.length===4&&box.every(Number.isFinite)?
   [box[0]*sx,box[1]*sy,box[2]*sx,box[3]*sy]:null;
  const girderX=Number.isFinite(nodes.girder?.x)?nodes.girder.x*sx:960;
  return {x,y,pin:{x,y},left:x<girderX,bbox,rect:bbox?
   {x:bbox[0],y:bbox[1],width:bbox[2]-bbox[0],height:bbox[3]-bbox[1]}:
   {x:x-8,y:y-8,width:16,height:16}};
 };
}
export async function loadBackgrounds(shots,resolve){
 const anchors=new Map();
 await Promise.all(shots.filter(shot=>shot.bg).map(async shot=>{
  const response=await fetch(resolve(shot.bg.anchors));
  if(!response.ok)throw new Error(`镜头 ${shot.id} 锚点加载失败（${response.status}）`);
  anchors.set(shot.id,await response.json());
 }));
 return anchors;
}
export async function showBackground(img,bg,index,resolve,preloaded){
 const url=resolve(backgroundURL(bg,index));
 if(img.src!==url)img.src=url;
 await img.decode();
 img.hidden=false;
 const upcoming=new Set();
 for(let i=index+1;i<=Math.min(bg.count,index+2);i++){
  const next=resolve(backgroundURL(bg,i));upcoming.add(next);
  if(!preloaded.has(next)){const image=new Image();image.src=next;preloaded.set(next,image);}
 }
 for(const key of preloaded.keys())if(!upcoming.has(key))preloaded.delete(key);
}

export function dimensionPoints(payload,index,bg){
 const dims=payload?.frames?.find(frame=>frame.frame===index)?.dims;
 if(!dims)throw new Error('写实类比缺少尺寸锚点');
 const sx=1920/(payload.width||bg.width),sy=1080/(payload.height||bg.height);
 return Object.fromEntries(Object.entries(dims).map(([key,p])=>{
  if(!Number.isFinite(p?.x)||!Number.isFinite(p?.y))throw new Error('写实类比尺寸锚点无效');
  return [key,{x:p.x*sx,y:p.y*sy}];
 }));
}
