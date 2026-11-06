import { useEffect, useRef } from 'react';
import { cssVar } from '../../lib/theme';
import styles from './RingField.module.css';

/*
 * Soft waves of light with a chromatic shimmer. A few slow sine bands cross the screen; each is
 * drawn three times, a hair apart, for red, green and blue, so their edges split into faint
 * rainbow fringes the way light does through glass. On a dark page the light adds to the
 * background; on a light page the waves are pale washes of colour, so text keeps its contrast.
 * The pointer bends the nearest waves a little. Drawn at half resolution, paused when hidden,
 * off screen or `active` is false, and still when motion is reduced.
 */

const SCALE = 0.5;
const BANDS = 5;

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
uniform vec3 u_bg;
uniform vec3 u_tint;
uniform float u_dark;
uniform float u_strength;
uniform vec2 u_pointer;

// Distance from a wave: two sines of different lengths, so the shape never quite repeats.
float wave(vec2 p, float i, float shift) {
  float t = u_time * (0.10 + 0.025 * i);
  float base = 0.18 + i * 0.16;
  float y = base
    + 0.075 * sin(p.x * (1.6 + 0.32 * i) + t * 2.0 + i * 1.7)
    + 0.035 * sin(p.x * (3.1 + 0.21 * i) - t * 1.3 + i * 4.1)
    + shift;
  // The pointer lifts the waves near it.
  vec2 d = p - u_pointer;
  y += 0.05 * exp(-dot(d, d) * 14.0);
  return abs(p.y - y);
}

float glow(float dist, float width) {
  return exp(-(dist * dist) / (width * width)) * 0.85 + exp(-dist / (width * 5.0)) * 0.15;
}

void main() {
  float aspect = u_res.x / u_res.y;
  vec2 p = vec2(v_uv.x * aspect, v_uv.y);
  vec3 light = vec3(0.0);
  for (int k = 0; k < ${BANDS}; k++) {
    float i = float(k);
    float width = 0.012 + 0.006 * i;
    float split = 0.006 + 0.002 * i;        // how far the colours separate
    float weight = 1.0 - i * 0.12;
    light.r += glow(wave(p, i, split), width) * weight;
    light.g += glow(wave(p, i, 0.0), width) * weight;
    light.b += glow(wave(p, i, -split), width) * weight;
  }
  // A slow shimmer of hue along the waves.
  vec3 shimmer = 0.5 + 0.5 * cos(6.2831 * (vec3(0.0, 0.33, 0.67) + p.x * 0.18 + u_time * 0.02));
  vec3 colour = mix(u_tint, shimmer, 0.45);
  vec3 lit = light * mix(vec3(1.0), colour, 0.6);
  vec3 dark = u_bg + lit * u_strength;
  // On a light page: tint the background towards the colour, never darker than a pale wash.
  float amount = clamp(max(light.r, max(light.g, light.b)) * u_strength, 0.0, 1.0);
  vec3 pale = mix(u_bg, mix(colour, vec3(1.0), 0.2), amount * 0.5);
  gl_FragColor = vec4(mix(pale, dark, u_dark), 1.0);
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

interface ChromaWavesProps {
  dark: boolean;
  /** Changing it re-reads the theme colours. */
  accent: string;
  still?: boolean;
  /** False pauses drawing (e.g. while the waves are faded out). */
  active?: boolean;
  className?: string;
}

export function ChromaWaves({ dark, accent, still = false, active = true, className }: ChromaWavesProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const activeRef = useRef(active);
  const wakeRef = useRef<() => void>(() => {});

  useEffect(() => {
    activeRef.current = active;
    wakeRef.current();
  }, [active]);

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

    const u = (name: string) => gl.getUniformLocation(program, name);
    const uRes = u('u_res');
    const uTime = u('u_time');
    const uPointer = u('u_pointer');
    gl.uniform3fv(u('u_bg'), rgb(cssVar('--bg'), dark ? [0.06, 0.07, 0.08] : [0.96, 0.96, 0.97]));
    gl.uniform3fv(u('u_tint'), rgb(cssVar('--accent'), [0.06, 0.38, 1]));
    gl.uniform1f(u('u_dark'), dark ? 1 : 0);
    gl.uniform1f(u('u_strength'), dark ? 0.36 : 0.55);

    let width = 1;
    let height = 1;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width * SCALE));
      height = Math.max(1, Math.round(rect.height * SCALE));
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
      gl.uniform2f(uRes, width, height);
    };

    // The pointer, eased towards where it is, in the shader's coordinates.
    const pointer = { x: -10, y: -10, tx: -10, ty: -10 };
    const onMove = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      pointer.tx = ((e.clientX - rect.left) / rect.width) * (rect.width / Math.max(1, rect.height));
      pointer.ty = 1 - (e.clientY - rect.top) / rect.height;
      if (pointer.x < -5) {
        pointer.x = pointer.tx;
        pointer.y = pointer.ty;
      }
    };

    let raf = 0;
    let visible = true;
    const started = performance.now() - 20_000;
    const draw = (now: number) => {
      pointer.x += (pointer.tx - pointer.x) * 0.06;
      pointer.y += (pointer.ty - pointer.y) * 0.06;
      gl.uniform2f(uPointer, pointer.x, pointer.y);
      gl.uniform1f(uTime, (now - started) / 1000);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };
    const running = () => !still && visible && activeRef.current && !document.hidden;
    const frame = (now: number) => {
      raf = 0;
      draw(now);
      if (running()) raf = requestAnimationFrame(frame);
    };
    const wake = () => {
      if (!raf && running()) raf = requestAnimationFrame(frame);
    };
    wakeRef.current = wake;

    resize();
    draw(performance.now());
    const observer = new ResizeObserver(() => {
      resize();
      draw(performance.now());
    });
    observer.observe(canvas);
    const seen = new IntersectionObserver((entries) => {
      visible = entries.some((e) => e.isIntersecting);
      wake();
    });
    seen.observe(canvas);
    const onVisibility = () => wake();
    document.addEventListener('visibilitychange', onVisibility);
    if (!still) window.addEventListener('pointermove', onMove, { passive: true });
    wake();

    return () => {
      wakeRef.current = () => {};
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
