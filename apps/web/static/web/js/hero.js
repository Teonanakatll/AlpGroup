/* Герой главной: параллакс слоёв + логотип с бликами (WebGL).
   Дальние слои (data-depth мал) двигаются за курсором слабо, ближние сильнее.
   Без WebGL остаётся обычная картинка логотипа. */
(function () {
  "use strict";

  var hero = document.querySelector("[data-parallax]");
  if (!hero) return;

  var root = document.documentElement;
  var still = root.dataset.motion === "reduced";          // флаг из настроек сайта (см. DECISIONS §18)
  var layers = Array.prototype.slice.call(hero.querySelectorAll("[data-depth]"));
  var logo = hero.querySelector(".logo3d");
  
  var SHIFT = 6;                                           // px на единицу глубины при крайнем положении курсора
  var target = { x: 0, y: 0 };                             // куда тянется курсор, -1..1
  var cur = { x: 0, y: 0 };                                // сглаженное положение
  var hasPointer = false;
  var visible = true;
  var raf = 0;
  var gl = null;                                           // состояние шейдера (если получилось)

  /* ---------- ввод ---------- */
  function onMove(e) {
    var r = hero.getBoundingClientRect();
    target.x = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1));
    target.y = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height) * 2 - 1));
    client.x = e.clientX; client.y = e.clientY;
    hasPointer = true;
    kick();
  }
  function onLeave() { hasPointer = false; kick(); }
  hero.addEventListener("pointermove", onMove);
  hero.addEventListener("pointerleave", onLeave);

  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (en) {
      visible = en[0].isIntersecting;
      if (visible) kick();
    }).observe(hero);
  }

  /* ---------- цикл ---------- */
  function kick() { if (!raf && visible) raf = requestAnimationFrame(frame); }

  function frame(t) {
    raf = 0;
    if (!visible) return;
    var time = t / 1000;

    if (!hasPointer) {                                     // без курсора слегка «дышим» сами
      target.x = Math.sin(time * 0.35) * 0.45;
      target.y = Math.cos(time * 0.27) * 0.25;
    }
    // lerp: чем меньше коэффициент, тем плавнее и «тяжелее» движение
    cur.x += (target.x - cur.x) * 0.035;
    cur.y += (target.y - cur.y) * 0.035;

    layers.forEach(function (el) {
      var d = parseFloat(el.dataset.depth) || 0;
      var x = -cur.x * d * SHIFT;
      var y = -cur.y * d * SHIFT * 0.6;
      if (el === logo) {
        // тот же сдвиг + лёгкий наклон к курсору
        el.style.transform = "translate3d(" + x + "px," + y + "px,0) perspective(700px) rotateY(" +
          (cur.x * 3).toFixed(2) + "deg) rotateX(" + (-cur.y * 2).toFixed(2) + "deg)";
      } else {
        el.style.transform = "translate3d(" + x + "px," + y + "px,0)";
      }
    });

    if (gl) drawLogo(time);
    raf = requestAnimationFrame(frame);
  }

  /* ---------- логотип: WebGL ---------- */
  var VERT = "attribute vec2 p;varying vec2 uv;void main(){uv=p*.5+.5;uv.y=1.-uv.y;gl_Position=vec4(p,0.,1.);}";

  // Нормаль берём из яркости текстуры (рельеф золота и карбона), свет следует за курсором.
  var FRAG = [
    "precision mediump float;",
    "varying vec2 uv;",
    "uniform sampler2D tex;",
    "uniform vec2 px;",          // размер одного texel
    "uniform vec3 light;",       // положение света в координатах логотипа (x,y 0..1, z высота)
    "uniform float time;",
    "float lum(vec4 c){return dot(c.rgb,vec3(.299,.587,.114));}",
    "float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}",
    "void main(){",
    "  vec4 c=texture2D(tex,uv);",
    "  if(c.a<.003){gl_FragColor=vec4(0.);return;}",
    "  vec3 base=c.rgb/max(c.a,.001);",                       // убираем premultiply для расчётов
    "  float mx=max(base.r,max(base.g,base.b)), mn=min(base.r,min(base.g,base.b));",
    "  float sat=(mx-mn)/max(mx,.001);",
    "  float gold=smoothstep(.28,.55,sat)*step(base.b,base.r);",   // золото: насыщенное, тёплое; карбон серый
    // рельеф на двух масштабах: крупный (края букв) и мелкий (плетение карбона)
    "  vec2 e1=px*2.,e2=px*.8;",
    "  float hx1=lum(texture2D(tex,uv+vec2(e1.x,0.)))-lum(texture2D(tex,uv-vec2(e1.x,0.)));",
    "  float hy1=lum(texture2D(tex,uv+vec2(0.,e1.y)))-lum(texture2D(tex,uv-vec2(0.,e1.y)));",
    "  float hx2=lum(texture2D(tex,uv+vec2(e2.x,0.)))-lum(texture2D(tex,uv-vec2(e2.x,0.)));",
    "  float hy2=lum(texture2D(tex,uv+vec2(0.,e2.y)))-lum(texture2D(tex,uv-vec2(0.,e2.y)));",
    "  vec2 g=mix(vec2(hx2,hy2)*1.6,vec2(hx1,hy1)*.9,gold);",
    "  vec3 n=normalize(vec3(-g*3.,1.));",
    // направление на свет (экран логотипа 3.44:1, поправка по x)
    "  vec3 pos=vec3((uv.x-.5)*3.44,(uv.y-.5),0.);",
    "  vec3 L=normalize(vec3((light.x-.5)*3.44,(light.y-.5),light.z)-pos);",
    "  vec3 V=vec3(0.,0.,1.);",
    "  vec3 H=normalize(L+V);",
    "  float nh=max(dot(n,H),0.), nl=max(dot(n,L),0.);",
    // золото: широкий тёплый блик + узкая искра; карбон: тусклый широкий + редкие искры по зерну
    "  float specG=pow(nh,22.)*.9+pow(nh,140.)*1.6;",
    "  float grain=hash(floor(uv/px*.5));",
    "  float specC=pow(nh,60.)*.35+pow(nh,260.)*step(.82,grain)*2.2;",
    "  vec3 goldTint=vec3(1.,.86,.52);",
    "  vec3 col=base*(.62+.5*nl);",
    "  col+=mix(vec3(.7,.75,.85)*specC, goldTint*specG, gold);",
    // полоса-«проход» света: смещается вместе с курсором
    "  float d=abs((uv.x-light.x)*1.0+(uv.y-.5)*.55);",
    "  float band=smoothstep(.16,0.,d);",
    "  col+=mix(vec3(.10,.11,.13),goldTint*.28,gold)*band*nl;",
    "  col=clamp(col,0.,1.);",
    "  gl_FragColor=vec4(col*c.a,c.a);",                      // обратно в premultiplied
    "}"
  ].join("\n");

  function initLogo() {
    if (!logo) return;
    var img = logo.querySelector(".logo3d-img");
    var canvas = logo.querySelector(".logo3d-canvas");
    if (!img || !canvas) return;

    var ctx = canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true, antialias: false }) ||
              canvas.getContext("experimental-webgl", { premultipliedAlpha: true, alpha: true });
    if (!ctx) return;

    function sh(type, src) {
      var s = ctx.createShader(type);
      ctx.shaderSource(s, src); ctx.compileShader(s);
      if (!ctx.getShaderParameter(s, ctx.COMPILE_STATUS)) throw new Error(ctx.getShaderInfoLog(s));
      return s;
    }
    var prog;
    try {
      prog = ctx.createProgram();
      ctx.attachShader(prog, sh(ctx.VERTEX_SHADER, VERT));
      ctx.attachShader(prog, sh(ctx.FRAGMENT_SHADER, FRAG));
      ctx.linkProgram(prog);
      if (!ctx.getProgramParameter(prog, ctx.LINK_STATUS)) throw new Error("link");
    } catch (err) { return; }                              // не вышло: остаётся картинка
    ctx.useProgram(prog);

    var buf = ctx.createBuffer();
    ctx.bindBuffer(ctx.ARRAY_BUFFER, buf);
    ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), ctx.STATIC_DRAW);
    var loc = ctx.getAttribLocation(prog, "p");
    ctx.enableVertexAttribArray(loc);
    ctx.vertexAttribPointer(loc, 2, ctx.FLOAT, false, 0, 0);

    var tex = ctx.createTexture();
    ctx.bindTexture(ctx.TEXTURE_2D, tex);
    ctx.pixelStorei(ctx.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    ctx.texImage2D(ctx.TEXTURE_2D, 0, ctx.RGBA, ctx.RGBA, ctx.UNSIGNED_BYTE, img);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MIN_FILTER, ctx.LINEAR);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MAG_FILTER, ctx.LINEAR);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_S, ctx.CLAMP_TO_EDGE);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_T, ctx.CLAMP_TO_EDGE);

    var u = {
      px: ctx.getUniformLocation(prog, "px"),
      light: ctx.getUniformLocation(prog, "light"),
      time: ctx.getUniformLocation(prog, "time")
    };
    ctx.uniform1i(ctx.getUniformLocation(prog, "tex"), 0);
    ctx.uniform2f(u.px, 1 / img.naturalWidth, 1 / img.naturalHeight);

    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var w = Math.min(Math.round(canvas.clientWidth * dpr), img.naturalWidth);
      var h = Math.round(w * img.naturalHeight / img.naturalWidth);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      ctx.viewport(0, 0, w, h);
    }
    resize();
    window.addEventListener("resize", function () { resize(); if (still) drawLogo(0); });

    gl = { ctx: ctx, u: u, resize: resize };
    logo.classList.add("is-gl");
    drawLogo(0);
  }

  // Свет: над логотипом идёт за курсором; иначе раз в несколько секунд сам пробегает слева направо.
  var light = { x: -0.4, y: 0.35, z: 0.35 };
  var client = { x: 0, y: 0 };
  var SWEEP_EVERY = 6.5, SWEEP_TIME = 2.4;

  function drawLogo(time) {
    var c = gl.ctx;
    var lr = logo.getBoundingClientRect();
    var tx, ty;
    var over = hasPointer && client.x > lr.left - 30 && client.x < lr.right + 30 &&
               client.y > lr.top - 30 && client.y < lr.bottom + 30;
    if (still) { tx = 0.25; ty = 0.2; light.x = tx; light.y = ty; }
    else if (over) {
      tx = (client.x - lr.left) / lr.width;
      ty = (client.y - lr.top) / lr.height;
    } else {
      var k = (time % SWEEP_EVERY) / SWEEP_TIME;           // 0..1 во время пробега, дальше свет стоит за краем
      if (k < 1) {
        var e = k * k * (3 - 2 * k);                       // smoothstep: разгон и торможение
        tx = -0.35 + e * 1.7; ty = 0.25 + 0.2 * Math.sin(k * 3.14);
      } else { tx = 1.35; ty = 0.35; }
    }
    // над логотипом свет следует быстро, при пробеге — точно по траектории
    var f = over ? 0.2 : 1;
    if (!still) { light.x += (tx - light.x) * f; light.y += (ty - light.y) * f; }
    c.uniform3f(gl.u.light, light.x, light.y, 0.35);
    c.uniform1f(gl.u.time, time);
    c.clearColor(0, 0, 0, 0);
    c.clear(c.COLOR_BUFFER_BIT);
    c.drawArrays(c.TRIANGLE_STRIP, 0, 4);
  }

  /* ---------- старт ---------- */
  var logoImg = logo && logo.querySelector(".logo3d-img");
  function start() {
    initLogo();
    if (still) {                                           // без анимации: один кадр и всё
      layers.forEach(function (el) { el.style.transform = ""; });
      return;
    }
    kick();
  }
  if (logoImg && !logoImg.complete) logoImg.addEventListener("load", start, { once: true });
  else start();
})();
