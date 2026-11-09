import * as THREE from 'three';
export const clamp = (x,a=0,b=1) => Math.max(a,Math.min(b,x));
export const ease = x => (x=clamp(x))<.5?4*x*x*x:1-(-2*x+2)**3/2;
export const esc = s => String(s ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const names = {girder:'主梁',leg_left:'刚性腿',leg_right:'柔性腿',trolley:'起重小车',hoist_hook:'吊钩',cab:'司机室'};
export function source(f){return `来源：${esc(f?.source?.doc || '待添加')} 第${esc(f?.source?.page ?? '待添加')}页`;}
export function orbit(ctx,angle=20,elevation=18,distance=1.2,target=ctx.center){
 const a=THREE.MathUtils.degToRad(angle), e=THREE.MathUtils.degToRad(elevation), r=ctx.diagonal*distance;
 ctx.camera.position.set(target.x+Math.sin(a)*Math.cos(e)*r,target.y+Math.sin(e)*r,target.z+Math.cos(a)*Math.cos(e)*r);
 ctx.camera.lookAt(target);ctx.camera.updateMatrixWorld();
}
export function mesh(geometry,color,metalness=.35){return new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,metalness,roughness:.4}));}
export function box(group,w,h,d,x,y,z,color){const m=mesh(new THREE.BoxGeometry(w,h,d),color);m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;group.add(m);return m;}
export function labelNodes(ctx,ids){
 ctx.scene.updateMatrixWorld(true);ctx.camera.updateMatrixWorld();
 const items=ids.map(id=>{const n=ctx.model.getObjectByName(id);if(!n)return null;const v=new THREE.Box3().setFromObject(n).getCenter(new THREE.Vector3()).project(ctx.camera);return{id,x:(v.x+1)*960,y:(1-v.y)*540};}).filter(Boolean).sort((a,b)=>a.y-b.y);
 ctx.labels.innerHTML=items.map((v,i)=>{const left=v.x<960, x=left?95:1590,y=385+i*85,end=left?x+210:x;return `<path d="M ${v.x} ${v.y} L ${left?end+35:end-35} ${y+25} L ${end} ${y+25}"/><circle cx="${v.x}" cy="${v.y}" r="5"/><rect x="${x}" y="${y}" width="210" height="50" rx="8"/><text x="${x+20}" y="${y+34}">${names[v.id]||esc(v.id)}</text>`;}).join('');
}
export const setup = () => {};

export function boundsCorners(bounds){
 const points=[];
 for(const x of [bounds.min.x,bounds.max.x])for(const y of [bounds.min.y,bounds.max.y])for(const z of [bounds.min.z,bounds.max.z])points.push(new THREE.Vector3(x,y,z));
 return points;
}
// 以外包投影占比取景，保持类比两侧的比例一致。
export function frameParallel(ctx,bounds,{angle=0,elevation=35,width,height,cx=.5,cy=.5}){
 const parts=Array.isArray(bounds)?bounds:[bounds];
 bounds=parts.reduce((all,part)=>all.union(part),new THREE.Box3());
 const center=bounds.getCenter(new THREE.Vector3());
 orbit(ctx,angle,elevation,1,center);
 const right=new THREE.Vector3(1,0,0).applyQuaternion(ctx.camera.quaternion);
 const up=new THREE.Vector3(0,1,0).applyQuaternion(ctx.camera.quaternion);
 const back=new THREE.Vector3(0,0,1).applyQuaternion(ctx.camera.quaternion);
 const points=parts.flatMap(boundsCorners).map(p=>p.sub(center));
 const extent=axis=>Math.max(...points.map(p=>p.dot(axis)))-Math.min(...points.map(p=>p.dot(axis)));
 const halfHeight=height?extent(up)/(2*height):extent(right)/(2*width*ctx.camera.aspect);
 const halfWidth=halfHeight*ctx.camera.aspect;
 const midpoint=axis=>(Math.max(...points.map(p=>p.dot(axis)))+Math.min(...points.map(p=>p.dot(axis))))/2;
 const target=center.clone().addScaledVector(right,midpoint(right)-(2*cx-1)*halfWidth).addScaledVector(up,midpoint(up)-(1-2*cy)*halfHeight);
 ctx.camera.position.copy(target).addScaledVector(back,bounds.getSize(new THREE.Vector3()).length());
 ctx.camera.lookAt(target);ctx.camera.updateMatrixWorld();
 ctx.camera.projectionMatrix.makeOrthographic(-halfWidth,halfWidth,halfHeight,-halfHeight,ctx.camera.near,ctx.camera.far);
 ctx.camera.projectionMatrixInverse.copy(ctx.camera.projectionMatrix).invert();
}
