import {orbit,ease,esc} from './common.js';
export {setup} from './common.js';
export function render(ctx,shot,t,dur){const p=shot.params,rig=ctx.timeline.model?.rig?.axes?.[p.axis],node=ctx.model.getObjectByName(rig?.node || ({trolley:'trolley',hoist:'hoist_hook',gantry:'crane'})[p.axis]);let value=p.from_m+(p.to_m-p.from_m)*ease(t/dur);
 if(node){const axis=rig?.axis||({trolley:'x',hoist:'y',gantry:'z'})[p.axis];if(p.axis==='hoist'){node.parent.updateWorldMatrix(true,false);const world=node.getWorldPosition(ctx.center.clone());world.y=value;node.position.copy(node.parent.worldToLocal(world));const rope=ctx.model.getObjectByName('rope');if(rope){const initial=ctx.originals.find(o=>o.n===rope);const oldHook=ctx.originals.find(o=>o.n===node);const anchor=initial.p.y+Math.abs(initial.p.y-oldHook.p.y);const length=Math.max(.01,anchor-node.position.y),oldLength=Math.max(.01,anchor-oldHook.p.y);rope.position.y=(anchor+node.position.y)/2;rope.scale.y=initial.s.y*length/oldLength;}}else{node.position[axis]=value;}}
 const target=ctx.center.clone();target.x+=10;orbit(ctx,24,17,1.45,target);if(p.axis==='gantry'&&ctx.floor.material.map)ctx.floor.material.map.offset.y=-value/62.5;
 const f=ctx.timeline.facts?.[rig?.speed_fact];document.getElementById('motion-info').innerHTML=`<strong>${(p.speedup??1)===1?'实时':`×${esc(p.speedup)} 倍速`}</strong>${f?`最大 ${esc(f.value)} m/min · 来源 第${esc(f.source.page)}页`:'速度参数待添加'}`;
 ctx.content.innerHTML=`<div class="section-title"><small>运动演示</small>${({trolley:'小车横移 · 精准就位',hoist:'吊钩起升 · 稳定承载',gantry:'大车行走 · 协同推进'})[p.axis]}</div>`;
}
