import { useEffect, useRef } from 'react';
import { cssVar } from '../../lib/theme';
import styles from './RingField.module.css';

/*
 * Billowing clouds you can push around like wind. The clouds are domain-warped fractal noise that
 * drifts on its own; moving the pointer leaves gusts (where it was, which way and how fast) that
 * displace the clouds nearby and fade over a couple of seconds. Drawn at a fraction of the screen's
 * resolution (clouds are soft), paused off screen and in background tabs, and still when motion is
 * reduced.
 */

const GUSTS = 12;
const SCALE = 0.5; // render resolution relative to CSS pixels
const GUST_EVERY_MS = 45;

const VERT = `
attribute vec2 a_pos;
varying vec2 v_uv;
void main() {
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}`;

const FRAG = `
precision highp float;
varying vec2 v_uv;
uniform vec2 u_res;
uniform float u_time;
uniform vec3 u_sky;
uniform vec3 u_light;
uniform vec3 u_shade;
uniform float u_strength;
uniform vec4 u_gust[${GUSTS}];
uniform float u_age[${GUSTS}];

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}

float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++) {
    v += a * noise(p);
    p = m * p;
    a *= 0.5;
  }
  return v;
}

void main() {
  float aspect = u_res.x / u_res.y;
  vec2 uv = v_uv;
  // Wind: every gust pushes the clouds near it the way the pointer moved, and dies away.
  vec2 push = vec2(0.0);
  for (int i = 0; i < ${GUSTS}; i++) {
    vec2 d = vec2((uv.x - u_gust[i].x) * aspect, uv.y - u_gust[i].y);
    push += u_gust[i].zw * exp(-dot(d, d) * 9.0) * exp(-u_age[i] * 0.8);
  }
  vec2 p = vec2(uv.x * aspect, uv.y) * 2.4 - push * 1.6;
  float t = u_time * 0.02;
  vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, 1.3) - t));
  vec2 r = vec2(fbm(p + 3.0 * q + vec2(1.7, 9.2) + 1.4 * t), fbm(p + 3.0 * q + vec2(8.3, 2.8) - 1.1 * t));
  float body = fbm(p + 2.6 * r + vec2(2.0 * t, 0.0));
  float cloud = smoothstep(0.42, 0.86, body);
  // Lit from above: the tops brighter than the undersides.
  float lit = smoothstep(0.30, 0.95, fbm(p + 2.6 * r + vec2(0.18, 0.26) + vec2(2.0 * t, 0.0)));
  vec3 colour = mix(u_shade, u_light, lit);
  gl_FragColor = vec4(mix(u_sky, colour, cloud * u_strength), 1.0);
}`;

function compile(gl: WebGLRenderingContext, type: number, source: string) {
  const shader = gl.createShader(type);
  if (!shader) return null;
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (gl.getShaderParameter(shader, gl.COMPILE_STATUS)) return shader;
  gl.deleteShader(shader);
  return null;
}

function rgb(color: string, fallback: [number, number, number]): [number, number, number] {
  const hex = /^#?([0-9a-f]{6})$/i.exec(color.trim());
  if (!hex) return fallback;
  const n = parseInt(hex[1], 16);
  return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

const mix = (a: number[], b: number[], t: number) => a.map((v, i) => v + (b[i] - v) * t);

interface CloudFieldProps {
  dark: boolean;
  /** Changing it re-reads the theme colours the clouds are painted with. */
  accent: string;
  still?: boolean;
  className?: string;
}

export function CloudField({ dark, accent, still = false, className }: CloudFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas?.getContext('webgl', { alpha: false, antialias: false, depth: false, preserveDrawingBuffer: false });
    if (!canvas || !gl) return;

    const vert = compile(gl, gl.VERTEX_SHADER, VERT);
    const frag = compile(gl, gl.FRAGMENT_SHADER, FRAG);
    const program = gl.createProgram();
    if (!vert || !frag || !program) return;
    gl.attachShader(program, vert);
    gl.attachShader(program, frag);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return;
    gl.useProgram(program);

    const quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const pos = gl.getAttribLocation(program, 'a_pos');
    gl.enableVertexAttribArray(pos);
    gl.vertexAttribPointer(pos, 2, gl.FLOAT, false, 0, 0);

    const u = {
      res: gl.getUniformLocation(program, 'u_res'),
      time: gl.getUniformLocation(program, 'u_time'),
      sky: gl.getUniformLocation(program, 'u_sky'),
      light: gl.getUniformLocation(program, 'u_light'),
      shade: gl.getUniformLocation(program, 'u_shade'),
      strength: gl.getUniformLocation(program, 'u_strength'),
      gust: gl.getUniformLocation(program, 'u_gust'),
      age: gl.getUniformLocation(program, 'u_age'),
    };

    // The page's own colours: the sky is the background, the clouds a little lighter (a little
    // darker underneath), with a breath of the accent, so text on top keeps its contrast.
    const sky = rgb(cssVar('--bg'), dark ? [0.06, 0.07, 0.08] : [0.96, 0.96, 0.97]);
    const tint = rgb(cssVar('--accent'), [0.06, 0.38, 1]);
    const light = dark ? mix(mix(sky, [1, 1, 1], 0.13), tint, 0.05) : mix(mix(sky, [1, 1, 1], 0.85), tint, 0.03);
    const shade = dark ? mix(sky, [0, 0, 0], 0.25) : mix(sky, [0.55, 0.6, 0.7], 0.18);
    gl.uniform3fv(u.sky, sky);
    gl.uniform3fv(u.light, light);
    gl.uniform3fv(u.shade, shade);
    gl.uniform1f(u.strength, dark ? 0.9 : 0.95);

    const gusts = new Float32Array(GUSTS * 4);
    const born = new Float64Array(GUSTS).fill(-1e9);
    const ages = new Float32Array(GUSTS).fill(1e3);
    let next = 0;

    let width = 1;
    let height = 1;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width * SCALE));
      height = Math.max(1, Math.round(rect.height * SCALE));
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(u.res, width, height);
    };

    const draw = (seconds: number, now: number) => {
      for (let i = 0; i < GUSTS; i++) ages[i] = (now - born[i]) / 1000;
      gl.uniform4fv(u.gust, gusts);
      gl.uniform1fv(u.age, ages);
      gl.uniform1f(u.time, seconds);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };

    let raf = 0;
    let visible = true;
    const started = performance.now() - 30_000;
    const frame = (now: number) => {
      raf = 0;
      draw((now - started) / 1000, now);
      if (!still && visible && !document.hidden) raf = requestAnimationFrame(frame);
    };
    const wake = () => {
      if (!still && !raf && visible && !document.hidden) raf = requestAnimationFrame(frame);
    };

    // Gusts: where the pointer is, which way and how fast it moves (in screen-heights a second).
    let last: { x: number; y: number; t: number } | null = null;
    const onMove = (e: PointerEvent) => {
      if (still) return;
      const rect = canvas.getBoundingClientRect();
      if (e.clientX < rect.left || e.clientX > rect.right || e.clientY < rect.top || e.clientY > rect.bottom) {
        last = null;
        return;
      }
      const now = performance.now();
      const x = (e.clientX - rect.left) / rect.width;
      const y = 1 - (e.clientY - rect.top) / rect.height;
      if (last && now - last.t >= GUST_EVERY_MS) {
        const dt = (now - last.t) / 1000;
        const aspect = rect.width / rect.height;
        const clamp = (v: number) => Math.max(-1.5, Math.min(1.5, v));
        gusts.set([x, y, clamp(((x - last.x) * aspect) / dt) * 0.35, clamp((y - last.y) / dt) * 0.35], next * 4);
        born[next] = now;
        next = (next + 1) % GUSTS;
        last = { x, y, t: now };
        wake();
      } else if (!last) {
        last = { x, y, t: now };
      }
    };

    resize();
    draw(30, performance.now());
    const observer = new ResizeObserver(() => {
      resize();
      draw((performance.now() - started) / 1000, performance.now());
    });
    observer.observe(canvas);
    const seen = new IntersectionObserver((entries) => {
      visible = entries.some((e) => e.isIntersecting);
      wake();
    });
    seen.observe(canvas);
    const onVisibility = () => wake();
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('pointermove', onMove, { passive: true });
    wake();

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      seen.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('pointermove', onMove);
      gl.deleteBuffer(quad);
      gl.deleteProgram(program);
      gl.deleteShader(vert);
      gl.deleteShader(frag);
    };
  }, [dark, accent, still]);

  return <canvas ref={canvasRef} className={`${styles.field} ${className ?? ''}`} aria-hidden="true" />;
}
