/* ============================================================================
   СКГВХ — клиентские скрипты (ревизия 2)
   Ванильный JS, без зависимостей. Каждый модуль независим и молча
   выключается, если разметки нет. Всё уважает prefers-reduced-motion.
   ========================================================================= */
(function () {
  'use strict';

  var root = document.documentElement;
  root.classList.add('js');

  var reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $  = function (s, c) { return (c || document).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || document).querySelectorAll(s)); };

  /* ── Мобильное меню ───────────────────────────────────────────────────── */
  function initNav() {
    var burger = $('.burger');
    var nav = $('#site-nav');
    if (!burger || !nav) return;

    function setOpen(open) {
      burger.setAttribute('aria-expanded', String(open));
      nav.classList.toggle('is-open', open);
    }

    burger.addEventListener('click', function () {
      setOpen(burger.getAttribute('aria-expanded') !== 'true');
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && burger.getAttribute('aria-expanded') === 'true') {
        setOpen(false);
        burger.focus();
      }
    });

    nav.addEventListener('focusout', function (e) {
      if (!nav.contains(e.relatedTarget)) setOpen(false);
    });

    var desktop = window.matchMedia('(min-width: 1025px)');
    var onChange = function (m) { if (m.matches) setOpen(false); };
    if (desktop.addEventListener) desktop.addEventListener('change', onChange);
    else desktop.addListener(onChange);
  }

  /* ── Шапка, кнопка «наверх», прогресс прокрутки ───────────────────────── */
  function initScrollChrome() {
    var header = $('.site-header');
    var toTop = $('.to-top');
    var bar = $('.scroll-progress__bar');
    if (!header && !toTop && !bar) return;

    var ticking = false;

    function update() {
      var y = window.pageYOffset;
      var vh = window.innerHeight || 1;

      if (header) header.classList.toggle('is-stuck', y > 16);
      if (toTop) toTop.classList.toggle('is-visible', y > vh * .8);

      if (bar) {
        var max = document.documentElement.scrollHeight - vh;
        var p = max > 0 ? Math.min(1, y / max) : 0;
        bar.style.transform = 'scaleX(' + p.toFixed(4) + ')';
      }
      ticking = false;
    }

    window.addEventListener('scroll', function () {
      if (!ticking) { window.requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    update();
  }

  /* ── Плавный скролл к якорям ──────────────────────────────────────────── */
  function initAnchors() {
    document.addEventListener('click', function (e) {
      var link = e.target.closest ? e.target.closest('a[href^="#"]') : null;
      if (!link) return;

      var id = link.getAttribute('href');
      if (!id || id === '#' || link.classList.contains('skip-link')) return;

      var target = document.getElementById(id.slice(1));
      if (!target) return;

      e.preventDefault();
      target.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
      target.setAttribute('tabindex', '-1');
      target.focus({ preventScroll: true });
      if (history.replaceState) history.replaceState(null, '', id);
    });
  }

  /* ── Появление блоков при прокрутке ───────────────────────────────────── */
  function initReveal() {
    var items = $$('[data-reveal]');
    if (!items.length) return;

    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach(function (el) { el.classList.add('is-in'); });
      return;
    }

    // Каскад внутри группы: элементы появляются по очереди
    $$('[data-reveal-group]').forEach(function (group) {
      $$('[data-reveal]', group).forEach(function (el, i) {
        el.style.setProperty('--reveal-delay', Math.min(i * 80, 480) + 'ms');
      });
    });

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-in');
        io.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px -7% 0px', threshold: .08 });

    items.forEach(function (el) { io.observe(el); });
  }

  /* ── Появление заголовка по словам ───────────────────────────────────── */
  /* Оборачиваем слова в <span class="split-word"> с нарастающей задержкой.
     Текст остаётся доступным для скринридеров: элементы — инлайновые,
     между ними сохраняются пробелы. */
  function initSplitText() {
    var targets = $$('[data-split]');
    if (!targets.length) return;

    targets.forEach(function (el) {
      if (el.dataset.splitDone) return;

      if (reduceMotion) {
        el.dataset.splitDone = '1';
        return;
      }

      var words = el.textContent.trim().split(/\s+/);
      el.textContent = '';

      words.forEach(function (w, i) {
        var s = document.createElement('span');
        s.className = 'split-word';
        s.style.setProperty('--hero-i', i);
        s.textContent = w;
        el.appendChild(s);
        if (i < words.length - 1) el.appendChild(document.createTextNode(' '));
      });
      el.dataset.splitDone = '1';
    });
  }

  /* ── Счётчики ────────────────────────────────────────────────────────── */
  function initCounters() {
    var els = $$('[data-count]');
    if (!els.length) return;

    function animate(el) {
      var raw = el.getAttribute('data-count');
      var target = parseFloat(raw);
      var prefix = el.getAttribute('data-prefix') || '';
      var suffix = el.getAttribute('data-suffix') || '';
      var dur = parseInt(el.getAttribute('data-duration'), 10) || 1500;

      // Нечисловые значения (№100-39, ISO 9001) показываем как есть
      if (isNaN(target)) { el.textContent = prefix + el.textContent + suffix; return; }
      if (reduceMotion) { el.textContent = prefix + target + suffix; return; }

      var start = performance.now();
      function frame(now) {
        var p = Math.min((now - start) / dur, 1);
        var eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);   // easeOutExpo
        el.textContent = prefix + Math.round(target * eased) + suffix;
        if (p < 1) requestAnimationFrame(frame);
      }
      requestAnimationFrame(frame);
    }

    if (!('IntersectionObserver' in window)) { els.forEach(animate); return; }

    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        animate(entry.target);
        io.unobserve(entry.target);
      });
    }, { threshold: .45 });

    els.forEach(function (el) { io.observe(el); });
  }

  /* ── Параллакс фона hero ──────────────────────────────────────────────── */
  function initParallax() {
    var layers = $$('[data-parallax]');
    if (!layers.length || reduceMotion) return;

    var ticking = false;

    function update() {
      var vh = window.innerHeight;
      layers.forEach(function (layer) {
        var speed = parseFloat(layer.getAttribute('data-parallax')) || 0.2;
        var rect = layer.parentElement.getBoundingClientRect();
        var center = rect.top + rect.height / 2 - vh / 2;
        layer.style.transform = 'translate3d(0,' + (center * speed).toFixed(2) + 'px,0)';
      });
      ticking = false;
    }

    window.addEventListener('scroll', function () {
      if (!ticking) { requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    window.addEventListener('resize', update, { passive: true });
    update();
  }

  /* ── Пятно света и блик, следующие за курсором ──────────────────────── */
  /* Два эффекта сразу: у .card/.metric — мягкое пятно, у .glass — узкий
     блик по кромке. Оба пишут координаты в CSS-переменные, а саму анимацию
     делает CSS. Запись идёт через rAF, иначе pointermove дёргает стиль
     на каждое событие мыши. */
  function initPointerGlow() {
    if (reduceMotion) return;
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;

    var cards = $$('.card, .metric');
    var glasses = $$('.glass');

    var pending = null;
    var x = 0, y = 0;

    function flush() {
      pending = null;
      for (var i = 0; i < cards.length; i++) {
        var r = cards[i].getBoundingClientRect();
        cards[i].style.setProperty('--mx', ((x - r.left) / r.width * 100).toFixed(1) + '%');
        cards[i].style.setProperty('--my', ((y - r.top) / r.height * 100).toFixed(1) + '%');
      }
      for (var j = 0; j < glasses.length; j++) {
        var g = glasses[j].getBoundingClientRect();
        glasses[j].style.setProperty('--gx', ((x - g.left) / g.width * 100).toFixed(1) + '%');
        glasses[j].style.setProperty('--gy', ((y - g.top) / g.height * 100).toFixed(1) + '%');
      }
    }

    window.addEventListener('pointermove', function (e) {
      x = e.clientX;
      y = e.clientY;
      if (pending === null) { pending = requestAnimationFrame(flush); }
    }, { passive: true });
  }

  /* ── Раскрытие карточек услуг ────────────────────────────────────────── */
  function initServiceCards() {
    $$('[data-expand]').forEach(function (btn) {
      var card = btn.closest('.service-card');
      if (!card) return;
      btn.addEventListener('click', function () {
        var open = card.classList.toggle('is-open');
        btn.setAttribute('aria-expanded', String(open));
        var label = btn.querySelector('[data-expand-label]');
        if (label) label.textContent = open ? 'Свернуть' : 'Подробнее';
      });
    });
  }

  /* ── Аккордеон: не более одной открытой секции ───────────────────────── */
  function initAccordion() {
    var items = $$('.acc__item');
    if (!items.length) return;

    items.forEach(function (item) {
      var summary = $('.acc__summary', item);
      if (!summary) return;
      summary.addEventListener('click', function (e) {
        e.preventDefault();
        var willOpen = !item.hasAttribute('open');
        items.forEach(function (other) {
          other.removeAttribute('open');
          var s = $('.acc__summary', other);
          if (s) s.setAttribute('aria-expanded', 'false');
        });
        if (willOpen) {
          item.setAttribute('open', '');
          summary.setAttribute('aria-expanded', 'true');
        }
      });
    });
  }

  /* ── Lightbox галереи ─────────────────────────────────────────────────── */
  function initLightbox() {
    var items = $$('[data-lightbox]');
    if (!items.length) return;

    var box = document.createElement('div');
    box.className = 'lightbox';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', 'Просмотр изображения');
    box.innerHTML =
      '<button class="lightbox__close" type="button" aria-label="Закрыть">' +
      '<svg class="icon" aria-hidden="true" focusable="false"><use href="#i-close"></use></svg></button>' +
      '<figure style="margin:0;display:grid;place-items:center">' +
      '<img class="lightbox__img" alt="">' +
      '<figcaption class="lightbox__cap"></figcaption></figure>';
    document.body.appendChild(box);

    var img = $('.lightbox__img', box);
    var cap = $('.lightbox__cap', box);
    var closeBtn = $('.lightbox__close', box);
    var lastFocused = null;

    function open(item) {
      lastFocused = document.activeElement;
      img.src = item.getAttribute('data-lightbox');
      img.alt = item.getAttribute('data-alt') || '';
      cap.textContent = item.getAttribute('data-caption') || '';
      box.classList.add('is-open');
      document.body.style.overflow = 'hidden';
      closeBtn.focus();
    }

    function close() {
      box.classList.remove('is-open');
      document.body.style.overflow = '';
      if (lastFocused) lastFocused.focus();
    }

    items.forEach(function (item) {
      item.addEventListener('click', function () { open(item); });
      item.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(item); }
      });
    });

    closeBtn.addEventListener('click', close);
    box.addEventListener('click', function (e) { if (e.target === box) close(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && box.classList.contains('is-open')) close();
    });
  }

  /* ── Копирование реквизитов ──────────────────────────────────────────── */
  function initCopy() {
    $$('[data-copy]').forEach(function (el) {
      el.addEventListener('click', function () {
        var text = el.getAttribute('data-copy');
        if (!text || !navigator.clipboard) return;
        navigator.clipboard.writeText(text).then(function () {
          var old = el.querySelector('[data-copy-label]');
          if (!old) return;
          var prev = old.textContent;
          old.textContent = 'Скопировано';
          setTimeout(function () { old.textContent = prev; }, 1400);
        }).catch(function () { /* нет доступа к буферу — игнорируем */ });
      });
    });
  }

  /* ── Отметка активного раздела ───────────────────────────────────────── */
  function initActiveLink() {
    var here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
    $$('.nav__link').forEach(function (link) {
      var href = (link.getAttribute('href') || '').split('/').pop().toLowerCase();
      if (href === here) {
        link.classList.add('is-active');
        link.setAttribute('aria-current', 'page');
      }
    });
  }

  /* ── Согласие на cookie и отложенная загрузка счётчика ───────────────── */
  var CONSENT_KEY = 'skgvh_consent';

  function initConsent() {
    var banner = $('#consent');
    var previous = readConsent();

    if (previous) {
      if (window.__skgvhMetrika) window.__skgvhMetrika(previous);
      return;
    }
    if (!banner) return;

    // Небольшая задержка, чтобы баннер не перехватывал фокус при загрузке
    setTimeout(function () {
      banner.hidden = false;
      requestAnimationFrame(function () { banner.classList.add('is-open'); });
    }, 1100);

    $$('[data-consent]', banner).forEach(function (btn) {
      btn.addEventListener('click', function () {
        var mode = btn.getAttribute('data-consent');
        try { window.localStorage.setItem(CONSENT_KEY, mode); } catch (e) { /* приватный режим */ }
        banner.classList.remove('is-open');
        setTimeout(function () { banner.hidden = true; }, 320);
        if (window.__skgvhMetrika) window.__skgvhMetrika(mode);
      });
    });
  }

  function readConsent() {
    try { return window.localStorage.getItem(CONSENT_KEY); }
    catch (e) { return null; }
  }

  /* ── Запуск ───────────────────────────────────────────────────────────── */
  function boot() {
    initNav();
    initScrollChrome();
    initAnchors();
    initReveal();
    initSplitText();
    initCounters();
    initParallax();
    initPointerGlow();
    initServiceCards();
    initAccordion();
    initLightbox();
    initCopy();
    initActiveLink();
    initConsent();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();