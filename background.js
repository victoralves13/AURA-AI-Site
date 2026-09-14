/* AURA AI — atmospheric neural background */
(()=>{
  if(document.getElementById('auraBackground')) return;
  const canvas=document.createElement('canvas');
  canvas.id='auraBackground'; canvas.setAttribute('aria-hidden','true');
  Object.assign(canvas.style,{position:'fixed',inset:'0',width:'100vw',height:'100vh',display:'block',zIndex:'0',pointerEvents:'none',opacity:'.92'});
  const app=document.querySelector('.app'); if(app)Object.assign(app.style,{position:'relative',zIndex:'1'});
  document.body.prepend(canvas);
  const ctx=canvas.getContext('2d'); const reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let w=0,h=0,dpr=1,particles=[],mx=.5,my=.5;
  const resize=()=>{dpr=Math.min(window.devicePixelRatio||1,1.6);w=window.innerWidth;h=window.innerHeight;canvas.width=Math.floor(w*dpr);canvas.height=Math.floor(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);const count=Math.max(34,Math.min(82,Math.round(w*h/21000)));particles=Array.from({length:count},()=>({x:Math.random()*w,y:Math.random()*h,r:.7+Math.random()*2.1,a:.10+Math.random()*.28,vx:(Math.random()-.5)*.10,vy:(Math.random()-.5)*.10,p:Math.random()*Math.PI*2}));};
  const draw=()=>{ctx.clearRect(0,0,w,h);const t=performance.now()*.00035;for(const p of particles){if(!reduce){p.x+=p.vx+Math.sin(t+p.p)*.045;p.y+=p.vy+Math.cos(t*.9+p.p)*.045;if(p.x<-10)p.x=w+10;if(p.x>w+10)p.x=-10;if(p.y<-10)p.y=h+10;if(p.y>h+10)p.y=-10;}const px=p.x+(mx-.5)*7,py=p.y+(my-.5)*5;const glow=ctx.createRadialGradient(px,py,0,px,py,p.r*7);glow.addColorStop(0,`rgba(101,231,245,${p.a})`);glow.addColorStop(1,'rgba(101,231,245,0)');ctx.fillStyle=glow;ctx.beginPath();ctx.arc(px,py,p.r*7,0,Math.PI*2);ctx.fill();ctx.fillStyle=`rgba(135,240,250,${Math.min(.72,p.a+.18)})`;ctx.beginPath();ctx.arc(px,py,p.r,0,Math.PI*2);ctx.fill();}for(let i=0;i<particles.length;i++)for(let j=i+1;j<particles.length;j++){const a=particles[i],b=particles[j],dx=a.x-b.x,dy=a.y-b.y,dist=Math.hypot(dx,dy);if(dist<125){const alpha=(1-dist/125)*.055;ctx.strokeStyle=`rgba(101,231,245,${alpha})`;ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();}}requestAnimationFrame(draw);};
  window.addEventListener('resize',resize,{passive:true});window.addEventListener('pointermove',e=>{mx=e.clientX/w;my=e.clientY/h},{passive:true});resize();draw();
  const product=document.createElement('script');product.src='product-layer.js';product.async=false;document.body.appendChild(product);
  const intro=document.createElement('script');intro.src='intro.js';intro.async=false;window.setTimeout(()=>document.body.appendChild(intro),80);
})();
