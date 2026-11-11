import * as THREE from 'three';
const clamp=x=>Math.max(0,Math.min(1,x));
export const cameraEase=x=>{x=clamp(x);return x*x*(3-2*x);};
// 相机和注视点均由当前时间直接计算，支持任意顺序 seek。
export function perspectivePose(ctx,{position,target,fov=36,screenX=.5,screenY=.5}){
 const camera=ctx.camera;
 camera.fov=fov;camera.aspect=16/9;camera.near=.1;camera.far=2500;
 camera.position.copy(position);camera.up.set(0,1,0);camera.lookAt(target);camera.updateProjectionMatrix();
 camera.projectionMatrix.elements[8]=1-2*screenX;
 camera.projectionMatrix.elements[9]=2*screenY-1;
 camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();camera.updateMatrixWorld();
}
export function cameraArc(ctx,{angle,elevation,distance,target,fov=36,screenX=.5,screenY=.5}){
 const a=THREE.MathUtils.degToRad(angle),e=THREE.MathUtils.degToRad(elevation),r=distance;
 const position=new THREE.Vector3(target.x+Math.sin(a)*Math.cos(e)*r,target.y+Math.sin(e)*r,target.z+Math.cos(a)*Math.cos(e)*r);
 perspectivePose(ctx,{position,target,fov,screenX,screenY});
}
