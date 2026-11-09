import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';

export async function mountModel(host, url, onNodes) {
  const renderer = new THREE.WebGLRenderer({antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
  const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(38,16/9,0.1,10000);
  const controls = new OrbitControls(camera,renderer.domElement);
  controls.autoRotate = true; controls.autoRotateSpeed = 0.6; controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xc9e6ff,0x334455,3));
  const light = new THREE.DirectionalLight(0xffffff,3); light.position.set(80,130,100); scene.add(light);
  let frame, disposed = false;
  const resize = () => { const width = host.clientWidth; if (!width) return; renderer.setSize(width,width*9/16); camera.aspect=16/9; camera.updateProjectionMatrix(); };
  const observer = new ResizeObserver(resize);
  const dispose = () => { disposed = true; cancelAnimationFrame(frame); observer.disconnect(); controls.dispose(); scene.traverse(node => { node.geometry?.dispose(); const materials = Array.isArray(node.material) ? node.material : [node.material]; materials.filter(Boolean).forEach(m => { Object.values(m).forEach(v => { if (v?.isTexture) v.dispose(); }); m.dispose(); }); }); renderer.dispose(); renderer.domElement.remove(); };
  try {
    const gltf = await new GLTFLoader().loadAsync(url);
    scene.add(gltf.scene);
    if (!host.isConnected) { dispose(); return dispose; }
    const box = new THREE.Box3().setFromObject(gltf.scene), center = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length() || 10;
    camera.position.copy(center).add(new THREE.Vector3(size*0.7,size*0.4,size));
    camera.near=size/1000; camera.far=size*20; camera.updateProjectionMatrix(); controls.target.copy(center);
    host.replaceChildren(renderer.domElement); const nodes=[]; gltf.scene.traverse(n => { if(n.name) nodes.push(n.name); }); onNodes([...new Set(nodes)]);
    observer.observe(host); resize();
    const animate = () => { if (disposed) return; frame=requestAnimationFrame(animate); controls.update(); renderer.render(scene,camera); }; animate();
    return dispose;
  } catch (error) { dispose(); throw error; }
}
