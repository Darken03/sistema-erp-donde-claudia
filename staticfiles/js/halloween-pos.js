/* Halloween POS: risita de bruja sintetizada + lluvia de emojis.
   Sin archivos de audio: WebAudio la genera (funciona offline).
   Se dispara al mostrarse el ticket (ventas online y offline).
   Clic en la guirnalda = silenciar/activar (se recuerda). */
(function(){
  var KEY = 'bizm_hwn_sound';
  function enabled(){
    try { return localStorage.getItem(KEY) !== 'off'; } catch(e){ return true; }
  }
  function setEnabled(v){
    try { localStorage.setItem(KEY, v ? 'on' : 'off'); } catch(e){}
  }

  /* Risita de bruja: 5 "ji" descendentes con vibrato, onda triangular. */
  function hwnLaugh(){
    if (!enabled()) return;
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      var ctx = new AC();
      if (ctx.state === 'suspended'){ ctx.resume(); }
      var t0 = ctx.currentTime + 0.05;
      var base = [660, 620, 580, 520, 440];
      base.forEach(function(f, i){
        var o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'triangle';
        o.frequency.setValueAtTime(f, t0 + i * 0.16);
        o.frequency.linearRampToValueAtTime(f * 0.82, t0 + i * 0.16 + 0.13);
        g.gain.setValueAtTime(0.0001, t0 + i * 0.16);
        g.gain.exponentialRampToValueAtTime(0.35, t0 + i * 0.16 + 0.02);
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + i * 0.16 + 0.15);
        o.connect(g); g.connect(ctx.destination);
        o.start(t0 + i * 0.16); o.stop(t0 + i * 0.16 + 0.17);
      });
      /* Campanazo final grave y burlón. */
      var o2 = ctx.createOscillator(), g2 = ctx.createGain();
      o2.type = 'sine';
      o2.frequency.setValueAtTime(220, t0 + 0.85);
      o2.frequency.linearRampToValueAtTime(110, t0 + 1.15);
      g2.gain.setValueAtTime(0.0001, t0 + 0.85);
      g2.gain.exponentialRampToValueAtTime(0.3, t0 + 0.87);
      g2.gain.exponentialRampToValueAtTime(0.0001, t0 + 1.2);
      o2.connect(g2); g2.connect(ctx.destination);
      o2.start(t0 + 0.85); o2.stop(t0 + 1.25);
      setTimeout(function(){ try { ctx.close(); } catch(e){} }, 1500);
    } catch(e){}
  }

  /* Lluvia de emojis dentro del POS. */
  function hwnRain(){
    try {
      var shell = document.getElementById('posShell');
      if (!shell) return;
      var faces = ['🎃','👻','🦇','🍬','🕷️','🍭'];
      for (var i = 0; i < 14; i++){
        (function(i){
          var s = document.createElement('span');
          s.className = 'hwn-float';
          s.textContent = faces[i % faces.length];
          s.style.left = (4 + Math.random() * 92) + '%';
          s.style.animationDelay = (Math.random() * 0.6) + 's';
          s.style.fontSize = (16 + Math.random() * 18) + 'px';
          shell.appendChild(s);
          setTimeout(function(){ s.remove(); }, 3200);
        })(i);
      }
    } catch(e){}
  }

  function hwnCelebrate(){ hwnLaugh(); hwnRain(); }
  window.hwnCelebrate = hwnCelebrate;

  document.addEventListener('DOMContentLoaded', function(){
    var modal = document.getElementById('ticketModal');
    if (modal){
      modal.addEventListener('shown.bs.modal', hwnCelebrate);
    }
    var gar = document.querySelector('.hwn-garland');
    if (gar){
      gar.style.cursor = 'pointer';
      gar.title = 'Clic para activar/silenciar el sonido de Halloween';
      const paint = () => { gar.style.opacity = enabled() ? '1' : '0.35'; };
      gar.addEventListener('click', function(){ setEnabled(!enabled()); paint(); });
      paint();
    }
  });
})();
