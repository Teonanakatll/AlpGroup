/* Заставка темы Nexora: «жидкая» картинка (WebGL, без библиотек).
   Идея из rgbKineticSlider (PixiJS + GSAP), переписанная одним шейдером:
   - картинка всё время чуть «дышит»: её пиксели тянет медленный шум (вместо картинки-карты смещения);
   - за курсором с инерцией идёт линза: чем быстрее мышь, тем сильнее она тянет картинку
     по направлению движения и тем сильнее RGB-расслоение (красный в одну сторону, синий в другую);
   - при появлении (и при смене картинок, если их несколько) картинка «растекается» и собирается.
   Картинки любые (JPG, PNG, WebP): вписываются как object-fit: cover, слишком большие уменьшаются.
   Несколько картинок через «|» в data-images — тогда они сменяют друг друга.
   Нет WebGL, «меньше движения» или другая тема — эффект не запускается, остаётся обычный фон темы. */
(function () {
  "use strict";

  var root = document.documentElement;
  var box = document.querySelector(".liquid");
  var canvas = box && box.querySelector(".liquid-fx");
  if (!canvas) return;

  var SOURCES = (canvas.dataset.images || "").split("|").filter(Boolean);
  if (!SOURCES.length) return;

  var SETTINGS = {
    breathe: 0.006,     // постоянное «дыхание» картинки (доля ширины)
    lens: 0.22,         // радиус линзы курсора (доля высоты блока)
    pull: 3.4,          // насколько линза тянет картинку за мышью
    rgb: 2.6,           // сила RGB-расслоения от скорости мыши
    momentum: 0.12,     // инерция линзы: меньше — плавнее и дольше догоняет
    intro: 1.4,         // длительность «растекания» при появлении и смене картинки, с
    change: 9           // через сколько секунд менять картинку (если их несколько)
  };

  // Картинка дышит постоянно, пока видна, поэтому на слабых устройствах рисуем в меньшем разрешении
  var LITE = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4 ||
             (window.matchMedia && (matchMedia("(pointer: coarse)").matches ||
                                    matchMedia("(prefers-reduced-data: reduce)").matches));

  var gl = null, prog = null, textures = [], sizes = [], u = {};
  var started = false, raf = 0, visible = false, onScreen = true;
  var current = 0, next = 0, switchAt = 0, introStart = 0, lastChange = 0;
  var mouse = { x: 0.5, y: 0.5, tx: 0.5, ty: 0.5, inside: false };   // tx/ty — где курсор, x/y — где линза
  var vel = { x: 0, y: 0 };

  /* ---------- шейдер ---------- */
  var VERT = "attribute vec2 p;varying vec2 uv;void main(){uv=p*.5+.5;uv.y=1.-uv.y;gl_Position=vec4(p,0.,1.);}";
  var FRAG = [
    "precision mediump float;",
    "varying vec2 uv;",
    "uniform sampler2D texA, texB;",   // текущая и следующая картинки
    "uniform vec2 sizeA, sizeB, box;", // размеры картинок и блока в пикселях
    "uniform vec2 mouse, vel;",        // линза (0..1) и её скорость
    "uniform float time, mixT, burst, breathe, lens, pull, rgb;",
    // гладкий шум: сумма волн разных масштабов, его «наклон» и есть смещение пикселей
    "float h(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}",
    "float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);",
    "  return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+1.),f.x),f.y);}",
    "vec2 flow(vec2 p){",
    "  vec2 a=vec2(n(p+time*.05),n(p+vec2(5.2,1.3)-time*.04));",
    "  vec2 b=vec2(n(p*2.1+vec2(9.,2.)+time*.07),n(p*2.1+vec2(3.,7.)-time*.06));",
    "  return (a+b*.5)/1.5-.5;}",
    // как object-fit: cover: координаты картинки, чтобы она заполнила блок без искажения
    "vec2 cover(vec2 st,vec2 img){",
    "  float s=max(box.x/img.x,box.y/img.y);vec2 k=box/(img*s);",
    "  return (st-.5)*k+.5;}",
    "vec3 pick(sampler2D t,vec2 img,vec2 st,vec2 shift){",
    "  vec2 c=cover(st,img);",
    "  float r=texture2D(t,cover(st+shift,img)).r;",      // красный и синий берём со сдвигом
    "  float g=texture2D(t,c).g;",
    "  float b=texture2D(t,cover(st-shift,img)).b;",
    "  return vec3(r,g,b);}",
    "void main(){",
    "  float aspect=box.x/box.y;",
    "  vec2 f=flow(uv*vec2(aspect,1.)*2.2);",
    "  vec2 d=f*(breathe+burst*.18);",                           // дыхание + растекание при смене
    "  vec2 q=(uv-mouse)*vec2(aspect,1.);",
    "  float fall=smoothstep(lens,0.,length(q));",               // 1 в центре линзы, 0 за её краем
    "  fall*=fall;",
    "  d-=vel*fall*pull;",                                       // линза тянет картинку за мышью
    "  vec2 shift=vel*(fall*rgb+.15*rgb)+vec2(burst*.025,0.);",  // RGB-расслоение по движению
    "  vec3 a=pick(texA,sizeA,uv+d*(1.+mixT),shift);",
    "  vec3 b=pick(texB,sizeB,uv-d*(2.-mixT*2.),shift);",        // следующая «стекает» навстречу
    "  vec3 col=mix(a,b,smoothstep(0.,1.,mixT));",
    "  col+=vec3(.5,1.,.1)*fall*length(vel)*1.6;",               // лёгкий отсвет линзы в цвет темы
    "  gl_FragColor=vec4(col,1.);",
    "}"
  ].join("\n");

  function compile(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }

  function setup() {
    gl = canvas.getContext("webgl", { alpha: false, antialias: false, premultipliedAlpha: false });
    if (!gl) return false;
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
    var loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    ["texA", "texB", "sizeA", "sizeB", "box", "mouse", "vel", "time", "mixT", "burst",
     "breathe", "lens", "pull", "rgb"].forEach(function (name) { u[name] = gl.getUniformLocation(prog, name); });
    gl.uniform1i(u.texA, 0); gl.uniform1i(u.texB, 1);
    gl.uniform1f(u.breathe, SETTINGS.breathe);
    gl.uniform1f(u.lens, SETTINGS.lens);
    gl.uniform1f(u.pull, SETTINGS.pull);
    gl.uniform1f(u.rgb, SETTINGS.rgb);
    return true;
  }

  /* ---------- картинки ---------- */
  function load(src) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.decoding = "async";
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
      var k = limit / Math.max(w, h);
      var c = document.createElement("canvas");
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
    return { texture: t, size: [w, h] };
  }

  /* ---------- размер и курсор ---------- */
  function resize() {
    var rect = box.getBoundingClientRect();
    // выше 1.75 разницы не видно, а нагрузка растёт; на слабых устройствах и телефонах хватает 1
    var dpr = Math.min(window.devicePixelRatio || 1, LITE ? 1 : 1.75);
    var w = Math.max(1, Math.round(rect.width * dpr)), h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, w, h);
    gl.uniform2f(u.box, w, h);
  }

  function pointer(x, y) {
    var rect = box.getBoundingClientRect();
    mouse.tx = (x - rect.left) / rect.width;
    mouse.ty = (y - rect.top) / rect.height;
    mouse.inside = mouse.tx >= 0 && mouse.tx <= 1 && mouse.ty >= 0 && mouse.ty <= 1;
    kick();
  }

  var hero = box.closest(".hero") || box;
  hero.addEventListener("pointermove", function (e) { pointer(e.clientX, e.clientY); }, { passive: true });
  hero.addEventListener("pointerleave", function () { mouse.inside = false; });

  /* ---------- кадр ---------- */
  function ease(t) { return 1 - Math.pow(1 - Math.min(Math.max(t, 0), 1), 3); }

  function bind(unit, index) {
    gl.activeTexture(unit === 0 ? gl.TEXTURE0 : gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, textures[index]);
    gl.uniform2f(unit === 0 ? u.sizeA : u.sizeB, sizes[index][0], sizes[index][1]);
  }

  function frame(now) {
    raf = 0;
    if (!visible || !onScreen || document.hidden) return;
    var t = now / 1000;

    // линза догоняет курсор с инерцией; скорость = на сколько она отстаёт
    var tx = mouse.inside ? mouse.tx : 0.5, ty = mouse.inside ? mouse.ty : 0.5;
    var vx = (tx - mouse.x) * SETTINGS.momentum, vy = (ty - mouse.y) * SETTINGS.momentum;
    mouse.x += vx; mouse.y += vy;
    vel.x += (vx - vel.x) * 0.25; vel.y += (vy - vel.y) * 0.25;       // сглаживаем рывки

    // растекание при появлении, смена картинки по таймеру
    var burst = 1 - ease((t - introStart) / SETTINGS.intro);
    var mixT = 0;
    if (textures.length > 1) {
      if (!switchAt && t - lastChange > SETTINGS.change) { switchAt = t; next = (current + 1) % textures.length; }
      if (switchAt) {
        mixT = ease((t - switchAt) / SETTINGS.intro);
        burst = Math.max(burst, Math.sin(Math.PI * mixT));             // растекается и собирается
        if (mixT >= 1) { current = next; switchAt = 0; lastChange = t; mixT = 0; }
      }
    }
    bind(0, current); bind(1, switchAt ? next : current);

    gl.uniform2f(u.mouse, mouse.x, mouse.y);
    gl.uniform2f(u.vel, vel.x, vel.y);
    gl.uniform1f(u.time, t);
    gl.uniform1f(u.mixT, mixT);
    gl.uniform1f(u.burst, burst);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    raf = requestAnimationFrame(frame);                                 // картинка дышит всегда, пока видна
  }

  function kick() { if (!raf && started && visible && onScreen && !document.hidden) raf = requestAnimationFrame(frame); }

  /* ---------- запуск только в теме Nexora ---------- */
  function themeChanged() {
    var want = root.dataset.theme === "nexora" && root.dataset.motion !== "reduced";
    if (want && !started) { start(); return; }
    visible = want && textures.length > 0;                            // рисуем, только когда картинки уже в видеокарте
    box.classList.toggle("is-gl", visible);
    hero.classList.toggle("has-liquid", visible);                       // кристалл темы прячем, пока виден эффект
    if (visible) { introStart = performance.now() / 1000; lastChange = introStart; kick(); }   // при переключении темы снова «растекается»
  }

  function start() {
    started = true;          // второй раз не запускаем, даже если что-то не вышло
    if (!setup()) return;
    Promise.all(SOURCES.map(load)).then(function (imgs) {
      imgs.forEach(function (img) { var t = toTexture(img); textures.push(t.texture); sizes.push(t.size); });
      resize();
      themeChanged();
    }).catch(function () { /* картинка не загрузилась: остаётся обычный фон темы */ });
  }

  new MutationObserver(themeChanged).observe(root, { attributes: true, attributeFilter: ["data-theme", "data-motion"] });
  window.addEventListener("resize", function () { if (gl && textures.length) resize(); kick(); });
  document.addEventListener("visibilitychange", kick);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) { onScreen = entries[0].isIntersecting; kick(); }).observe(box);
  }
  themeChanged();
})();
