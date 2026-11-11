// 画面亮度沿用现有 mask 的归一化 sRGB 加权口径，不放宽成线性光比。
export function luminance(pixels,i){return (.2126*pixels[i]+.7152*pixels[i+1]+.0722*pixels[i+2])/255;}
export function linearLuminance(pixels,i){const linear=c=>{c/=255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;};return .2126*linear(pixels[i])+.7152*linear(pixels[i+1])+.0722*linear(pixels[i+2]);}
export function measureLighting(pixels,mask,width,height){
 const sums=[0,0],linearSums=[0,0],counts=[0,0];
 for(let y=2;y<height-2;y++)for(let x=2;x<width-2;x++){
  const i=(y*width+x)*4,kind=mask[i]>250&&mask[i+1]<5?0:mask[i+1]>250&&mask[i]<5?1:-1;
  if(kind<0)continue;
  if(![i-8,i+8,i-width*8,i+width*8].every(j=>mask[j+kind]>250&&mask[j+1-kind]<5))continue;
  sums[kind]+=luminance(pixels,i);linearSums[kind]+=linearLuminance(pixels,i);counts[kind]++;
 }
 const means=sums.map((v,i)=>v/counts[i]);return {sunCount:counts[0],shadeCount:counts[1],sun:means[0],shade:means[1],ratio:means[0]/means[1],linearSun:linearSums[0]/counts[0],linearShade:linearSums[1]/counts[1],linearRatio:(linearSums[0]/counts[0])/(linearSums[1]/counts[1])};
}
