import * as THREE from 'three';
import {esc} from './common.js';
import {cameraArc,cameraEase} from '../camera.js';
export {setup} from './common.js';
export function render(ctx,shot,t,dur){
 const u=cameraEase(t/dur),scale=(ctx.size?.y||ctx.center.y*2||51)/51;
 const target=new THREE.Vector3(4*scale,24*scale,0);
 cameraArc(ctx,{angle:-36+u*5,elevation:-3.6,distance:(178-u*12)*scale,target,fov:36,screenX:.60,screenY:.51});
 ctx.content.innerHTML=`<div class="hero opening"><div class="eyebrow">工程的尺度</div><h1>${esc(shot.params.title||'大器，有度')}</h1><p>${esc(shot.params.subtitle||'')}</p></div>`;
}
