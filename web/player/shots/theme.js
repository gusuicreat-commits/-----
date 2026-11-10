import * as THREE from 'three';

export function twilightSky(){
 const canvas=document.createElement('canvas');canvas.width=2;canvas.height=512;
 const paint=canvas.getContext('2d'),gradient=paint.createLinearGradient(0,0,0,512);
 gradient.addColorStop(0,'#17324F');gradient.addColorStop(1,'#B89F86');
 paint.fillStyle=gradient;paint.fillRect(0,0,2,512);
 const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.SRGBColorSpace;
 return texture;
}
export function applyTwilight({scene,renderer,sun,hemisphere,floor,backdrop}){
 const sky=twilightSky();scene.background=sky;scene.fog.color.set('#3A4552');
 sun.color.set('#FFD2A0');sun.position.set(-90,35,65);sun.intensity=2.6;
 hemisphere.color.set('#6F8FB3');hemisphere.groundColor.set('#2A2D31');hemisphere.intensity=1.8;
 floor.material.dispose();floor.material=new THREE.MeshStandardMaterial({color:'#3B3E42',roughness:.94,metalness:.08});
 backdrop.visible=false;renderer.toneMappingExposure=1;
 return sky;
}
