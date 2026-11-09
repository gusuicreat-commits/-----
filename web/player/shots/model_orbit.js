import {orbit,ease,labelNodes} from './common.js';
export {setup} from './common.js';
export function render(ctx,shot,t,dur){const p=shot.params;orbit(ctx,(p.from_deg??-30)+((p.to_deg??30)-(p.from_deg??-30))*ease(t/dur),p.elevation_deg??15,p.distance??1.6);for(const id of p.highlight||[]){ctx.model.getObjectByName(id)?.traverse(n=>{if(n.isMesh)for(const m of [].concat(n.material)){if(m.emissive){m.emissive.set('#38d1ff');m.emissiveIntensity=.4+.2*Math.sin(t*2);}}});}ctx.content.innerHTML='<div class="section-title"><small>结构解构</small>每个部件，都各司其职</div>';labelNodes(ctx,p.highlight||[]);}
