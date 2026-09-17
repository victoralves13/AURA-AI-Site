/* AURA AI — atmospheric neural background */
(()=>{
  if(document.getElementById('auraBackground')) return;
  const canvas=document.createElement('canvas'); canvas.id='auraBackground'; canvas.setAttribute('aria-hidden','true');
  Object.assign(canvas.style,{position:'fixed',inset:'0',width:'100vw',height:'100vh',display:'block',zIndex:'0',pointerEvents:'none',opacity:'.92'});
  const app=document.querySelector('.app'); if(app)Object.assign(app.style,{position:'relative',zIndex:'1'}); document.body.prepend(canvas);
  const ctx=canvas.getContext('2d'),reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches; let w=0,h=0,dpr=1,particles=[],mx=.5,my=.5;
  const resize=()=>{dpr=Math.min(devicePixelRatio||1,1.6);w=innerWidth;h=innerHeight;canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);const n=Math.max(34,Math.min(82,Math.round(w*h/21000)));particles=Array.from({length:n},()=>({x:Math.random()*w,y:Math.random()*h,r:.7+Math.random()*2.1,a:.10+Math.random()*.28,vx:(Math.random()-.5)*.10,vy:(Math.random()-.5)*.10,p:Math.random()*Math.PI*2}))};
  const draw=()=>{ctx.clearRect(0,0,w,h);const t=performance.now()*.00035;for(const p of particles){if(!reduce){p.x+=p.vx+Math.sin(t+p.p)*.045;p.y+=p.vy+Math.cos(t*.9+p.p)*.045;if(p.x<-10)p.x=w+10;if(p.x>w+10)p.x=-10;if(p.y<-10)p.y=h+10;if(p.y>h+10)p.y=-10}const x=p.x+(mx-.5)*7,y=p.y+(my-.5)*5,g=ctx.createRadialGradient(x,y,0,x,y,p.r*7);g.addColorStop(0,`rgba(101,231,245,${p.a})`);g.addColorStop(1,'rgba(101,231,245,0)');ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,p.r*7,0,Math.PI*2);ctx.fill();ctx.fillStyle=`rgba(135,240,250,${Math.min(.72,p.a+.18)})`;ctx.beginPath();ctx.arc(x,y,p.r,0,Math.PI*2);ctx.fill()}requestAnimationFrame(draw)};
  addEventListener('resize',resize,{passive:true}); addEventListener('pointermove',e=>{mx=e.clientX/w;my=e.clientY/h},{passive:true}); resize(); draw();
  ['product-layer.js','intro.js','logo-enhancement.js','real-engine.js','persistence.js','dynamic-data.js'].forEach((src,i)=>{const s=document.createElement('script');s.src=src;s.async=false;setTimeout(()=>document.body.appendChild(s),80+i*70)});
})();
