/* AURA AI — cinematic product intro */
(()=>{
  'use strict';
  if(document.getElementById('auraIntro')) return;

  const style=document.createElement('style');
  style.id='auraIntroStyles';
  style.textContent=`
    #auraIntro{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:radial-gradient(circle at 50% 46%,rgba(9,54,67,.34),rgba(2,8,13,.97) 58%,#02070b 100%);overflow:hidden;opacity:1;transition:opacity .9s cubic-bezier(.2,.7,.2,1),visibility .9s}
    #auraIntro.is-leaving{opacity:0;visibility:hidden;pointer-events:none}
    #auraIntro .intro-aura{position:relative;width:min(410px,72vw);aspect-ratio:300/265;display:grid;place-items:center;transform:scale(.94);opacity:0;filter:blur(10px);animation:auraIntroIn 1.45s cubic-bezier(.16,1,.3,1) .15s forwards}
    #auraIntro .intro-aura:before{content:"";position:absolute;width:74%;height:74%;border-radius:50%;background:radial-gradient(circle,rgba(86,232,245,.15),rgba(86,232,245,0) 68%);filter:blur(12px);animation:introGlow 2.8s ease-in-out infinite}
    #auraIntro img{position:relative;width:100%;height:100%;object-fit:contain;filter:drop-shadow(0 0 22px rgba(81,226,241,.16))}
    #auraIntro .intro-particles{position:absolute;inset:-16%;pointer-events:none;background-image:radial-gradient(circle,rgba(120,239,250,.8) 0 1px,transparent 1.7px),radial-gradient(circle,rgba(120,239,250,.42) 0 1px,transparent 1.8px);background-size:53px 47px,87px 71px;background-position:12px 19px,35px 4px;opacity:0;animation:introParticles 2.9s ease-out .65s forwards}
    #auraIntro .intro-status{position:absolute;bottom:7.5vh;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:9px;color:#71959f;font:500 9px/1 'DM Mono',monospace;letter-spacing:.18em;text-transform:uppercase;white-space:nowrap;opacity:0;animation:introStatus .7s ease 1.05s forwards}
    #auraIntro .intro-status i{width:5px;height:5px;border-radius:50%;background:#62e5f2;box-shadow:0 0 12px rgba(98,229,242,.9);animation:introDot 1s ease-in-out infinite}
    .app.aura-intro-reveal .rail{animation:introUiIn .75s cubic-bezier(.16,1,.3,1) both}
    .app.aura-intro-reveal main{animation:introUiIn .9s cubic-bezier(.16,1,.3,1) .08s both}
    @keyframes auraIntroIn{to{opacity:1;filter:blur(0);transform:scale(1)}}
    @keyframes introGlow{0%,100%{transform:scale(.9);opacity:.55}50%{transform:scale(1.08);opacity:1}}
    @keyframes introParticles{0%{opacity:0;transform:scale(.75)}35%{opacity:.45}75%{opacity:.2;transform:scale(1.06)}100%{opacity:0;transform:scale(1.16)}}
    @keyframes introStatus{to{opacity:1}}
    @keyframes introDot{50%{opacity:.35;transform:scale(.7)}}
    @keyframes introUiIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
    @media (prefers-reduced-motion:reduce){#auraIntro .intro-aura,#auraIntro .intro-particles,#auraIntro .intro-status{animation:none!important;opacity:1;filter:none;transform:none}.app.aura-intro-reveal .rail,.app.aura-intro-reveal main{animation:none!important}}
    @media (max-width:600px){#auraIntro .intro-aura{width:min(340px,78vw)}#auraIntro .intro-status{bottom:6vh;font-size:8px}}
  `;
  document.head.appendChild(style);

  const intro=document.createElement('div');
  intro.id='auraIntro';
  intro.setAttribute('aria-label','AURA AI iniciando');
  intro.innerHTML=`<div class="intro-aura"><div class="intro-particles"></div><img src="aura-logo.svg" alt="AURA AI — Inteligência Artificial"></div><div class="intro-status"><i></i><span>Intelligence engine initializing</span></div>`;
  document.body.appendChild(intro);
  const app=document.querySelector('.app');
  window.setTimeout(()=>{if(app)app.classList.add('aura-intro-reveal');intro.classList.add('is-leaving');window.setTimeout(()=>intro.remove(),950)},3100);
})();
