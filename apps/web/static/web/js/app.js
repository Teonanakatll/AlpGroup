/*
 * Небольшой скрипт интерфейса. Без библиотек, работает и без него (страницы остаются читаемыми).
 *  - переключение темы summit / nexora (запоминается в браузере)
 *  - подсветка карточки под курсором
 *  - числа «набегают» от нуля
 *  - всплывающие сообщения (window.toast), сообщения Django показываются так же
 *  - плавный скролл (библиотека Lenis, на ней построен Locomotive Scroll v5)
 *  - меню на телефоне, клавиша "/" ставит курсор в поиск
 */
(function () {
  "use strict";

  var root = document.documentElement;
  var reduceMotion = root.dataset.motion === "reduced";   // только по явному выбору, не по флагу системы

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

  // ---- Плавный скролл (Lenis) -------------------------------------------
  // Lenis подключается в base.html с CDN. Если он не загрузился (нет интернета), страница
  // просто прокручивается обычным образом. На телефонах Lenis сам оставляет родную прокрутку.
  (function smoothScroll() {
    if (reduceMotion || typeof window.Lenis === "undefined") return;
    // duration: сколько длится «скольжение» после щелчка колеса (секунды); больше значит плавнее и дольше.
    var lenis = new window.Lenis({
      duration: 1.6,
      easing: function (t) { return Math.min(1, 1.001 - Math.pow(2, -10 * t)); },   // быстрый старт, долгое затухание
      wheelMultiplier: 1,
    });
    window.lenis = lenis;
    function raf(time) { lenis.raf(time); requestAnimationFrame(raf); }
    requestAnimationFrame(raf);
    // Пока открыто меню на телефоне, страница под ним не прокручивается
    new MutationObserver(function () {
      if (document.body.classList.contains("nav-open")) lenis.stop(); else lenis.start();
    }).observe(document.body, { attributes: true, attributeFilter: ["class"] });
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
