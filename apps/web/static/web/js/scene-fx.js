/* Фото горы в герое: настоящая рябь на воде + RGB-расслоение (WebGL).
   Курсор «роняет капли» вдоль своего пути; чем быстрее мышь, тем крупнее и сильнее волны и RGB.
   Нажать левую кнопку и тянуть — максимум: большие волны и сильный RGB-сдвиг.
   Волны считаются на CPU на маленькой сетке (волновое уравнение), в видеокарту уходит текстура
   с наклоном и высотой воды, шейдер только преломляет фото. Нет WebGL или «меньше движения» — просто фото. */
(function () {
  "use strict";

  var hero = document.querySelector("[data-parallax]");
  var scene = hero && hero.querySelector(".scene");
  var canvas = scene && scene.querySelector(".layer-fx");
  var img = scene && scene.querySelector(".layer-photo");
  if (!canvas || !img) return;
  if (document.documentElement.dataset.motion === "reduced") return;

  var gl = canvas.getContext("webgl", { alpha: false, antialias: false });
  if (!gl) return;

  /* ---------- шейдер ---------- */
  var VERT = "attribute vec2 p;varying vec2 uv;void main(){uv=p*.5+.5;uv.y=1.-uv.y;gl_Position=vec4(p,0.,1.);}";
  var FRAG = [
    "precision mediump float;",
    "varying vec2 uv;",
    "uniform sampler2D tex;",   // фото
    "uniform sampler2D wave;",  // R,G: наклон воды, B: высота
    "uniform float refr;",      // сила преломления
    "uniform float rgb;",       // сила RGB-расслоения
    "void main(){",
    "  vec4 w=texture2D(wave,uv);",
    "  vec2 g=(w.rg-.5)*2.;",
    "  float h=(w.b-.5)*2.;",
    "  vec2 off=g*refr;",
    "  float r=texture2D(tex,uv+off*(1.+rgb)).r;",               // красный и синий преломляются по-разному
    "  float gr=texture2D(tex,uv+off).g;",
    "  float b=texture2D(tex,uv+off*(1.-rgb)).b;",
    "  vec3 col=vec3(r,gr,b);",
    "  vec3 n=normalize(vec3(-g*5.,1.));",
    "  float spec=pow(max(dot(n,normalize(vec3(-.3,-.5,.8))),0.),48.);",   // блик света на гребнях
    "  col+=spec*.35*min(1.,length(g)*9.)+max(h,0.)*.05;",
    "  gl_FragColor=vec4(col,1.);",
    "}"
  ].join("\n");

  function sh(type, src) {
    var s = gl.createShader(type);
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
    return s;
  }
  var prog;
  try {
    prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error("link");
  } catch (e) { return; }
  gl.useProgram(prog);

  gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  var loc = gl.getAttribLocation(prog, "p");
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  var uRefr = gl.getUniformLocation(prog, "refr"), uRgb = gl.getUniformLocation(prog, "rgb");

  /* ---------- вода: волновое уравнение на сетке ---------- */
  var W = 128, H = 192;                                    // клетки квадратные (фото 2:3)
  var cur = new Float32Array(W * H), prev = new Float32Array(W * H);
  var pix = new Uint8Array(W * H * 4);                     // текстура: наклон по x, y и высота
  var DAMP = 0.985;                                        // чем ближе к 1, тем дольше живут круги
  var energy = 0;

  function step() {
    var e = 0, i, x, y, v;
    for (y = 1; y < H - 1; y++) {
      for (x = 1; x < W - 1; x++) {
        i = y * W + x;
        // среднее по соседям минус прошлое состояние = волна, бегущая по сетке
        v = ((cur[i - 1] + cur[i + 1] + cur[i - W] + cur[i + W]) * 0.5 - prev[i]) * DAMP;
        prev[i] = v;
        e += v < 0 ? -v : v;
      }
    }
    var t = cur; cur = prev; prev = t;                     // меняем местами буферы
    energy = e;
  }

  function drop(gx, gy, strength, radius) {                // капля: гладкий «бугор» в точке
    var r = Math.ceil(radius * 2), x0 = Math.round(gx), y0 = Math.round(gy);
    for (var y = y0 - r; y <= y0 + r; y++) {
      for (var x = x0 - r; x <= x0 + r; x++) {
        if (x < 1 || y < 1 || x >= W - 1 || y >= H - 1) continue;
        var d2 = ((x - gx) * (x - gx) + (y - gy) * (y - gy)) / (radius * radius);
        if (d2 < 4) cur[y * W + x] = Math.max(-0.5, cur[y * W + x] - strength * Math.exp(-d2 * 1.6));
      }
    }
  }

  function pack() {                                        // высота и наклон -> байты текстуры
    var GS = 8, x, y, i, o, gx, gy, h;
    for (y = 1; y < H - 1; y++) {
      for (x = 1; x < W - 1; x++) {
        i = y * W + x; o = i * 4;
        gx = (cur[i + 1] - cur[i - 1]) * GS; gy = (cur[i + W] - cur[i - W]) * GS; h = cur[i];
        pix[o]     = 127.5 + 127.5 * Math.max(-1, Math.min(1, gx));
        pix[o + 1] = 127.5 + 127.5 * Math.max(-1, Math.min(1, gy));
        pix[o + 2] = 127.5 + 127.5 * Math.max(-1, Math.min(1, h * 2));
        pix[o + 3] = 255;
      }
    }
  }

  /* ---------- текстуры ---------- */
  var waveTex;
  function upload() {
    // слабое устройство или экономия трафика: холст вдвое меньше (картинка и волны те же, только мельче)
    var lite = (navigator.hardwareConcurrency || 8) <= 4 || (navigator.deviceMemory || 8) <= 4 ||
               (window.matchMedia && matchMedia("(hover: none)").matches) ||      // телефон: и так рябь мельче глазом, и батарея
               (window.matchMedia && matchMedia("(prefers-reduced-data: reduce)").matches);
    var q = lite ? 0.5 : 1;
    canvas.width = Math.round(img.naturalWidth * q); canvas.height = Math.round(img.naturalHeight * q);
    gl.viewport(0, 0, canvas.width, canvas.height);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
    setup();
    gl.uniform1i(gl.getUniformLocation(prog, "tex"), 0);

    gl.activeTexture(gl.TEXTURE1);
    waveTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, waveTex);
    pack();
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, W, H, 0, gl.RGBA, gl.UNSIGNED_BYTE, pix);
    setup();
    gl.uniform1i(gl.getUniformLocation(prog, "wave"), 1);

    ready = true;
    render();
    scene.classList.add("is-gl");
  }
  function setup() {
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  /* ---------- ввод и цикл ---------- */
  var ready = false, raf = 0, down = false;
  var last = null;                                         // прошлая точка курсора (экран)
  var power = 0, rgbPower = 0;                             // сглаженные: скорость мыши -> сила эффектов

  // экран -> клетки сетки с учётом object-fit: cover и object-position 50% 18%
  function toGrid(cx, cy) {
    var r = canvas.getBoundingClientRect();
    var s = Math.max(r.width / canvas.width, r.height / canvas.height);
    var dw = canvas.width * s, dh = canvas.height * s;
    var ox = (r.width - dw) * 0.5, oy = (r.height - dh) * 0.18;
    return { x: (cx - r.left - ox) / dw * W, y: (cy - r.top - oy) / dh * H };
  }

  var logoEl = hero.querySelector(".logo3d-hero");
  function overLogo(x, y) {                                // под логотипом воды не нужно
    if (!logoEl) return false;
    var r = logoEl.getBoundingClientRect();
    return x > r.left - 8 && x < r.right + 8 && y > r.top - 8 && y < r.bottom + 8;
  }

  hero.addEventListener("pointermove", function (e) {
    if (!ready) return;
    if (overLogo(e.clientX, e.clientY)) { last = null; return; }
    var now = { x: e.clientX, y: e.clientY };
    if (last) {
      var sp = Math.hypot(now.x - last.x, now.y - last.y);          // px за событие
      var k = Math.min(1, sp / 45);                                 // 0..1 по скорости
      var kk = down ? 1 : k;
      power += (kk - power) * 0.5; rgbPower += (kk - rgbPower) * 0.5;
      // капли по всему пути от прошлой точки: быстрый взмах оставляет след, а не отдельные кружки
      var a = toGrid(last.x, last.y), b = toGrid(now.x, now.y);
      var n = Math.max(1, Math.ceil(Math.hypot(b.x - a.x, b.y - a.y) / 1.5));
      var strength = down ? 0.28 : 0.05 + 0.16 * k * k;               // тихо: еле заметно, быстро: сильно
      var radius = down ? 3.6 : 1.5 + 1.6 * k;                      // и крупнее при быстром движении
      for (var i = 1; i <= n; i++) drop(a.x + (b.x - a.x) * i / n, a.y + (b.y - a.y) * i / n, strength / n, radius);
    }
    last = now;
    kick();
  });
  hero.addEventListener("pointerleave", function () { last = null; down = false; });
  hero.addEventListener("pointerdown", function (e) {
    if (!ready || overLogo(e.clientX, e.clientY)) return;
    if (e.pointerType === "mouse") {
      if (e.button === 0) { down = true; last = { x: e.clientX, y: e.clientY }; kick(); }
    } else {                                               // палец: касание роняет заметную каплю, дальше работает движение
      var g = toGrid(e.clientX, e.clientY);
      drop(g.x, g.y, 0.4, 3.2);
      power = rgbPower = 0.8;
      last = { x: e.clientX, y: e.clientY };
      kick();
    }
  });
  hero.addEventListener("pointercancel", function () { last = null; down = false; });   // браузер забрал жест под прокрутку
  window.addEventListener("pointerup", function () { down = false; });

  function kick() { if (!raf && ready) raf = requestAnimationFrame(frame); }

  function render() {
    pack();
    gl.activeTexture(gl.TEXTURE1);
    gl.texSubImage2D(gl.TEXTURE_2D, 0, 0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, pix);
    // базовое преломление + прибавка от силы эффекта; RGB растёт сильнее всего при перетаскивании
    gl.uniform1f(uRefr, 0.012 + 0.022 * power);
    gl.uniform1f(uRgb, 0.25 + 1.5 * rgbPower);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  function frame() {
    raf = 0;
    step(); step();                                        // два шага за кадр: волны бегут бодрее
    power *= 0.97; rgbPower *= 0.97;                       // когда мышь замерла, сила плавно спадает
    render();
    if (energy > 0.02 || down) raf = requestAnimationFrame(frame);
    else { cur.fill(0); prev.fill(0); power = rgbPower = 0; render(); }   // вода успокоилась: чистый кадр и стоп
  }

  if (img.complete && img.naturalWidth) upload();
  else img.addEventListener("load", upload, { once: true });
})();
