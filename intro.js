/* AURA AI — cinematic product intro */
(()=>{
  'use strict';
  if(document.getElementById('auraIntro')) return;
  const style=document.createElement('style');
  style.id='auraIntroStyles';
  style.textContent=`
    #auraIntro{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:radial-gradient(circle at 50% 46%,rgba(9,54,67,.34),rgba(2,8,13,.97) 58%,#02070b 100%);overflow:hidden;opacity:1;transition:opacity 1s cubic-bezier(.2,.7,.2,1),visibility 1s}
    #auraIntro.is-leaving{opacity:0;visibility:hidden;pointer-events:none}
    #auraIntro .intro-aura{position:relative;width:min(300px,58vw);aspect-ratio:300/265;display:grid;place-items:center;transform:scale(.72);opacity:0;filter:blur(12px);animation:auraIntroIn 1.55s cubic-bezier(.16,1,.3,1) .1s forwards}
    #auraIntro .intro-aura:before{content:"";position:absolute;width:72%;height:72%;border-radius:50%;background:radial-gradient(circle,rgba(86,232,245,.18),rgba(86,232,245,0) 68%);filter:blur(18px);animation:introGlow 2.5s ease-in-out infinite}
    #auraIntro img{position:relative;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 0 28px rgba(81,226,241,.28))}
    #auraIntro .intro-particles{position:absolute;inset:-28%;pointer-events:none;background-image:radial-gradient(circle,rgba(120,239,250,.85) 0 1px,transparent 1.8px),radial-gradient(circle,rgba(120,239,250,.5) 0 1px,transparent 1.9px);background-size:43px 39px,73px 67px;background-position:12px 19px,35px 4px;opacity:0;animation:introParticles 3s ease-out .55s forwards}
    #auraIntro .intro-shards{position:absolute;inset:-18%;border-radius:50%;background:conic-gradient(from 20deg,transparent 0 12%,rgba(98,229,242,.3) 13%,transparent 15% 32%,rgba(98,229,242,.22) 33%,transparent 35% 63%,rgba(98,229,242,.26) 64%,transparent 66% 100%);filter:blur(1px);opacity:0;animation:introShards 3.05s cubic-bezier(.2,.7,.2,1) .7s forwards}
    #auraIntro .intro-status{position:absolute;bottom:7.5vh;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:9px;color:#71959f;font:500 9px/1 'DM Mono',monospace;letter-spacing:.18em;text-transform:uppercase;white-space:nowrap;opacity:0;animation:introStatus .7s ease 1.05s forwards}
    #auraIntro .intro-status i{width:5px;height:5px;border-radius:50%;background:#62e5f2;box-shadow:0 0 12px rgba(98,229,242,.9);animation:introDot 1s ease-in-out infinite}
    .app.aura-intro-reveal .rail{animation:introUiIn .75s cubic-bezier(.16,1,.3,1) both}
    .app.aura-intro-reveal main{animation:introUiIn .9s cubic-bezier(.16,1,.3,1) .08s both}
    @keyframes auraIntroIn{0%{opacity:0;filter:blur(12px);transform:scale(.72)}65%{opacity:1;filter:blur(0);transform:scale(1.04)}100%{opacity:1;filter:blur(0);transform:scale(1)}}
    @keyframes introGlow{0%,100%{transform:scale(.9);opacity:.45}50%{transform:scale(1.1);opacity:1}}
    @keyframes introParticles{0%{opacity:0;transform:scale(.65) rotate(0)}28%{opacity:.65}62%{opacity:.3;transform:scale(1.03) rotate(18deg)}100%{opacity:0;transform:scale(1.25) rotate(38deg)}}
    @keyframes introShards{0%{opacity:0;transform:scale(.45) rotate(-25deg)}35%{opacity:.5}68%{opacity:.22;transform:scale(1.08) rotate(18deg)}100%{opacity:0;transform:scale(1.5) rotate(55deg)}}
    @keyframes introStatus{to{opacity:1}}
    @keyframes introDot{50%{opacity:.35;transform:scale(.7)}}
    @keyframes introUiIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
    @media (prefers-reduced-motion:reduce){#auraIntro .intro-aura,#auraIntro .intro-particles,#auraIntro .intro-shards,#auraIntro .intro-status{animation:none!important;opacity:1;filter:none;transform:none}.app.aura-intro-reveal .rail,.app.aura-intro-reveal main{animation:none!important}}
    @media (max-width:600px){#auraIntro .intro-aura{width:min(260px,64vw)}#auraIntro .intro-status{bottom:6vh;font-size:8px}}
  `;
  document.head.appendChild(style);
  const intro=document.createElement('div');
  intro.id='auraIntro';
  intro.setAttribute('aria-label','AURA AI iniciando');
  intro.innerHTML=`<div class="intro-aura"><div class="intro-shards"></div><div class="intro-particles"></div><img src="aura-logo-real.jpeg?v=2" alt="AURA AI — Inteligência Artificial"></div><div class="intro-status"><i></i><span>Intelligence engine initializing</span></div>`;
  document.body.appendChild(intro);
  const app=document.querySelector('.app');
  window.setTimeout(()=>{if(app)app.classList.add('aura-intro-reveal');intro.classList.add('is-leaving');window.setTimeout(()=>intro.remove(),1050)},3400);
})();
