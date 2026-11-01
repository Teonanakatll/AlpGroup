/* Логотипы с бликами (WebGL): подключается на всех страницах и оживляет каждый .logo3d.
   Золото и карбон реагируют на свет: над логотипом он идёт за курсором, иначе блик сам
   пробегает раз в data-sweep секунд (у большого логотипа чаще, у малых реже).
   Нет WebGL или включено «меньше движения» — остаётся обычная картинка / один статичный кадр. */
(function () {
  "use strict";

  var logos = Array.prototype.slice.call(document.querySelectorAll(".logo3d"));
  if (!logos.length) return;

  var still = document.documentElement.dataset.motion === "reduced";   // DECISIONS §18
  var SWEEP_TIME = 2.4;                                                  // сколько длится пробег блика, с
  var pointer = { x: 0, y: 0, on: false };

  window.addEventListener("pointermove", function (e) { pointer.x = e.clientX; pointer.y = e.clientY; pointer.on = true; kick(); }, { passive: true });
  document.documentElement.addEventListener("mouseleave", function () { pointer.on = false; });

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

  /* ---------- один логотип = один контекст WebGL ---------- */
  function setup(el) {
    var img = el.querySelector(".logo3d-img");
    var canvas = el.querySelector(".logo3d-canvas");
    if (!img || !canvas) return null;
    var ctx = canvas.getContext("webgl", { premultipliedAlpha: true, alpha: true, antialias: false }) ||
              canvas.getContext("experimental-webgl", { premultipliedAlpha: true, alpha: true });
    if (!ctx) return null;

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
    } catch (err) { return null; }
    ctx.useProgram(prog);

    ctx.bindBuffer(ctx.ARRAY_BUFFER, ctx.createBuffer());
    ctx.bufferData(ctx.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), ctx.STATIC_DRAW);
    var loc = ctx.getAttribLocation(prog, "p");
    ctx.enableVertexAttribArray(loc);
    ctx.vertexAttribPointer(loc, 2, ctx.FLOAT, false, 0, 0);

    ctx.bindTexture(ctx.TEXTURE_2D, ctx.createTexture());
    ctx.pixelStorei(ctx.UNPACK_PREMULTIPLY_ALPHA_WEBGL, true);
    ctx.texImage2D(ctx.TEXTURE_2D, 0, ctx.RGBA, ctx.RGBA, ctx.UNSIGNED_BYTE, img);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MIN_FILTER, ctx.LINEAR);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_MAG_FILTER, ctx.LINEAR);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_S, ctx.CLAMP_TO_EDGE);
    ctx.texParameteri(ctx.TEXTURE_2D, ctx.TEXTURE_WRAP_T, ctx.CLAMP_TO_EDGE);

    ctx.uniform1i(ctx.getUniformLocation(prog, "tex"), 0);
    ctx.uniform2f(ctx.getUniformLocation(prog, "px"), 1 / img.naturalWidth, 1 / img.naturalHeight);

    var inst = {
      el: el, ctx: ctx, canvas: canvas, img: img, visible: true,
      uLight: ctx.getUniformLocation(prog, "light"),
      uTime: ctx.getUniformLocation(prog, "time"),
      every: parseFloat(el.dataset.sweep) || 6.5,          // период пробега блика
      phase: parseFloat(el.dataset.phase) || 0,            // сдвиг, чтобы логотипы не вспыхивали одновременно
      light: { x: -0.4, y: 0.35 }
    };
    inst.resize = function () {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      var w = Math.max(1, Math.min(Math.round(canvas.clientWidth * dpr), img.naturalWidth));
      var h = Math.round(w * img.naturalHeight / img.naturalWidth);
      if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
      ctx.viewport(0, 0, w, h);
    };
    inst.resize();
    window.addEventListener("resize", function () { inst.resize(); if (still) draw(inst, 0); });
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (en) { inst.visible = en[0].isIntersecting; if (inst.visible) kick(); }).observe(el);
    }
    el.classList.add("is-gl");
    return inst;
  }

  function draw(inst, time) {
    var lr = inst.el.getBoundingClientRect(), L = inst.light, tx, ty;
    var over = pointer.on && pointer.x > lr.left - 30 && pointer.x < lr.right + 30 &&
               pointer.y > lr.top - 30 && pointer.y < lr.bottom + 30;
    if (still) { L.x = 0.25; L.y = 0.2; }
    else {
      if (over) {                                          // над логотипом: свет идёт за курсором
        tx = (pointer.x - lr.left) / lr.width; ty = (pointer.y - lr.top) / lr.height;
        L.x += (tx - L.x) * 0.2; L.y += (ty - L.y) * 0.2;
      } else {                                             // иначе раз в `every` секунд пробегает слева направо
        var k = ((time + inst.phase) % inst.every) / SWEEP_TIME;
        if (k < 1) { var e = k * k * (3 - 2 * k); L.x = -0.35 + e * 1.7; L.y = 0.25 + 0.2 * Math.sin(k * 3.14); }
        else { L.x = 1.35; L.y = 0.35; }
      }
    }
    var c = inst.ctx;
    c.uniform3f(inst.uLight, L.x, L.y, 0.35);
    c.uniform1f(inst.uTime, time);
    c.clearColor(0, 0, 0, 0);
    c.clear(c.COLOR_BUFFER_BIT);
    c.drawArrays(c.TRIANGLE_STRIP, 0, 4);
  }

  /* ---------- общий цикл ---------- */
  var list = [], raf = 0;
  function kick() { if (!raf && list.length && !still) raf = requestAnimationFrame(frame); }
  function frame(t) {
    raf = 0;
    list.forEach(function (inst) { if (inst.visible) draw(inst, t / 1000); });
    raf = requestAnimationFrame(frame);
  }

  logos.forEach(function (el) {
    var img = el.querySelector(".logo3d-img");
    function go() {
      var inst = setup(el);
      if (!inst) return;
      list.push(inst);
      if (still) draw(inst, 0); else kick();
    }
    if (img && !img.complete) img.addEventListener("load", go, { once: true });
    else go();
  });
})();
