// mask 由独立几何通道产生：红=设备，白=橙红漆，黑=背景/遮挡物。
export function measureProjection(pixels,mask,width,height){
 let count=0,paintCount=0,luminance=0,red=0,green=0,blue=0,clipped=0,dark=0;
 const levels=[],bounds={left:width,right:-1,top:height,bottom:-1};
 for(let y=1;y<height-1;y++)for(let x=1;x<width-1;x++){
  const i=(y*width+x)*4;
  // 腐蚀一个像素仅排除光栅边缘，不按最终画面的颜色/明度选样。
  if(![i,i-4,i+4,i-width*4,i+width*4].every(j=>mask[j]>250))continue;
  const r=pixels[i]/255,g=pixels[i+1]/255,b=pixels[i+2]/255;
  const l=.2126*r+.7152*g+.0722*b;
  count++;luminance+=l;
  bounds.left=Math.min(bounds.left,x);bounds.right=Math.max(bounds.right,x);bounds.top=Math.min(bounds.top,y);bounds.bottom=Math.max(bounds.bottom,y);
  if(![i,i-4,i+4,i-width*4,i+width*4].every(j=>mask[j+1]>250))continue;
  paintCount++;red+=r;green+=g;blue+=b;levels.push(l);
  if(Math.max(r,g,b)>.985)clipped++;if(l<.1)dark++;
 }
 const r=red/paintCount,g=green/paintCount,b=blue/paintCount,max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;
 const hue=d===0?0:((max===r?(g-b)/d:max===g?(b-r)/d+2:(r-g)/d+4)*60+360)%360;
 levels.sort((a,b)=>a-b);
 return {count,paintCount,brightness:luminance/count,paintBrightness:.2126*r+.7152*g+.0722*b,hue,saturation:max===0?0:d/max,clipped:clipped/paintCount,dark:dark/paintCount,
  contrast:levels[Math.floor(levels.length*.9)]-levels[Math.floor(levels.length*.1)],bounds};
}

export function projectionPasses(m){
 return m.count>=5000&&m.paintCount>=3000&&m.brightness>=.25&&m.paintBrightness>=.25&&m.hue>=10&&m.hue<=25&&m.saturation>=.55;
}
