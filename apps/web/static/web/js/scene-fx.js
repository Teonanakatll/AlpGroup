/* Фото горы в герое: вода и RGB-сдвиг вокруг курсора (WebGL).
   Чем быстрее двигается мышь, тем сильнее рябь; когда курсор замер, всё успокаивается,
   и цикл перерисовки останавливается (экономит батарею). Нет WebGL или «меньше движения» — просто фото. */
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

  var VERT = "attribute vec2 p;varying vec2 uv;void main(){uv=p*.5+.5;uv.y=1.-uv.y;gl_Position=vec4(p,0.,1.);}";
  var FRAG = [
    "precision mediump float;",
    "varying vec2 uv;",
    "uniform sampler2D tex;",
    "uniform vec2 mouse;",      // положение курсора в координатах фото (0..1)
    "uniform float amp;",       // сила эффекта 0..1 (зависит от скорости мыши)
    "uniform float time;",
    "uniform float aspect;",    // ширина/высота фото, чтобы волны были круглыми
    "void main(){",
    "  vec2 d=(uv-mouse)*vec2(aspect,1.);",
    "  float r=length(d);",
    "  vec2 dir=d/max(r,.0001);",
    "  float fall=exp(-r*10.)*amp;",                              // эффект затухает от курсора
    "  float wave=sin(r*70.-time*6.)*fall;",                      // кольца, бегущие от курсора
    "  vec2 off=dir*wave*.005/vec2(aspect,1.);",
    "  vec2 split=dir*fall*.005/vec2(aspect,1.);",                // RGB-расслоение вдоль радиуса
    "  float rr=texture2D(tex,uv+off+split).r;",
    "  float gg=texture2D(tex,uv+off).g;",
    "  float bb=texture2D(tex,uv+off-split).b;",
    "  vec3 col=vec3(rr,gg,bb);",
    "  col+=max(wave,0.)*.12;",                                    // блик на гребнях волн
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

  var u = {
    mouse: gl.getUniformLocation(prog, "mouse"), amp: gl.getUniformLocation(prog, "amp"),
    time: gl.getUniformLocation(prog, "time")
  };

  var state = { mx: 0.5, my: 0.5, amp: 0, last: null, raf: 0, ready: false };

  function upload() {
    canvas.width = img.naturalWidth; canvas.height = img.naturalHeight;
    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.bindTexture(gl.TEXTURE_2D, gl.createTexture());
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.uniform1i(gl.getUniformLocation(prog, "tex"), 0);
    gl.uniform1f(gl.getUniformLocation(prog, "aspect"), img.naturalWidth / img.naturalHeight);
    state.ready = true;
    draw(0);
    scene.classList.add("is-gl");
  }

  // Курсор (экран) -> координаты фото с учётом object-fit: cover и object-position 50% 18%
  function toUV(cx, cy) {
    var r = canvas.getBoundingClientRect();
    var s = Math.max(r.width / canvas.width, r.height / canvas.height);
    var dw = canvas.width * s, dh = canvas.height * s;
    var ox = (r.width - dw) * 0.5, oy = (r.height - dh) * 0.18;
    return { x: (cx - r.left - ox) / dw, y: (cy - r.top - oy) / dh };
  }

  function draw(t) {
    gl.uniform2f(u.mouse, state.mx, state.my);
    gl.uniform1f(u.amp, state.amp);
    gl.uniform1f(u.time, t / 1000);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  function frame(t) {
    state.raf = 0;
    state.amp *= 0.965;                                    // затухание, когда мышь замерла
    draw(t);
    if (state.amp > 0.004) state.raf = requestAnimationFrame(frame);
    else { state.amp = 0; draw(t); }                       // последний чистый кадр, дальше цикл не нужен
  }

  hero.addEventListener("pointermove", function (e) {
    if (!state.ready) return;
    var p = toUV(e.clientX, e.clientY);
    if (state.last) {                                      // скорость мыши -> сила эффекта
      var sp = Math.hypot(e.clientX - state.last.x, e.clientY - state.last.y);
      state.amp = Math.min(1, Math.max(state.amp, sp / 28));
    }
    state.last = { x: e.clientX, y: e.clientY };
    state.mx = p.x; state.my = p.y;
    if (!state.raf) state.raf = requestAnimationFrame(frame);
  });
  hero.addEventListener("pointerleave", function () { state.last = null; });

  if (img.complete && img.naturalWidth) upload();
  else img.addEventListener("load", upload, { once: true });
})();
