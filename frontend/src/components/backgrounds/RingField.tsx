import { useEffect, useRef } from 'react';
import { cssVar } from '../../lib/theme';
import styles from './RingField.module.css';

/*
 * Wavy rings of fine dust drifting outward from a dark centre. Every grain's position is computed
 * in the vertex shader from its seed and the time, so a frame costs one draw call and no work on
 * the main thread. It pauses when off screen or in a background tab, and draws one still frame
 * when motion is reduced.
 */

const RINGS = 18;
const GRAINS = 16000;
const MAX_DPR = 1.5;

const VERT = `
attribute vec4 a_seed;
uniform float u_time;
uniform vec2 u_scale;
uniform float u_reach;
uniform float u_dpr;
varying float v_alpha;
const float RINGS = ${RINGS.toFixed(1)};
void main() {
  float ring = floor(a_seed.x * RINGS);
  float travel = fract(ring / RINGS + u_time * 0.011);
  float wave = sin(a_seed.y * (3.0 + mod(ring, 4.0)) + u_time * 0.32 + ring * 1.7) * 0.05
             + sin(a_seed.y * (7.0 + mod(ring, 3.0)) - u_time * 0.21 + ring) * 0.02;
  float r = 0.07 + travel * u_reach + (wave + (a_seed.z - 0.5) * 0.014) * (0.35 + travel);
  vec2 p = vec2(cos(a_seed.y), sin(a_seed.y)) * r;
  gl_Position = vec4(p * u_scale, 0.0, 1.0);
  v_alpha = smoothstep(0.02, 0.2, travel) * (1.0 - smoothstep(0.72, 1.0, travel)) * (0.3 + 0.7 * a_seed.w);
  gl_PointSize = (0.9 + a_seed.w * 1.5) * u_dpr;
}`;

const FRAG = `
precision mediump float;
uniform vec3 u_color;
uniform float u_opacity;
varying float v_alpha;
void main() {
  float a = smoothstep(0.5, 0.1, length(gl_PointCoord - 0.5)) * v_alpha * u_opacity;
  gl_FragColor = vec4(u_color * a, a);
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

function rgb(color: string): [number, number, number] {
  const hex = /^#?([0-9a-f]{6})$/i.exec(color.trim());
  if (!hex) return [0.6, 0.7, 1];
  const n = parseInt(hex[1], 16);
  return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

interface RingFieldProps {
  /** Light or dark page: pale glowing dust on dark, fine graphite dust on light. */
  dark: boolean;
  /** Changing it re-reads the accent colour the dust is tinted with. */
  accent: string;
  still?: boolean;
  className?: string;
}

export function RingField({ dark, accent, still = false, className }: RingFieldProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const gl = canvas?.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, depth: false });
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

    const seeds = new Float32Array(GRAINS * 4);
    for (let i = 0; i < GRAINS; i++) {
      seeds[i * 4] = Math.random();
      seeds[i * 4 + 1] = Math.random() * Math.PI * 2;
      seeds[i * 4 + 2] = Math.random();
      seeds[i * 4 + 3] = Math.random() ** 2;
    }
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, seeds, gl.STATIC_DRAW);
    const seedAttr = gl.getAttribLocation(program, 'a_seed');
    gl.enableVertexAttribArray(seedAttr);
    gl.vertexAttribPointer(seedAttr, 4, gl.FLOAT, false, 0, 0);

    const u = {
      time: gl.getUniformLocation(program, 'u_time'),
      scale: gl.getUniformLocation(program, 'u_scale'),
      reach: gl.getUniformLocation(program, 'u_reach'),
      dpr: gl.getUniformLocation(program, 'u_dpr'),
      color: gl.getUniformLocation(program, 'u_color'),
      opacity: gl.getUniformLocation(program, 'u_opacity'),
    };

    // Pale, glowing dust on a dark page; darker grains on a light one, both tinted by the accent.
    const tint = rgb(cssVar('--accent'));
    const color = dark
      ? tint.map((c) => 0.55 + c * 0.45)
      : tint.map((c) => 0.06 + c * 0.26);
    gl.uniform3fv(u.color, color);
    gl.uniform1f(u.opacity, dark ? 0.85 : 0.7);
    gl.enable(gl.BLEND);
    if (dark) gl.blendFunc(gl.ONE, gl.ONE);
    else gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.clearColor(0, 0, 0, 0);

    let width = 1;
    let height = 1;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, MAX_DPR);
      const rect = canvas.getBoundingClientRect();
      width = Math.max(1, Math.round(rect.width * dpr));
      height = Math.max(1, Math.round(rect.height * dpr));
      canvas.width = width;
      canvas.height = height;
      gl.viewport(0, 0, width, height);
      // Round rings on any shape of screen, reaching just past the farthest corner.
      const wide = width >= height;
      const sx = wide ? height / width : 1;
      const sy = wide ? 1 : width / height;
      gl.uniform2f(u.scale, sx, sy);
      gl.uniform1f(u.reach, Math.hypot(1 / sx, 1 / sy) * 1.02);
      gl.uniform1f(u.dpr, dpr);
    };

    const draw = (seconds: number) => {
      gl.uniform1f(u.time, seconds);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.drawArrays(gl.POINTS, 0, GRAINS);
    };

    let raf = 0;
    let visible = true;
    const started = performance.now() - 40_000; // start mid-flow, with every ring already out
    const frame = (now: number) => {
      raf = 0;
      draw((now - started) / 1000);
      if (!still && visible && !document.hidden) raf = requestAnimationFrame(frame);
    };
    const wake = () => {
      if (!raf && visible && !document.hidden) raf = requestAnimationFrame(frame);
    };

    resize();
    draw(40);
    const observer = new ResizeObserver(() => {
      resize();
      if (still) draw(40);
    });
    observer.observe(canvas);
    const seen = new IntersectionObserver((entries) => {
      visible = entries.some((e) => e.isIntersecting);
      if (!still) wake();
    });
    seen.observe(canvas);
    const onVisibility = () => {
      if (!still) wake();
    };
    document.addEventListener('visibilitychange', onVisibility);
    if (!still) wake();

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      seen.disconnect();
      document.removeEventListener('visibilitychange', onVisibility);
      gl.deleteBuffer(buffer);
      gl.deleteProgram(program);
      gl.deleteShader(vert);
      gl.deleteShader(frag);
    };
  }, [dark, accent, still]);

  return <canvas ref={canvasRef} className={`${styles.field} ${className ?? ''}`} aria-hidden="true" />;
}
