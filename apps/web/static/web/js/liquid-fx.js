/* Заставка светлых тем (Nexora и других светлых): «жидкая» картинка с RGB-расслоением и помехами (WebGL, без библиотек).
   Повторяет эффект rgbKineticSlider (PixiJS + GSAP, ~600 КБ) одним шейдером, с теми же коэффициентами:
   - мышь без нажатия: картинка у курсора тянется за ним (радиальная линза), а вся картинка чуть
     проскальзывает вслед за мышью и пружинит обратно (по обеим осям);
   - зажать кнопку и тянуть (свайп): по картинке едет рваная карта смещения — края «текут» и бьются
     помехами, красный и голубой разъезжаются по скорости; протащить на 40% ширины — следующая картинка;
   - под самой линзой и без нажатия цвета чуть расходятся: в центре сильнее, к краю на нет (до 10 px);
   - клик по заставке, появление и смена картинок: переход — картинку рвёт по той же карте до 160 px
     и расслаивает до 80 px, потом она собирается.
   Рваную карту (блочный радиальный шум + кольца с резкими краями) считает сам шейдер, файлов-карт нет.
   Картинки любые (JPG, PNG, WebP): вписываются как object-fit: cover, слишком большие уменьшаются.
   Несколько картинок через «|» в data-images — клик и таймер переключают их;
   data-images-narrow — отдельный набор для узкого вертикального блока (телефон).
   Нет WebGL, «меньше движения» или другая тема — эффект не запускается, остаётся обычный фон темы. */
(function () {
  "use strict";

  var root = document.documentElement;
  var box = document.querySelector(".liquid");
  var canvas = box && box.querySelector(".liquid-fx");
  if (!canvas) return;
  var hero = box.closest(".hero") || box;

  // Для узкого вертикального блока (телефон) можно дать свой набор: широкая картинка там обрезалась бы до полоски
  function list(value) { return (value || "").split("|").filter(Boolean); }
  function sources() {                                   // выбираем при запуске: блок уже виден, размер известен
    var rect = box.getBoundingClientRect(), narrow = list(canvas.dataset.imagesNarrow);
    return narrow.length && rect.width < rect.height * 1.1 ? narrow : list(canvas.dataset.images);
  }
  if (!list(canvas.dataset.images).length && !list(canvas.dataset.imagesNarrow).length) return;

  // Коэффициенты как в настройках оригинала; все смещения в CSS-пикселях
  var SETTINGS = {
    momentum: 0.14,        // cursorMomentum: как быстро «точка» догоняет курсор (меньше — дольше хвост)
    cursorScale: 0.65,     // cursorScaleIntensity: насколько линза тянет картинку за мышью
    cursorRadius: 256,     // радиус линзы, px
    rgb: 0.9,              // imagesRgbIntensity: расслоение при свайпе = скорость мыши × это число
    rgbMax: 36,            // но не больше, px: иначе резкий рывок разводит цвета на сотни пикселей
    slip: 0.12,            // как сильно вся картинка проскальзывает за мышью (край карты линзы не серый)
    lensRgb: 0.4,          // небольшое расслоение под линзой без нажатия: в центре сильнее, к краю на нет
    lensRgbMax: 10,        // но не больше, px
    dragScale: 2,          // swipeScaleIntensity: сила рваной карты при свайпе
    swipeDistance: 0.4,    // протащить на эту долю ширины — переход на следующую картинку
    transitionScale: 160,  // transitionScaleAmplitude: насколько рвёт картинку при переходе, px
    transitionRgb: 80,     // navImagesRgbIntensity: расслоение при переходе, px
    transition: 2,         // длительность перехода, с (в оригинале 1 с туда и 1 с обратно)
    change: 0              // автосмена картинок раз в N секунд; 0 — только по клику
  };

  // Слабое устройство или телефон: холст в разрешении 1×, этого хватает глазу
  var LITE = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4 ||
             (window.matchMedia && (matchMedia("(pointer: coarse)").matches ||
                                    matchMedia("(prefers-reduced-data: reduce)").matches));

  var gl = null, u = {}, textures = [], sizes = [];
  var started = false, visible = false, onScreen = true, raf = 0;
  var cssW = 1, cssH = 1;
  var current = 0, next = 0;
  var tr = { start: -1, swap: false };                      // переход: когда начался, меняет ли картинку
  var lastChange = 0;
  var p = { x: 0, y: 0, vx: 0, vy: 0, inside: false };      // курсор (x, y) и догоняющая его точка (vx, vy)
  var lens = { x: 0, y: 0 };                                // сила линзы, плавно догоняет скорость (как TweenMax 0.5 с)
  var drag = { on: false, x: 0, y: 0, sx: 0, tx: 0, ty: 0, moved: false };   // tx, ty — сила рваной карты по осям

  /* ---------- шейдер ---------- */
  var VERT = "attribute vec2 a;varying vec2 uv;void main(){uv=a*.5+.5;uv.y=1.-uv.y;gl_Position=vec4(a,0.,1.);}";
  var FRAG = [
    "precision highp float;",
    "varying vec2 uv;",
    "uniform sampler2D texA, texB;",
    "uniform vec2 sizeA, sizeB, box;",       // размеры картинок и блока (CSS px)
    "uniform vec2 mouse, lens, rgb;",        // точка у курсора, сила линзы и расслоение (px)
    "uniform vec2 center;",                  // откуда рвёт карта: середина блока или курсор при перетаскивании
    "uniform vec2 tear;",                    // сила рваной карты по осям (px)
    "uniform float mapScale, mixT;",         // масштаб карты и доля новой картинки
    "float h(vec2 q){return fract(sin(dot(q,vec2(127.1,311.7)))*43758.5453);}",
    "float n(vec2 q){vec2 i=floor(q),f=fract(q);f=f*f*(3.-2.*f);",
    "  return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+1.),f.x),f.y);}",
    "float fbm(vec2 q){float s=0.,k=.5;for(int i=0;i<4;i++){s+=k*n(q);q=q*2.1+13.7;k*=.5;}return s;}",
    // Рваная карта смещения (как map.jpg и map3.png оригинала): блоки по секторам вокруг центра
    // и кольца с резкими краями. На резких краях соседние пиксели сдвигаются по-разному — это и есть помехи.
    "float tearMap(vec2 d){",
    "  vec2 q=d/(220.*mapScale);",
    "  float ang=atan(q.y,q.x),r=length(q);",
    "  float blocks=h(floor(vec2(ang*3.8197,r*6.)));",          // 24 сектора × кольца-ступеньки
    "  blocks=mix(blocks,n(q*3.),.45);",
    "  float rings=fract(fbm(q*.9+3.)*5.);",                    // контурные кольца, обрыв на каждом
    "  return mix(blocks,rings,.5);}",
    // object-fit: cover с запасом 6% по краям, чтобы смещение не вытаскивало край картинки
    "vec2 cover(vec2 px,vec2 img){",
    "  float s=max(box.x/img.x,box.y/img.y)*1.06;",
    "  return (px-box*.5)/(img*s)+.5;}",
    // Линза у курсора (как displace-circle.png): в центре тянет сильнее всего, к краю слабее.
    // За краем кружка карта не нейтрально-серая, поэтому вся картинка чуть съезжает за мышью.
    "vec2 lensShift(vec2 px){",
    "  float R=" + SETTINGS.cursorRadius.toFixed(1) + ";",
    "  float d=length(px-mouse);",
    "  float v=mix(.5*smoothstep(0.,R,d)," + (0.5 - SETTINGS.slip).toFixed(3) + ",smoothstep(R*.7,R,d));",
    "  return (vec2(v)-.5)*lens;}",
    // Расслоение под линзой: по направлению движения, в центре линзы максимум, к её краю плавно до нуля
    "vec2 lensRgb(vec2 px){",
    "  float f=1.-smoothstep(0.," + SETTINGS.cursorRadius.toFixed(1) + ",length(px-mouse));",
    "  vec2 v=lens*" + SETTINGS.lensRgb.toFixed(3) + ";",
    "  float L=length(v);",
    "  if(L>" + SETTINGS.lensRgbMax.toFixed(1) + ") v*=" + SETTINGS.lensRgbMax.toFixed(1) + "/L;",
    "  return v*f*f;}",
    "vec3 pick(sampler2D t,vec2 img,vec2 px){",
    "  vec2 split=rgb+lensRgb(px);",
    "  vec2 pr=px+split, pb=px-split;",                          // красный в одну сторону, голубой в другую
    "  float r=texture2D(t,cover(pr+lensShift(pr),img)).r;",
    "  float g=texture2D(t,cover(px+lensShift(px),img)).g;",
    "  float b=texture2D(t,cover(pb+lensShift(pb),img)).b;",
    "  return vec3(r,g,b);}",
    "void main(){",
    "  vec2 px=uv*box;",
    "  float m=tearMap(px-center);",
    "  px+=(vec2(m)-.5)*tear;",                                  // рвём по карте отдельно по x и y (Pixi DisplacementFilter)
    "  vec3 a=pick(texA,sizeA,px);",
    "  vec3 b=pick(texB,sizeB,px);",
    "  gl_FragColor=vec4(mix(a,b,smoothstep(.3,.7,mixT)),1.);",
    "}"
  ].join("\n");

  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }

  function setup() {
    gl = canvas.getContext("webgl", { alpha: false, antialias: false });
    if (!gl) return false;
    var prog;
    try {
      prog = gl.createProgram();
      gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
      gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(prog);
      if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error("link");
    } catch (e) { return false; }
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    var loc = gl.getAttribLocation(prog, "a");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    ["texA", "texB", "sizeA", "sizeB", "box", "mouse", "lens", "rgb", "center", "tear", "mapScale", "mixT"]
      .forEach(function (name) { u[name] = gl.getUniformLocation(prog, name); });
    gl.uniform1i(u.texA, 0); gl.uniform1i(u.texB, 1);
    return true;
  }

  /* ---------- картинки ---------- */
  function load(src) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = reject;
      img.src = src;
    });
  }

  function toTexture(img) {
    // Видеокарта телефона может не принять огромную картинку: уменьшаем до её предела
    var limit = Math.min(gl.getParameter(gl.MAX_TEXTURE_SIZE), 4096);
    var w = img.naturalWidth, h = img.naturalHeight, source = img;
    if (Math.max(w, h) > limit) {
      var k = limit / Math.max(w, h), c = document.createElement("canvas");
      c.width = Math.round(w * k); c.height = Math.round(h * k);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      source = c; w = c.width; h = c.height;
    }
    var t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    // CLAMP и без mipmap: так WebGL 1 принимает картинки любого размера, не только степени двойки
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, source);
    textures.push(t); sizes.push([w, h]);
  }

  /* ---------- размер ---------- */
  function resize() {
    var rect = box.getBoundingClientRect();
    cssW = Math.max(1, rect.width); cssH = Math.max(1, rect.height);
    var dpr = Math.min(window.devicePixelRatio || 1, LITE ? 1 : 1.75);
    var w = Math.round(cssW * dpr), h = Math.round(cssH * dpr);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h);
    gl.uniform2f(u.box, cssW, cssH);
  }

  /* ---------- мышь и палец ---------- */
  function local(e) {
    var rect = box.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top, inside:
      e.clientX >= rect.left && e.clientX <= rect.right && e.clientY >= rect.top && e.clientY <= rect.bottom };
  }

  hero.addEventListener("pointermove", function (e) {
    var q = local(e);
    if (!p.inside && q.inside) { p.vx = q.x; p.vy = q.y; }           // вошли: хвост начинается отсюда, без рывка
    p.x = q.x; p.y = q.y; p.inside = q.inside;
    if (drag.on && Math.abs(q.x - drag.sx) > 6) drag.moved = true;
    if (drag.on && Math.abs(q.x - drag.sx) > cssW * SETTINGS.swipeDistance) {   // дотянули: следующая картинка
      drag.on = false; transition(textures.length > 1);
    }
    kick();
  }, { passive: true });
  hero.addEventListener("pointerleave", function () { p.inside = false; drag.on = false; kick(); });

  function onControl(target) { return target.closest("a, button, input, select, textarea, label"); }

  hero.addEventListener("pointerdown", function (e) {
    if (onControl(e.target)) return;
    var q = local(e);
    if (tr.start >= 0) return;                          // во время перехода свайп не начинаем (как в оригинале)
    drag.on = true; drag.moved = false; drag.sx = q.x;
    kick();
  });
  window.addEventListener("pointerup", function () {
    if (!drag.on) return;
    drag.on = false;
    if (!drag.moved) transition(textures.length > 1);   // просто клик: переход (на следующую картинку, если их несколько)
    kick();
  });

  /* ---------- переходы ---------- */
  function now() { return performance.now() / 1000; }

  function transition(swap) {
    if (tr.start >= 0) return;                          // уже идёт
    tr.start = now(); tr.swap = swap && textures.length > 1;
    if (tr.swap) next = (current + 1) % textures.length;
    kick();
  }

  /* ---------- кадр ---------- */
  function bind(unit, index) {
    gl.activeTexture(unit ? gl.TEXTURE1 : gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, textures[index]);
    gl.uniform2f(unit ? u.sizeB : u.sizeA, sizes[index][0], sizes[index][1]);
  }

  function frame() {
    raf = 0;
    if (!visible || !onScreen || document.hidden) return;
    var t = now();

    // Как в оригинале: точка догоняет курсор, «скорость» — насколько она отстаёт (kineX, kineY)
    var tx = p.inside ? p.x : p.vx, ty = p.inside ? p.y : p.vy;
    p.vx += (tx - p.vx) * SETTINGS.momentum;
    p.vy += (ty - p.vy) * SETTINGS.momentum;
    var kx = tx - p.vx, ky = ty - p.vy;
    if (!p.inside) { kx *= 0.85; ky *= 0.85; }

    // Линза плавно догоняет скорость (в оригинале TweenMax за 0,5 с)
    lens.x += (kx * SETTINGS.cursorScale - lens.x) * 0.12;
    lens.y += (ky * SETTINGS.cursorScale - lens.y) * 0.12;

    // Свайп: рваная карта едет за курсором, сила по скорости отдельно по осям; отпустили — стихает за ~0,5 с
    var swiping = drag.on && drag.moved;
    drag.tx += ((swiping ? kx * SETTINGS.dragScale : 0) - drag.tx) * (swiping ? 0.5 : 0.12);
    drag.ty += ((swiping ? ky * SETTINGS.dragScale : 0) - drag.ty) * (swiping ? 0.5 : 0.12);
    var dragAmount = Math.abs(drag.tx) + Math.abs(drag.ty);
    drag.x += ((drag.on ? p.x : drag.x) - drag.x) * 0.5;
    drag.y += ((drag.on ? p.y : drag.y) - drag.y) * 0.5;

    // Переход: сила растёт и спадает по синусу, карта по ходу укрупняется (sprite.scale в оригинале)
    var progress = tr.start >= 0 ? Math.min((t - tr.start) / SETTINGS.transition, 1) : 0;
    var burst = tr.start >= 0 ? Math.sin(Math.PI * progress) : 0;
    var mixT = tr.swap ? progress : 0;
    if (tr.start >= 0 && progress >= 1) {
      if (tr.swap) current = next;
      tr.start = -1; tr.swap = false; mixT = 0; burst = 0; lastChange = t;
    }
    if (SETTINGS.change && textures.length > 1 && tr.start < 0 && t - lastChange > SETTINGS.change) transition(true);

    var burstTear = burst * SETTINGS.transitionScale;
    var useDrag = dragAmount > burstTear;
    // Цвета расходятся только при свайпе и при переходе, просто от движения мыши — нет
    var rgb = swiping ? Math.max(-SETTINGS.rgbMax, Math.min(SETTINGS.rgbMax, kx * SETTINGS.rgb)) : 0;
    bind(0, current); bind(1, tr.swap ? next : current);
    gl.uniform2f(u.mouse, p.vx, p.vy);
    gl.uniform2f(u.lens, lens.x, lens.y);
    gl.uniform2f(u.rgb, rgb + burst * SETTINGS.transitionRgb, 0);
    gl.uniform2f(u.center, useDrag ? drag.x : cssW / 2, useDrag ? drag.y : cssH / 2);
    gl.uniform2f(u.tear, burstTear + drag.tx, burstTear + drag.ty);
    gl.uniform1f(u.mapScale, 0.6 + progress * 2.4);
    gl.uniform1f(u.mixT, mixT);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

    // Крутим кадры, пока что-то движется; всё стихло — стоим и не тратим батарею
    var busy = tr.start >= 0 || drag.on || dragAmount > 0.3 ||
               Math.abs(kx) + Math.abs(ky) > 0.3 || Math.abs(lens.x) + Math.abs(lens.y) > 0.3 ||
               (SETTINGS.change && textures.length > 1);
    if (busy) raf = requestAnimationFrame(frame);
  }

  function kick() {
    if (!raf && visible && textures.length && onScreen && !document.hidden) raf = requestAnimationFrame(frame);   // без текстур (сброс видеокарты) кадров нет
  }

  /* ---------- запуск только в светлых темах (data-mode="light") ---------- */
  function themeChanged() {
    var want = root.dataset.mode === "light" && root.dataset.motion !== "reduced";   // заставка с фото у всех светлых тем
    if (want && !started) { start(); return; }
    var was = visible;
    visible = want && textures.length > 0;              // рисуем, только когда картинки уже в видеокарте
    box.classList.toggle("is-gl", visible);
    hero.classList.toggle("has-liquid", visible);       // кристалл темы прячем, пока виден эффект
    if (visible && !was) { p.vx = p.x = cssW / 2; p.vy = p.y = cssH / 2; lastChange = now(); transition(false); }
  }

  function start() {
    started = true;                                     // второй раз не запускаем, даже если что-то не вышло
    if (!setup()) return;
    Promise.all(sources().map(load)).then(function (imgs) {
      imgs.forEach(toTexture);
      resize();
      themeChanged();
    }).catch(function () { /* картинка не загрузилась: остаётся обычный фон темы */ });
  }

  new MutationObserver(themeChanged).observe(root, { attributes: true, attributeFilter: ["data-theme", "data-mode", "data-motion"] });
  window.addEventListener("resize", function () { if (textures.length) { resize(); kick(); } });
  // Видеокарта сбросила контекст (бывает на телефонах при нехватке памяти): прячем эффект, а не рисуем в пустоту
  canvas.addEventListener("webglcontextlost", function (e) {
    e.preventDefault(); textures = []; visible = false;
    box.classList.remove("is-gl"); hero.classList.remove("has-liquid");
  });
  document.addEventListener("visibilitychange", kick);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) { onScreen = entries[0].isIntersecting; kick(); }).observe(box);
  }
  themeChanged();
})();
