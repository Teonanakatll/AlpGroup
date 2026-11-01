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

  // ---- Формы выдачи и приёма -------------------------------------------
  // Подсвечивает выбранные строки, считает выбранное, не даёт ввести больше максимума,
  // фильтрует список по названию. Вызывается и после того, как HTMX подменил блок позиций.
  function updatePicks() {
    var form = document.querySelector(".op-form");
    if (!form) return;
    var count = 0;
    form.querySelectorAll(".pick").forEach(function (row) {
      var box = row.querySelector('input[type="checkbox"]');
      var qty = row.querySelector('input[type="number"]');
      var on = false;
      if (box) {
        on = box.checked;
      } else if (qty) {
        var max = parseInt(qty.max, 10), value = parseInt(qty.value, 10);
        if (!isNaN(value) && !isNaN(max) && value > max) { qty.value = max; value = max; }
        on = !isNaN(value) && value > 0;
        // Стрелки выключаются на границах: ниже нуля и выше остатка не уйти
        row.querySelectorAll("[data-qty-step]").forEach(function (button) {
          var current = isNaN(value) ? 0 : value;
          button.disabled = button.dataset.qtyStep < 0 ? current <= 0 : (!isNaN(max) && current >= max);
        });
      }
      row.classList.toggle("is-selected", on);
      if (on) count += 1;
    });
    form.querySelectorAll("[data-pick-count]").forEach(function (el) { el.textContent = count; });
    var submit = form.querySelector("[data-pick-submit]");
    if (submit) submit.disabled = count === 0;
  }

  function filterPicks(input) {
    var query = input.value.trim().toLowerCase();
    input.closest(".op-form").querySelectorAll(".pick").forEach(function (row) {
      row.classList.toggle("is-hidden", query !== "" && row.dataset.name.indexOf(query) === -1);
    });
  }

  document.addEventListener("input", function (event) {
    if (event.target.matches("[data-pick-filter]")) filterPicks(event.target);
    else if (event.target.closest(".pick")) updatePicks();
  });
  document.addEventListener("change", function (event) {
    if (event.target.closest(".pick")) updatePicks();
    // Без HTMX (не загрузился с CDN) список для объекта берём обычным переходом
    if (event.target.matches("[data-site-select]") && !window.htmx) {
      window.location.search = "?site=" + encodeURIComponent(event.target.value);
    }
  });
  document.addEventListener("click", function (event) {        // стрелки у количества
    var button = event.target.closest("[data-qty-step]");
    if (!button) return;
    var input = button.parentElement.querySelector('input[type="number"]');
    var max = parseInt(input.max, 10), value = parseInt(input.value, 10) || 0;
    value = Math.max(0, Math.min(isNaN(max) ? Infinity : max, value + parseInt(button.dataset.qtyStep, 10)));
    input.value = value;
    markFilled(input);
    updatePicks();
  });
  document.addEventListener("keydown", function (event) {      // Enter в фильтре не отправляет форму
    if (event.key === "Enter" && event.target.matches("[data-pick-filter]")) event.preventDefault();
  });
  document.addEventListener("htmx:afterSwap", updatePicks);

  // ---- Свои выпадающие списки -----------------------------------------
  // Заменяют обычный <select> на список в стиле сайта. Сам select остаётся в форме (скрытый):
  // из него уходит значение, на нём слушает HTMX; при выборе ему посылается обычное событие change.
  function enhanceSelect(select) {
    if (select.dataset.dd || select.multiple) return;
    select.dataset.dd = "1";
    var wrap = document.createElement("div");
    wrap.className = "dd";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.classList.add("dd-native");

    var button = document.createElement("button");
    button.type = "button";
    button.className = "dd-btn";
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    if (select.id) { button.id = select.id; select.id += "_native"; }   // подпись «for» ведёт на кнопку
    button.innerHTML = '<span class="dd-label"></span><svg class="icon dd-caret" aria-hidden="true"><use href="#i-chevron-down"/></svg>';
    var label = button.firstChild;

    var panel = document.createElement("div");
    panel.className = "dd-panel";
    panel.setAttribute("role", "listbox");
    panel.setAttribute("data-lenis-prevent", "");      // колесо внутри списка крутит список, а не страницу
    var options = Array.prototype.map.call(select.options, function (option, index) {
      var item = document.createElement("div");
      item.className = "dd-opt" + (option.value === "" ? " is-empty" : "");
      item.setAttribute("role", "option");
      item.innerHTML = "<span></span>" + '<svg class="icon" aria-hidden="true"><use href="#i-check"/></svg>';
      item.firstChild.textContent = option.text;
      item.dataset.index = index;
      panel.appendChild(item);
      return item;
    });
    wrap.appendChild(button);
    wrap.appendChild(panel);

    var active = select.selectedIndex;
    function sync() {
      var chosen = select.options[select.selectedIndex];
      label.textContent = chosen ? chosen.text : "";
      var empty = (!chosen || chosen.value === "") && !select.hasAttribute("data-dd-keep");   // «Склад» это настоящий выбор
      button.classList.toggle("is-placeholder", empty);
      button.classList.toggle("is-filled", !empty);
      options.forEach(function (item, index) {
        item.setAttribute("aria-selected", index === select.selectedIndex ? "true" : "false");
      });
    }
    function highlight(index) {
      active = Math.max(0, Math.min(options.length - 1, index));
      options.forEach(function (item, i) { item.classList.toggle("is-active", i === active); });
      options[active].scrollIntoView({ block: "nearest" });
    }
    function isOpen() { return wrap.classList.contains("is-open"); }
    function open() {
      var rect = button.getBoundingClientRect();
      var below = window.innerHeight - rect.bottom, above = rect.top;
      wrap.classList.toggle("dd-up", below < 300 && above > below);     // мало места снизу: открываем вверх
      wrap.classList.add("is-open");
      button.setAttribute("aria-expanded", "true");
      highlight(select.selectedIndex < 0 ? 0 : select.selectedIndex);
    }
    function close() {
      wrap.classList.remove("is-open");
      button.setAttribute("aria-expanded", "false");
    }
    function choose(index) {
      var changed = select.selectedIndex !== index;
      select.selectedIndex = index;
      sync();
      close();
      button.focus();
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    button.addEventListener("click", function () { if (isOpen()) close(); else open(); });
    button.addEventListener("keydown", function (event) {
      var key = event.key;
      if (key === "ArrowDown" || key === "ArrowUp") {
        event.preventDefault();
        if (!isOpen()) open(); else highlight(active + (key === "ArrowDown" ? 1 : -1));
      } else if (key === "Home" || key === "End") {
        if (isOpen()) { event.preventDefault(); highlight(key === "Home" ? 0 : options.length - 1); }
      } else if (key === "Enter" || key === " ") {
        event.preventDefault();
        if (isOpen()) choose(active); else open();
      } else if (key === "Escape" || key === "Tab") {
        if (isOpen()) { if (key === "Escape") event.preventDefault(); close(); }
      } else if (key.length === 1) {                           // быстрый поиск по первой букве
        var found = options.findIndex(function (item, i) {
          return i !== active && item.textContent.toLowerCase().indexOf(key.toLowerCase()) === 0;
        });
        if (found >= 0) { if (!isOpen()) open(); highlight(found); }
      }
    });
    panel.addEventListener("mousemove", function (event) {
      var item = event.target.closest(".dd-opt");
      if (item) highlight(parseInt(item.dataset.index, 10));
    });
    panel.addEventListener("click", function (event) {
      var item = event.target.closest(".dd-opt");
      if (item) choose(parseInt(item.dataset.index, 10));
    });
    document.addEventListener("click", function (event) { if (isOpen() && !wrap.contains(event.target)) close(); });
    sync();
  }

  // Подсветка заполненных полей ввода (у выпадающих списков её ставит enhanceSelect)
  var FILLABLE = ".field input, .pick-head input, .qty input";
  function markFilled(input) {
    input.classList.toggle("is-filled", input.value.trim() !== "" && input.value !== "0");
  }
  document.addEventListener("input", function (event) {
    if (event.target.matches(FILLABLE)) markFilled(event.target);
  });
  function enhanceForms() {
    document.querySelectorAll("main select").forEach(enhanceSelect);
    document.querySelectorAll(FILLABLE).forEach(markFilled);
  }
  document.addEventListener("htmx:afterSwap", function () { document.querySelectorAll(FILLABLE).forEach(markFilled); });

  // ---- Старт ------------------------------------------------------------
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-count]").forEach(countUp);
    updatePicks();
    enhanceForms();
    document.querySelectorAll("#toasts .toast").forEach(arm);   // сообщения от Django
  });
})();

/* Кнопки с data-confirm: первое нажатие только «взводит» кнопку (текст меняется на вопрос),
   второе в течение 4 секунд отправляет форму. Без JS форма просто отправляется сразу. */
document.addEventListener("click", function (e) {
  var btn = e.target.closest("button[data-confirm]");
  if (!btn) return;
  if (btn.classList.contains("is-armed")) return;           // второй клик: пусть форма уйдёт
  e.preventDefault();
  var label = btn.textContent;
  btn.textContent = btn.dataset.confirm;
  btn.classList.add("is-armed");
  setTimeout(function () { btn.textContent = label; btn.classList.remove("is-armed"); }, 4000);
});
