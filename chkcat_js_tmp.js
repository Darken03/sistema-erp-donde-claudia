
(function(){
  function norm(s){ return (s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,''); }
  var q = document.getElementById('q'), cat = '', sinRes = document.getElementById('sinRes');
  function filtrar(){
    var t = norm(q.value.trim()), vis = 0;
    document.querySelectorAll('.cat-sec').forEach(function(sec){
      var okCat = !cat || sec.getAttribute('data-cat') === cat, n = 0;
      sec.querySelectorAll('.card').forEach(function(c){
        var hit = okCat && (!t || norm(c.getAttribute('data-nombre')).indexOf(t) !== -1);
        c.style.display = hit ? '' : 'none'; if (hit) n++;
      });
      sec.style.display = n ? '' : 'none'; vis += n;
    });
    sinRes.style.display = vis ? 'none' : 'block';
  }
  q.addEventListener('input', filtrar);
  document.getElementById('chips').addEventListener('click', function(e){
    var b = e.target.closest('.chip'); if (!b) return;
    document.querySelectorAll('.chip').forEach(function(c){ c.classList.remove('active'); });
    b.classList.add('active'); cat = b.getAttribute('data-cat'); filtrar();
  });
})();
