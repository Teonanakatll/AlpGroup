/*
 * Небольшой скрипт интерфейса. Без библиотек, работает и без него (страницы остаются читаемыми).
 *  - переключение темы summit / nexora (запоминается в браузере)
 *  - подсветка карточки под курсором
 *  - числа «набегают» от нуля
 *  - всплывающие сообщения (window.toast), сообщения Django показываются так же
 *  - плавный скролл колесом мыши (инерция, как у Lenis / Locomotive Scroll)
 *  - меню на телефоне, клавиша "/" ставит курсор в поиск
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- Тема -------------------------------------------------------------
  function setTheme(name) {
    root.dataset.theme = name;
    try { localStorage.setItem("theme", name); } catch (e) { /* приватный режим: не страшно */ }
  }
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-theme-toggle]");
    if (!button) return;
    setTheme(root.dataset.theme === "nexora" ? "summit" : "nexora");
  });

  // ---- Подсветка под курсором ------------------------------------------
  document.addEventListener("pointermove", function (event) {
    var card = event.target.closest(".card");
    if (!card) return;
    var rect = card.getBoundingClientRect();
    card.style.setProperty("--mx", (event.clientX - rect.left) + "px");
    card.style.setProperty("--my", (event.clientY - rect.top) + "px");
  }, { passive: true });

  // ---- Плавный скролл колесом -------------------------------------------
  // Тот же принцип, что у Lenis (на нём построен Locomotive Scroll v5): колесо двигает не страницу,
  // а «цель», а страница плавно догоняет её. Тачпады и телефоны не трогаем (у них своя инерция),
  // так же как внутренние прокручиваемые блоки и режим «уменьшить движение».
  (function smoothScroll() {
    if (reduceMotion) return;
    var target = window.scrollY, current = target, running = false, ease = 0.11;

    function limit(value) {
      return Math.max(0, Math.min(value, document.documentElement.scrollHeight - window.innerHeight));
    }
    function scrollableInside(node) {            // внутри блока со своей прокруткой колесо не перехватываем
      for (; node && node !== document.body; node = node.parentElement) {
        var overflow = getComputedStyle(node).overflowY;
        if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight) return true;
      }
      return false;
    }
    function frame() {
      current += (target - current) * ease;
      if (Math.abs(target - current) < 0.4) { current = target; running = false; }
      window.scrollTo(0, current);
      if (running) requestAnimationFrame(frame);
    }

    window.addEventListener("wheel", function (event) {
      if (event.defaultPrevented || event.ctrlKey || event.deltaX !== 0 && Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
      if (document.body.classList.contains("nav-open") || scrollableInside(event.target)) return;
      if (event.deltaMode === 0 && Math.abs(event.deltaY) < 40) return;     // мелкие шаги тачпада: уже плавно
      event.preventDefault();
      if (!running) { target = current = window.scrollY; }
      var step = event.deltaMode === 1 ? event.deltaY * 32 : event.deltaY;
      target = limit(target + step);
      if (!running) { running = true; requestAnimationFrame(frame); }
    }, { passive: false });

    // Прокрутили иначе (клавиши, полоса, якорь): цель берём из реального положения
    window.addEventListener("scroll", function () { if (!running) { target = current = window.scrollY; } }, { passive: true });
  })();

  // ---- Счётчики ---------------------------------------------------------
  function countUp(element) {
    var target = parseInt(element.dataset.count, 10);
    if (isNaN(target) || reduceMotion) return;
    var duration = 1100;
    var start = null;
    function frame(now) {
      if (start === null) start = now;
      var progress = Math.min((now - start) / duration, 1);
      var eased = 1 - Math.pow(1 - progress, 3);   // замедление к концу
      element.textContent = Math.round(target * eased);
      if (progress < 1) requestAnimationFrame(frame);
    }
    element.textContent = "0";
    requestAnimationFrame(frame);
  }

  // ---- Всплывающие сообщения -------------------------------------------
  var TTL = 5000;
  var ICON_OK = '<svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>';
  var ICON_X = '<svg class="icon" aria-hidden="true"><use href="#i-x"/></svg>';

  function dismiss(toast) {
    if (!toast || toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    setTimeout(function () { toast.remove(); }, 400);
  }

  function arm(toast) {
    toast.style.setProperty("--ttl", TTL + "ms");
    var timer = setTimeout(function () { dismiss(toast); }, TTL);
    toast.addEventListener("click", function (event) {
      if (event.target.closest("[data-toast-close]")) { clearTimeout(timer); dismiss(toast); }
    });
  }

  window.toast = function (message, level) {
    var box = document.getElementById("toasts");
    if (!box) return;
    var toast = document.createElement("div");
    toast.className = "toast toast--" + (level || "success");
    toast.setAttribute("role", "status");
    toast.innerHTML =
      '<span class="toast-icon">' + ICON_OK + "</span>" +
      '<span class="toast-text"></span>' +
      '<button type="button" class="toast-close" data-toast-close aria-label="Закрыть">' + ICON_X + "</button>";
    toast.querySelector(".toast-text").textContent = message;   // textContent: без HTML-вставки
    box.appendChild(toast);
    arm(toast);
  };

  // ---- Меню на телефоне, поиск по клавише "/" ---------------------------
  document.addEventListener("click", function (event) {
    if (event.target.closest("[data-nav-toggle]")) document.body.classList.toggle("nav-open");
    else if (event.target.closest(".scrim")) document.body.classList.remove("nav-open");
  });
  document.addEventListener("keydown", function (event) {
    var tag = (event.target.tagName || "").toLowerCase();
    if (event.key === "/" && tag !== "input" && tag !== "textarea" && tag !== "select") {
      var search = document.querySelector(".search input");
      if (search) { event.preventDefault(); search.focus(); }
    }
    if (event.key === "Escape") document.body.classList.remove("nav-open");
  });

  // ---- Старт ------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-count]").forEach(countUp);
    document.querySelectorAll("#toasts .toast").forEach(arm);   // сообщения от Django
  });
})();
