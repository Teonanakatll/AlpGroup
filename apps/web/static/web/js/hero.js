/* Герой главной: параллакс. Задний план (фото) двигается слабо, средний (текст и кнопка) чуть сильнее,
   ближний (логотип) сильнее всех. Блики логотипа считает logo3d.js, здесь только движение. */
(function () {
  "use strict";

  var hero = document.querySelector("[data-parallax]");
  if (!hero) return;

  var still = document.documentElement.dataset.motion === "reduced";   // флаг из настроек сайта (DECISIONS §18)
  if (still) return;                                                    // без движения оставляем всё на месте

  var layers = Array.prototype.slice.call(hero.querySelectorAll("[data-depth]"));
  var SHIFT = 6;                                           // px на единицу глубины при крайнем положении курсора
  var target = { x: 0, y: 0 };                             // куда тянется курсор, -1..1
  var cur = { x: 0, y: 0 };                                // сглаженное положение
  var hasPointer = false, visible = true, raf = 0;

  hero.addEventListener("pointermove", function (e) {
    var r = hero.getBoundingClientRect();
    target.x = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1));
    target.y = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height) * 2 - 1));
    hasPointer = true;
    kick();
  });
  hero.addEventListener("pointerleave", function () { hasPointer = false; kick(); });

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (en) {
      visible = en[0].isIntersecting;
      if (visible) kick();
    }).observe(hero);
  }

  function kick() { if (!raf && visible) raf = requestAnimationFrame(frame); }

  function frame(t) {
    raf = 0;
    if (!visible) return;
    if (!hasPointer) { target.x = 0; target.y = 0; }       // курсор ушёл: плавно возвращаемся в центр
    // чем меньше коэффициент, тем плавнее и «тяжелее» движение
    cur.x += (target.x - cur.x) * 0.035;
    cur.y += (target.y - cur.y) * 0.035;

    layers.forEach(function (el) {
      var d = parseFloat(el.dataset.depth) || 0;
      var x = -cur.x * d * SHIFT, y = -cur.y * d * SHIFT * 0.6;
      var tf = "translate3d(" + x.toFixed(2) + "px," + y.toFixed(2) + "px,0)";
      if (el.classList.contains("logo3d")) {               // логотип ещё и слегка наклоняется к курсору
        tf += " perspective(700px) rotateY(" + (cur.x * 3).toFixed(2) + "deg) rotateX(" + (-cur.y * 2).toFixed(2) + "deg)";
      }
      el.style.transform = tf;
    });
    // дошли до цели: цикл не нужен, проснёмся от следующего движения мыши
    if (Math.abs(target.x - cur.x) > 0.0005 || Math.abs(target.y - cur.y) > 0.0005) raf = requestAnimationFrame(frame);
  }

  kick();
})();
