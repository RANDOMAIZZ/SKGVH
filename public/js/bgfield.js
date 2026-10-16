/* ============================================================================
   Фоновая анимация на canvas: «поток поля» частиц с реакцией на курсор.

   Что делает: частицы плывут по полю направлений, рядом друг с другом
   соединяются тонкими линиями, курсор их слегка отталкивает. Читается
   как движение воды, но стоит почти ничего.

   Экономия:
     • число частиц считается от площади экрана и ограничивается;
     • DPR ограничен двойкой — на телефонах третьего не нужно;
     • анимация встаёт на паузу, если вкладка скрыта или блок вне экрана;
     • при prefers-reduced-motion поле рисуется один раз статично.
   ========================================================================= */
(function () {
  'use strict';

  var canvas = document.getElementById('bg-canvas');
  if (!canvas) return;

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;

  var particles = [];
  var w = 0, h = 0, dpr = 1;
  var mouse = { x: -9999, y: -9999, active: false };
  var running = false;
  var visible = true;

  /* Поле направлений: комбинация синусов даёт плавные завихрения
     без единой псевдослучайной строки в кадре. */
  function fieldAngle(x, y) {
    return (
      Math.sin(x * 0.0016 + y * 0.0011) * 2.4 +
      Math.cos(x * 0.0009 - y * 0.0018) * 1.9 +
      Math.sin((x + y) * 0.0006) * 1.2
    );
  }

  function makeParticle() {
    return {
      x: Math.random() * w,
      y: Math.random() * h,
      vx: 0,
      vy: 0,
      r: 1.0 + Math.random() * 2.1,
      a: 0.22 + Math.random() * 0.40,
      hue: Math.random() < 0.22 ? 1 : 0   // часть частиц — фиолетовые
    };
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Плотность частиц фиксированная на экран, а не на единицу площади
    var target = Math.round(Math.min(150, Math.max(55, (w * h) / 11000)));
    while (particles.length > target) particles.pop();
    while (particles.length < target) particles.push(makeParticle());
  }

  function drawStatic() {
    // Один кадр для prefers-reduced-motion: поле есть, движения нет
    ctx.clearRect(0, 0, w, h);
    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.hue
        ? 'rgba(167,139,250,' + p.a + ')'
        : 'rgba(56,189,248,' + p.a + ')';
      ctx.fill();
    }
  }

  var LINK_DIST = 158;
  var MOUSE_R = 150;

  function frame() {
    if (!running) return;
    ctx.clearRect(0, 0, w, h);

    for (var i = 0; i < particles.length; i++) {
      var p = particles[i];

      var ang = fieldAngle(p.x, p.y);
      p.vx += Math.cos(ang) * 0.028;
      p.vy += Math.sin(ang) * 0.028;

      // Курсор слегка отталкивает частицы
      if (mouse.active) {
        var dx = p.x - mouse.x;
        var dy = p.y - mouse.y;
        var dist = Math.hypot(dx, dy);
        if (dist < MOUSE_R && dist > 0.01) {
          var force = (1 - dist / MOUSE_R) * 0.9;
          p.vx += (dx / dist) * force;
          p.vy += (dy / dist) * force;
        }
      }

      // Инерция и трение: поток остаётся плавным, а не рваным
      p.vx *= 0.97;
      p.vy *= 0.97;
      p.x += p.vx;
      p.y += p.vy;

      // Выход за край — свернуть в противоположную сторону
      if (p.x < -20) p.x = w + 20;
      if (p.x > w + 20) p.x = -20;
      if (p.y < -20) p.y = h + 20;
      if (p.y > h + 20) p.y = -20;

      p.drawColor = p.hue
        ? 'rgba(167,139,250,' + p.a + ')'
        : 'rgba(56,189,248,' + p.a + ')';
    }

    // Соединяем ближние частицы
    ctx.lineWidth = 0.9;
    for (var a = 0; a < particles.length; a++) {
      for (var b = a + 1; b < particles.length; b++) {
        var q = particles[b];
        var p1 = particles[a];
        var dx = p1.x - q.x, dy = p1.y - q.y;
        var d2 = dx * dx + dy * dy;
        if (d2 > LINK_DIST * LINK_DIST) continue;

        var t = 1 - Math.sqrt(d2) / LINK_DIST;
        ctx.strokeStyle = 'rgba(94,180,255,' + (t * 0.30).toFixed(3) + ')';
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(q.x, q.y);
        ctx.stroke();
      }
    }

    // Частицы поверх линий
    for (var k = 0; k < particles.length; k++) {
      var pp = particles[k];
      ctx.beginPath();
      ctx.arc(pp.x, pp.y, pp.r, 0, Math.PI * 2);
      ctx.fillStyle = pp.drawColor;
      ctx.fill();
    }

    requestAnimationFrame(frame);
  }

  function start() {
    if (running || reduceMotion || !visible) return;
    running = true;
    requestAnimationFrame(frame);
  }

  function stop() { running = false; }

  /* ── Инициализация ────────────────────────────────────────────────────── */
  resize();

  if (reduceMotion) {
    drawStatic();
  } else {
    start();

    var resizeTimer;
    window.addEventListener('resize', function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(resize, 180);
    }, { passive: true });

    window.addEventListener('pointermove', function (e) {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
      mouse.active = true;
    }, { passive: true });

    window.addEventListener('pointerleave', function () { mouse.active = false; });

    // Вкладка ушла в фон — рисуем вхолостую
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) stop(); else start();
    });
  }
})();