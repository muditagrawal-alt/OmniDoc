/**
 * Imperative three.js renderer for the knowledge globe. React only creates it,
 * feeds it state (graph, filters, focus, theme, insets) and disposes it.
 *
 * Scene: an opaque body sphere (surface colour, faint fresnel rim), a dotted
 * Fibonacci lattice shell, entities as one InstancedMesh, relations as merged
 * great-circle arcs (LineSegments), and the active entity's relations as a
 * separate thicker accent layer with a slow travelling pulse. Labels, the
 * selection ring and the hover tooltip are DOM elements in an overlay.
 *
 * Rendering is on demand: the RAF loop only runs while something moves
 * (damping, auto-rotate, a camera flight, an inset transition, the pulse) and
 * never while the tab is hidden.
 */
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  InstancedMesh,
  type InterleavedBufferAttribute,
  LineSegments,
  Matrix4,
  Mesh,
  PerspectiveCamera,
  Points,
  Quaternion,
  Raycaster,
  Scene,
  ShaderMaterial,
  SphereGeometry,
  SRGBColorSpace,
  Vector2,
  Vector3,
  WebGLRenderer,
} from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { cssVar } from '../../lib/theme';
import { ALL_FAMILIES } from '../../lib/categories';
import { DEFAULT_FRONT, fibonacciSphere } from './globeLayout';
import type { GraphModel } from './graphModel';

export interface GlobeSceneClassNames {
  canvas: string;
  overlay: string;
  label: string;
  labelActive: string;
  labelStrong: string;
  ring: string;
  tooltip: string;
  tooltipName: string;
  tooltipMeta: string;
  tooltipDot: string;
}

export interface GlobeSceneOptions {
  host: HTMLElement;
  classNames: GlobeSceneClassNames;
  reducedMotion: boolean;
  onSelect: (index: number | null) => void;
}

export interface GlobeInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export interface GlobeFocus {
  selected: number | null;
  matches: ReadonlySet<number> | null;
  isolateFamily: string | null;
}

// ---------------------------------------------------------------- constants
const FOV = 30;
/** Globe diameter as a fraction of the free area's short side. */
const FIT = 0.8;
const MIN_ZOOM = 0.45;
const MAX_ZOOM = 1.9;
const ROTATE_SPEED = 0.45; // OrbitControls units: 2 = one turn per 30 s
const IDLE_RESUME_MS = 6000;
const FLY_MS = 700;
const INSET_MS = 320;
const LATTICE_COUNT = 4800;
const BODY_RADIUS = 0.996;
const MAX_TOP_LABELS = 12;
const MAX_MATCH_LABELS = 30;
const LABEL_GAP = 6;
const CLICK_SLOP = 5;
const POLAR_MARGIN = 0.14;

const DEFAULT_DIR = new Vector3(...DEFAULT_FRONT).normalize();

// ------------------------------------------------------------------ shaders
const BODY_VERT = /* glsl */ `
varying vec3 vN;
varying vec3 vV;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vN = normalize(normalMatrix * normal);
  vV = normalize(-mv.xyz);
  gl_Position = projectionMatrix * mv;
}`;

const BODY_FRAG = /* glsl */ `
uniform vec3 uBody;
uniform vec3 uRim;
uniform float uRimAlpha;
uniform vec3 uOutline;
uniform float uOutlineAlpha;
varying vec3 vN;
varying vec3 vV;
void main() {
  float ndv = clamp(dot(normalize(vN), normalize(vV)), 0.0, 1.0);
  float f = 1.0 - ndv;
  vec3 c = mix(uBody, uRim, pow(f, 5.0) * uRimAlpha);
  c = mix(c, uOutline, smoothstep(0.16, 0.04, ndv) * uOutlineAlpha);
  gl_FragColor = vec4(c, 1.0);
  #include <colorspace_fragment>
}`;

const DOT_VERT = /* glsl */ `
uniform float uSize;
varying float vFade;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vec3 n = normalize(normalMatrix * position);
  float facing = dot(n, normalize(-mv.xyz));
  vFade = smoothstep(0.02, 0.45, facing);
  gl_PointSize = uSize;
  gl_Position = projectionMatrix * mv;
}`;

const DOT_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uAlpha;
varying float vFade;
void main() {
  vec2 p = gl_PointCoord - 0.5;
  float a = smoothstep(0.5, 0.3, length(p)) * vFade;
  if (a <= 0.004) discard;
  gl_FragColor = vec4(uColor, uAlpha * a);
  #include <colorspace_fragment>
}`;

const NODE_VERT = /* glsl */ `
varying vec3 vColor;
varying float vNdv;
void main() {
  vec4 mv = modelViewMatrix * instanceMatrix * vec4(position, 1.0);
  vec3 n = normalize(normalMatrix * mat3(instanceMatrix) * normal);
  vNdv = dot(n, normalize(-mv.xyz));
  vColor = instanceColor;
  gl_Position = projectionMatrix * mv;
}`;

const NODE_FRAG = /* glsl */ `
uniform vec3 uRing;
varying vec3 vColor;
varying float vNdv;
void main() {
  float ndv = clamp(vNdv, 0.0, 1.0);
  vec3 c = vColor * (0.9 + 0.1 * ndv);
  // a hairline of surface colour at the silhouette separates overlapping dots
  c = mix(c, uRing, smoothstep(0.34, 0.16, ndv));
  gl_FragColor = vec4(c, 1.0);
  #include <colorspace_fragment>
}`;

const EDGE_VERT = /* glsl */ `
attribute float aVisible;
varying float vVis;
varying float vFade;
void main() {
  vVis = aVisible;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vec3 n = normalize(normalMatrix * position);
  vFade = smoothstep(-0.15, 0.25, dot(n, normalize(-mv.xyz)));
  gl_Position = projectionMatrix * mv;
}`;

const EDGE_FRAG = /* glsl */ `
uniform vec3 uColor;
uniform float uAlpha;
varying float vVis;
varying float vFade;
void main() {
  if (vVis < 0.5) discard;
  gl_FragColor = vec4(uColor, uAlpha * vFade);
  #include <colorspace_fragment>
}`;

// ------------------------------------------------------------------ helpers
interface Rgba {
  color: Color;
  alpha: number;
}

let probeCtx: CanvasRenderingContext2D | null = null;

/** Parses any CSS colour into a linear-space THREE.Color + alpha. */
function parseColor(input: string, fallback: string): Rgba {
  const rgba = parseCssColor(input) ?? parseCssColor(fallback) ?? [128, 128, 128, 1];
  return {
    color: new Color().setRGB(rgba[0] / 255, rgba[1] / 255, rgba[2] / 255, SRGBColorSpace),
    alpha: rgba[3],
  };
}

function parseCssColor(input: string): [number, number, number, number] | null {
  const s = input.trim();
  if (!s) return null;
  const hex = /^#([0-9a-f]{3,8})$/i.exec(s);
  if (hex) {
    let h = hex[1];
    if (h.length === 3 || h.length === 4) h = [...h].map((c) => c + c).join('');
    if (h.length === 6 || h.length === 8) {
      const v = (i: number) => parseInt(h.slice(i, i + 2), 16);
      return [v(0), v(2), v(4), h.length === 8 ? v(6) / 255 : 1];
    }
  }
  const fn = /^rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+)(%?))?\s*\)$/i.exec(s);
  if (fn) {
    let a = fn[4] === undefined ? 1 : Number(fn[4]);
    if (fn[5] === '%') a /= 100;
    return [Number(fn[1]), Number(fn[2]), Number(fn[3]), a];
  }
  // anything else (oklch, color-mix, named): let the browser resolve it
  try {
    probeCtx ??= document.createElement('canvas').getContext('2d', { willReadFrequently: true });
    if (!probeCtx) return null;
    probeCtx.clearRect(0, 0, 1, 1);
    probeCtx.fillStyle = '#000';
    probeCtx.fillStyle = s;
    probeCtx.fillRect(0, 0, 1, 1);
    const d = probeCtx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  } catch {
    return null;
  }
}

function clamp(v: number, lo: number, hi: number) {
  return v < lo ? lo : v > hi ? hi : v;
}

function smoothstep(a: number, b: number, x: number) {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
}

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

/** Spherical interpolation between unit vectors (handles antipodes). */
function slerpDir(a: Vector3, b: Vector3, t: number, out: Vector3): Vector3 {
  const dot = clamp(a.dot(b), -1, 1);
  const omega = Math.acos(dot);
  if (omega < 1e-5) return out.copy(b);
  const w = new Vector3().copy(b).addScaledVector(a, -dot);
  if (w.lengthSq() < 1e-10) {
    w.set(0, 1, 0).addScaledVector(a, -a.y);
    if (w.lengthSq() < 1e-10) w.set(1, 0, 0).addScaledVector(a, -a.x);
  }
  w.normalize();
  const ang = omega * t;
  return out.copy(a).multiplyScalar(Math.cos(ang)).addScaledVector(w, Math.sin(ang)).normalize();
}

/** Keeps a camera direction inside the OrbitControls polar limits. */
function clampPolar(dir: Vector3): Vector3 {
  const phi = Math.acos(clamp(dir.y, -1, 1));
  const cp = clamp(phi, POLAR_MARGIN, Math.PI - POLAR_MARGIN);
  if (cp === phi) return dir;
  const theta = Math.atan2(dir.x, dir.z);
  return dir.set(Math.sin(cp) * Math.sin(theta), Math.cos(cp), Math.sin(cp) * Math.cos(theta));
}

/**
 * Writes segs+1 points of the great-circle arc from a (radius ra) to b
 * (radius rb), lifted at its middle in proportion to the angular distance.
 */
function arcPoints(
  pos: Float32Array,
  a: number,
  ra: number,
  b: number,
  rb: number,
  segs: number,
  out: Float32Array,
): void {
  const ax = pos[3 * a];
  const ay = pos[3 * a + 1];
  const az = pos[3 * a + 2];
  const bx = pos[3 * b];
  const by = pos[3 * b + 1];
  const bz = pos[3 * b + 2];
  const dot = clamp(ax * bx + ay * by + az * bz, -1, 1);
  const omega = Math.acos(dot);
  let wx = bx - ax * dot;
  let wy = by - ay * dot;
  let wz = bz - az * dot;
  let wl = Math.hypot(wx, wy, wz);
  if (wl < 1e-7) {
    // coincident or antipodal: any perpendicular will do
    wx = -ay;
    wy = ax;
    wz = 0;
    wl = Math.hypot(wx, wy, wz) || 1;
    if (wl < 1e-7) {
      wx = 1;
      wl = 1;
    }
  }
  wx /= wl;
  wy /= wl;
  wz /= wl;
  const lift = 0.004 + 0.13 * omega;
  for (let k = 0; k <= segs; k++) {
    const t = k / segs;
    const ang = omega * t;
    const c = Math.cos(ang);
    const s = Math.sin(ang);
    const r = ra + (rb - ra) * t + lift * Math.sin(Math.PI * t);
    out[3 * k] = (ax * c + wx * s) * r;
    out[3 * k + 1] = (ay * c + wy * s) * r;
    out[3 * k + 2] = (az * c + wz * s) * r;
  }
}

function segmentsFor(pos: Float32Array, a: number, b: number): number {
  const dot = clamp(pos[3 * a] * pos[3 * b] + pos[3 * a + 1] * pos[3 * b + 1] + pos[3 * a + 2] * pos[3 * b + 2], -1, 1);
  return clamp(Math.ceil(Math.acos(dot) / 0.045), 2, 56);
}

type LabelKind = 'active' | 'strong' | 'normal';

interface LabelCandidate {
  index: number;
  kind: LabelKind;
}

interface Flight {
  d0: Vector3;
  d1: Vector3;
  z0: number;
  z1: number;
  t0: number;
  dur: number;
}

interface Palette {
  body: Color;
  rim: Rgba;
  outline: Rgba;
  dot: Rgba;
  edge: Rgba;
  accent: Color;
  families: Map<string, Color>;
}

// -------------------------------------------------------------------- scene
export class GlobeScene {
  private readonly host: HTMLElement;
  private readonly cls: GlobeSceneClassNames;
  private readonly onSelect: (index: number | null) => void;
  private readonly canvas: HTMLCanvasElement;
  private readonly overlay: HTMLDivElement;
  private readonly renderer: WebGLRenderer;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(FOV, 1, 0.05, 60);
  private readonly controls: OrbitControls;
  private readonly raycaster = new Raycaster();

  private readonly bodyGeo = new SphereGeometry(BODY_RADIUS, 96, 64);
  private readonly bodyMat: ShaderMaterial;
  private readonly latticeGeo = new BufferGeometry();
  private readonly latticeMat: ShaderMaterial;
  private readonly nodeGeo = new SphereGeometry(1, 18, 12);
  private readonly nodeMat: ShaderMaterial;
  private readonly edgeMat: ShaderMaterial;
  private readonly hiMat: LineMaterial;

  private nodes: InstancedMesh | null = null;
  private edges: LineSegments | null = null;
  private edgeGeo: BufferGeometry | null = null;
  private edgeRanges: Int32Array = new Int32Array(0); // [start, count] per pair, in vertices
  private hi: LineSegments2 | null = null;
  private hiGeo: LineSegmentsGeometry | null = null;
  private hiT = new Float32Array(0);
  private hiColors = new Float32Array(0);

  private model: GraphModel | null = null;
  private pos: Float32Array = new Float32Array(0); // unit vectors
  private radius = new Float32Array(0); // world radius per node
  private center = new Float32Array(0); // node centres (world)
  private visible: Uint8Array = new Uint8Array(0);
  private emphasis: Uint8Array = new Uint8Array(0); // 0 dim, 1 normal, 2 emphasised
  private focusActive = false;
  private palette: Palette;
  private edgeAlphaScale = 1;

  private selected: number | null = null;
  private hovered: number | null = null;
  private matches: ReadonlySet<number> | null = null;
  private isolateFamily: string | null = null;
  private candidates: LabelCandidate[] = [];
  private readonly labels = new Map<number, HTMLDivElement>();
  private readonly ring: HTMLDivElement;
  private readonly tooltip: HTMLDivElement;
  private readonly tooltipName: HTMLDivElement;
  private readonly tooltipMetaText: HTMLSpanElement;
  private readonly tooltipDot: HTMLSpanElement;
  private readonly widthCache = new Map<string, number>();
  private measureCtx: CanvasRenderingContext2D | null = null;
  private labelFont = '';

  private width = 1;
  private height = 1;
  private dpr = 1;
  private fitDistance = 4;
  private insetsTarget: GlobeInsets = { top: 0, right: 0, bottom: 0, left: 0 };
  private insetsFrom: GlobeInsets = { top: 0, right: 0, bottom: 0, left: 0 };
  private insets: GlobeInsets = { top: 0, right: 0, bottom: 0, left: 0 };
  private insetT0 = -1;

  private flight: Flight | null = null;
  private reducedMotion: boolean;
  private rotateWanted: boolean;
  private idleTimer = 0;
  private interacting = false;
  private raf = 0;
  private needsRender = true;
  private lastFrame = 0;
  private lastPulseRender = 0;
  private disposed = false;
  private pointerDown: { x: number; y: number; t: number } | null = null;
  private readonly resizeObserver: ResizeObserver;
  private readonly cleanups: Array<() => void> = [];

  // scratch
  private readonly v = new Vector3();
  private readonly v2 = new Vector3();
  private readonly m4 = new Matrix4();
  private readonly q = new Quaternion();
  private readonly s3 = new Vector3();
  private readonly ndc = new Vector2();

  constructor(options: GlobeSceneOptions) {
    this.host = options.host;
    this.cls = options.classNames;
    this.onSelect = options.onSelect;
    this.reducedMotion = options.reducedMotion;
    this.rotateWanted = !options.reducedMotion;

    this.canvas = document.createElement('canvas');
    this.canvas.className = this.cls.canvas;
    this.canvas.setAttribute('role', 'img');
    this.canvas.setAttribute('aria-label', 'Knowledge globe');
    this.overlay = document.createElement('div');
    this.overlay.className = this.cls.overlay;
    this.overlay.setAttribute('aria-hidden', 'true');

    // may throw when WebGL is unavailable; nothing is attached yet
    this.renderer = new WebGLRenderer({ canvas: this.canvas, antialias: true, alpha: true, powerPreference: 'default' });
    this.renderer.setClearColor(0x000000, 0);
    this.host.append(this.canvas, this.overlay);

    this.ring = this.div(this.cls.ring);
    this.tooltip = this.div(this.cls.tooltip);
    this.tooltipName = document.createElement('div');
    this.tooltipName.className = this.cls.tooltipName;
    const meta = document.createElement('div');
    meta.className = this.cls.tooltipMeta;
    this.tooltipDot = document.createElement('span');
    this.tooltipDot.className = this.cls.tooltipDot;
    this.tooltipMetaText = document.createElement('span');
    meta.append(this.tooltipDot, this.tooltipMetaText);
    this.tooltip.append(this.tooltipName, meta);
    this.ring.style.opacity = '0';
    this.tooltip.style.opacity = '0';

    this.palette = this.readPalette();

    // body
    this.bodyMat = new ShaderMaterial({
      vertexShader: BODY_VERT,
      fragmentShader: BODY_FRAG,
      uniforms: {
        uBody: { value: new Color() },
        uRim: { value: new Color() },
        uRimAlpha: { value: 0 },
        uOutline: { value: new Color() },
        uOutlineAlpha: { value: 0 },
      },
    });
    const body = new Mesh(this.bodyGeo, this.bodyMat);
    body.renderOrder = 0;
    this.scene.add(body);

    // dotted lattice shell
    this.latticeGeo.setAttribute('position', new BufferAttribute(fibonacciSphere(LATTICE_COUNT), 3));
    this.latticeMat = new ShaderMaterial({
      vertexShader: DOT_VERT,
      fragmentShader: DOT_FRAG,
      transparent: true,
      depthWrite: false,
      uniforms: { uSize: { value: 2 }, uColor: { value: new Color() }, uAlpha: { value: 0.2 } },
    });
    const lattice = new Points(this.latticeGeo, this.latticeMat);
    lattice.renderOrder = 1;
    this.scene.add(lattice);

    this.nodeMat = new ShaderMaterial({
      vertexShader: NODE_VERT,
      fragmentShader: NODE_FRAG,
      uniforms: { uRing: { value: new Color() } },
    });
    this.edgeMat = new ShaderMaterial({
      vertexShader: EDGE_VERT,
      fragmentShader: EDGE_FRAG,
      transparent: true,
      depthWrite: false,
      uniforms: { uColor: { value: new Color() }, uAlpha: { value: 0.2 } },
    });
    this.hiMat = new LineMaterial({
      linewidth: 1.75,
      vertexColors: true,
      transparent: true,
      depthWrite: false,
      worldUnits: false,
    });

    this.applyPalette();

    // camera + controls
    this.camera.position.copy(DEFAULT_DIR).multiplyScalar(this.fitDistance);
    this.camera.lookAt(0, 0, 0);
    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enablePan = false;
    this.controls.enableDamping = !this.reducedMotion;
    this.controls.dampingFactor = 0.08;
    this.controls.rotateSpeed = 0.55;
    this.controls.zoomSpeed = 0.7;
    this.controls.minPolarAngle = POLAR_MARGIN;
    this.controls.maxPolarAngle = Math.PI - POLAR_MARGIN;
    this.controls.autoRotateSpeed = ROTATE_SPEED;
    this.controls.autoRotate = this.rotateWanted;

    this.bindEvents();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.host);
    this.resize();
    if (document.fonts?.ready) {
      void document.fonts.ready.then(() => {
        if (this.disposed) return;
        this.widthCache.clear();
        this.labelFont = '';
        this.requestRender();
      });
    }
  }

  // ------------------------------------------------------------- public API

  setDescription(text: string) {
    this.canvas.setAttribute('aria-label', text);
  }

  /** Replaces the graph. `positions` are unit vectors from computeGlobeLayout. */
  setGraph(model: GraphModel, positions: Float32Array, spacing: number) {
    this.model = model;
    const n = model.entities.length;
    this.pos = positions;
    this.visible = new Uint8Array(n).fill(1);
    this.emphasis = new Uint8Array(n).fill(1);
    this.selected = null;
    this.hovered = null;
    this.clearLabels();

    // node sizes: sqrt(degree), base scaled with typical spacing
    const base = clamp(spacing * 0.13, 0.0065, 0.026);
    this.radius = new Float32Array(n);
    this.center = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const r = base * Math.min(2.6, 0.8 + 0.3 * Math.sqrt(model.entities[i].degree));
      this.radius[i] = r;
      const lift = 1 + r * 0.35;
      this.center[3 * i] = positions[3 * i] * lift;
      this.center[3 * i + 1] = positions[3 * i + 1] * lift;
      this.center[3 * i + 2] = positions[3 * i + 2] * lift;
    }

    // nodes
    if (this.nodes) {
      this.scene.remove(this.nodes);
      this.nodes.dispose();
      this.nodes = null;
    }
    if (n > 0) {
      const mesh = new InstancedMesh(this.nodeGeo, this.nodeMat, n);
      mesh.renderOrder = 3;
      for (let i = 0; i < n; i++) mesh.setColorAt(i, this.palette.body);
      this.nodes = mesh;
      this.scene.add(mesh);
      this.writeNodeMatrices();
      mesh.computeBoundingSphere();
    }

    // relations: merged great-circle arcs
    if (this.edges) {
      this.scene.remove(this.edges);
      this.edgeGeo?.dispose();
      this.edges = null;
      this.edgeGeo = null;
    }
    const pairs = model.pairs;
    const m = pairs.length >> 1;
    this.edgeRanges = new Int32Array(m * 2);
    if (m > 0) {
      let total = 0;
      for (let e = 0; e < m; e++) total += 2 * segmentsFor(positions, pairs[2 * e], pairs[2 * e + 1]);
      const arr = new Float32Array(total * 3);
      const vis = new Float32Array(total).fill(1);
      const tmp = new Float32Array(57 * 3);
      let v = 0;
      for (let e = 0; e < m; e++) {
        const a = pairs[2 * e];
        const b = pairs[2 * e + 1];
        const segs = segmentsFor(positions, a, b);
        arcPoints(positions, a, 1 + this.radius[a] * 0.35, b, 1 + this.radius[b] * 0.35, segs, tmp);
        this.edgeRanges[2 * e] = v;
        this.edgeRanges[2 * e + 1] = segs * 2;
        for (let k = 0; k < segs; k++) {
          arr.set(tmp.subarray(3 * k, 3 * k + 6), 3 * v);
          v += 2;
        }
      }
      const geo = new BufferGeometry();
      geo.setAttribute('position', new BufferAttribute(arr, 3));
      geo.setAttribute('aVisible', new BufferAttribute(vis, 1));
      const lines = new LineSegments(geo, this.edgeMat);
      lines.renderOrder = 2;
      lines.frustumCulled = false;
      this.edgeGeo = geo;
      this.edges = lines;
      this.scene.add(lines);
    }
    this.edgeAlphaScale = clamp(1.9 - 0.4 * Math.log10(Math.max(1, m)), 0.55, 1.5);

    this.refreshFocus();
    this.requestRender();
  }

  /** 1 = shown. Hidden entities (and their relations) disappear entirely. */
  setVisible(mask: Uint8Array) {
    if (!this.model || mask.length !== this.visible.length) return;
    this.visible = mask;
    this.writeNodeMatrices();
    if (this.edgeGeo) {
      const attr = this.edgeGeo.getAttribute('aVisible') as BufferAttribute;
      const arr = attr.array as Float32Array;
      const pairs = this.model.pairs;
      for (let e = 0; e < pairs.length >> 1; e++) {
        const on = mask[pairs[2 * e]] && mask[pairs[2 * e + 1]] ? 1 : 0;
        arr.fill(on, this.edgeRanges[2 * e], this.edgeRanges[2 * e] + this.edgeRanges[2 * e + 1]);
      }
      attr.needsUpdate = true;
    }
    if (this.hovered !== null && !mask[this.hovered]) this.hovered = null;
    this.refreshFocus();
    this.requestRender();
  }

  setFocus(focus: GlobeFocus) {
    const changedSelection = focus.selected !== this.selected;
    this.selected = focus.selected;
    this.matches = focus.matches && focus.matches.size ? focus.matches : null;
    this.isolateFamily = focus.isolateFamily;
    if (changedSelection) {
      if (this.selected !== null) this.pauseRotation();
      else this.scheduleResume();
    }
    this.refreshFocus();
    this.requestRender();
  }

  /** Turns the camera to face an entity (~700 ms ease-out, instant under reduced motion). */
  flyTo(index: number) {
    if (!this.model || index < 0 || index >= this.model.entities.length) return;
    const dir = new Vector3(this.pos[3 * index], this.pos[3 * index + 1], this.pos[3 * index + 2]).normalize();
    this.pauseRotation();
    this.startFlight(clampPolar(dir), Math.min(this.zoomRatio(), 1), FLY_MS);
  }

  resetView() {
    this.pauseRotation();
    this.startFlight(DEFAULT_DIR.clone(), 1, FLY_MS);
    this.scheduleResume();
  }

  zoomBy(factor: number) {
    this.pauseRotation();
    const dir = this.camera.position.clone().normalize();
    this.startFlight(dir, clamp(this.zoomRatio() * factor, MIN_ZOOM, MAX_ZOOM), 260);
    this.scheduleResume();
  }

  setAutoRotate(on: boolean) {
    this.rotateWanted = on && !this.reducedMotion;
    if (this.rotateWanted) this.resumeRotation();
    else this.pauseRotation();
  }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
    this.controls.enableDamping = !reduced;
    if (reduced) this.setAutoRotate(false);
    this.requestRender();
  }

  /** Space taken by chrome; the globe centres and fits in what is left. */
  setInsets(next: GlobeInsets) {
    const t = this.insetsTarget;
    if (t.top === next.top && t.right === next.right && t.bottom === next.bottom && t.left === next.left) return;
    this.insetsFrom = { ...this.insets };
    this.insetsTarget = { ...next };
    if (this.reducedMotion || this.lastFrame === 0) {
      this.insets = { ...next };
      this.insetT0 = -1;
      this.refit();
    } else {
      this.insetT0 = performance.now();
    }
    this.requestRender();
  }

  /** Re-reads the design tokens (call after the theme changes). */
  setTheme() {
    this.palette = this.readPalette();
    this.applyPalette();
    this.refreshFocus();
    this.requestRender();
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this.raf);
    window.clearTimeout(this.idleTimer);
    this.resizeObserver.disconnect();
    for (const fn of this.cleanups) fn();
    this.controls.dispose();
    if (this.nodes) this.nodes.dispose();
    this.edgeGeo?.dispose();
    this.hiGeo?.dispose();
    this.bodyGeo.dispose();
    this.latticeGeo.dispose();
    this.nodeGeo.dispose();
    this.bodyMat.dispose();
    this.latticeMat.dispose();
    this.nodeMat.dispose();
    this.edgeMat.dispose();
    this.hiMat.dispose();
    this.scene.clear();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.canvas.remove();
    this.overlay.remove();
    this.labels.clear();
    this.model = null;
  }

  // ------------------------------------------------------------- internals

  private div(className: string): HTMLDivElement {
    const el = document.createElement('div');
    el.className = className;
    this.overlay.append(el);
    return el;
  }

  private readPalette(): Palette {
    const families = new Map<string, Color>();
    for (const f of ALL_FAMILIES) families.set(f.key, parseColor(cssVar(f.cssVar), '#8c887f').color);
    return {
      body: parseColor(cssVar('--surface'), '#ffffff').color,
      rim: parseColor(cssVar('--globe-rim'), 'rgba(200,122,16,0.1)'),
      outline: parseColor(cssVar('--border-strong'), '#cdc9bd'),
      dot: parseColor(cssVar('--globe-dot'), 'rgba(28,27,25,0.2)'),
      edge: parseColor(cssVar('--globe-edge'), 'rgba(28,27,25,0.22)'),
      accent: parseColor(cssVar('--accent'), '#c87a10').color,
      families,
    };
  }

  private applyPalette() {
    const p = this.palette;
    const bu = this.bodyMat.uniforms;
    (bu.uBody.value as Color).copy(p.body);
    (bu.uRim.value as Color).copy(p.rim.color);
    // A faint atmosphere at the limb, never a glow. The mix happens in linear light,
    // where a little bright amber already reads strongly over a dark body.
    bu.uRimAlpha.value = Math.min(1, p.rim.alpha * 0.6);
    (bu.uOutline.value as Color).copy(p.outline.color);
    bu.uOutlineAlpha.value = 0.55;
    (this.latticeMat.uniforms.uColor.value as Color).copy(p.dot.color);
    this.latticeMat.uniforms.uAlpha.value = p.dot.alpha;
    (this.nodeMat.uniforms.uRing.value as Color).copy(p.body);
    (this.edgeMat.uniforms.uColor.value as Color).copy(p.edge.color);
  }

  private zoomRatio() {
    return this.camera.position.length() / this.fitDistance;
  }

  private writeNodeMatrices() {
    const mesh = this.nodes;
    if (!mesh) return;
    const n = this.radius.length;
    const active = this.hovered ?? this.selected;
    for (let i = 0; i < n; i++) {
      let s = this.visible[i] ? this.radius[i] : 0;
      if (i === active) s *= 1.3;
      this.v.set(this.center[3 * i], this.center[3 * i + 1], this.center[3 * i + 2]);
      this.s3.set(s, s, s);
      this.m4.compose(this.v, this.q.identity(), this.s3);
      mesh.setMatrixAt(i, this.m4);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }

  /** Recomputes emphasis, node colours, the accent arcs and label candidates. */
  private refreshFocus() {
    const model = this.model;
    if (!model) return;
    const n = model.entities.length;
    const active = this.hovered ?? this.selected;
    const emph = this.emphasis;
    const iso = this.isolateFamily;
    const matches = this.matches;
    this.focusActive = iso !== null || active !== null || matches !== null;

    if (!this.focusActive) emph.fill(1);
    else {
      emph.fill(0);
      if (iso !== null) {
        for (const e of model.entities) if (e.family.key === iso) emph[e.index] = 2;
      } else {
        if (matches) for (const i of matches) emph[i] = 2;
        if (active !== null) {
          emph[active] = 2;
          for (const c of model.connections[active]) emph[c.neighbor] = 2;
        }
      }
    }

    // colours
    const mesh = this.nodes;
    if (mesh) {
      const col = new Color();
      const body = this.palette.body;
      for (let i = 0; i < n; i++) {
        const fam = this.palette.families.get(model.entities[i].family.key) ?? body;
        col.copy(fam);
        if (emph[i] === 0) col.lerp(body, 0.74);
        mesh.setColorAt(i, col);
      }
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    }
    this.writeNodeMatrices();
    this.edgeMat.uniforms.uAlpha.value =
      this.palette.edge.alpha * this.edgeAlphaScale * (this.focusActive ? (active !== null ? 0.35 : 0.5) : 1);

    this.buildHighlightArcs(active);
    this.buildCandidates(active);
  }

  private buildHighlightArcs(active: number | null) {
    if (this.hi) {
      this.scene.remove(this.hi);
      this.hiGeo?.dispose();
      this.hi = null;
      this.hiGeo = null;
    }
    const model = this.model;
    if (!model || active === null || !this.visible[active] || this.isolateFamily !== null) return;
    const seen = new Set<number>();
    const targets: number[] = [];
    for (const c of model.connections[active]) {
      if (seen.has(c.neighbor) || !this.visible[c.neighbor]) continue;
      seen.add(c.neighbor);
      targets.push(c.neighbor);
    }
    if (!targets.length) return;
    let segTotal = 0;
    for (const b of targets) segTotal += segmentsFor(this.pos, active, b);
    const positions = new Float32Array(segTotal * 6);
    const ts = new Float32Array(segTotal * 2);
    const tmp = new Float32Array(57 * 3);
    let s = 0;
    for (const b of targets) {
      const segs = segmentsFor(this.pos, active, b);
      arcPoints(this.pos, active, 1 + this.radius[active] * 0.35, b, 1 + this.radius[b] * 0.35, segs, tmp);
      for (let k = 0; k < segs; k++) {
        positions.set(tmp.subarray(3 * k, 3 * k + 6), 6 * s);
        ts[2 * s] = k / segs;
        ts[2 * s + 1] = (k + 1) / segs;
        s++;
      }
    }
    this.hiT = ts;
    this.hiColors = new Float32Array(segTotal * 6);
    const geo = new LineSegmentsGeometry();
    geo.setPositions(positions);
    geo.setColors(this.hiColors);
    this.hiGeo = geo;
    const line = new LineSegments2(geo, this.hiMat);
    line.renderOrder = 4;
    line.frustumCulled = false;
    this.hi = line;
    this.scene.add(line);
    this.writePulse(performance.now());
  }

  /** Colours the accent arcs; a soft highlight travels outward from the active entity. */
  private writePulse(now: number) {
    if (!this.hiGeo) return;
    const accent = this.palette.accent;
    const dim = accent.clone().lerp(this.palette.body, 0.45);
    const head = this.reducedMotion ? -1 : ((now / 1000) * 0.3) % 1;
    const out = this.hiColors;
    const ts = this.hiT;
    for (let k = 0; k < ts.length; k++) {
      let mix = 0.72;
      if (head >= 0) {
        let x = head - ts[k];
        if (x < 0) x += 1;
        mix = 0.55 + 0.45 * Math.exp(-x * 7);
      }
      out[3 * k] = dim.r + (accent.r - dim.r) * mix;
      out[3 * k + 1] = dim.g + (accent.g - dim.g) * mix;
      out[3 * k + 2] = dim.b + (accent.b - dim.b) * mix;
    }
    const attr = this.hiGeo.getAttribute('instanceColorStart') as InterleavedBufferAttribute | undefined;
    if (attr) attr.data.needsUpdate = true;
  }

  private buildCandidates(active: number | null) {
    const model = this.model;
    if (!model) return;
    const out: LabelCandidate[] = [];
    const used = new Set<number>();
    const push = (i: number, kind: LabelKind) => {
      if (used.has(i) || !this.visible[i]) return;
      used.add(i);
      out.push({ index: i, kind });
    };
    if (this.selected !== null) push(this.selected, 'active');
    if (this.hovered !== null) used.add(this.hovered); // the tooltip names it
    if (this.isolateFamily === null) {
      if (active !== null) for (const c of model.connections[active]) push(c.neighbor, 'strong');
      if (this.matches) {
        const ranked = [...this.matches].sort((a, b) => model.entities[b].degree - model.entities[a].degree);
        for (const i of ranked.slice(0, MAX_MATCH_LABELS)) push(i, 'strong');
      }
    }
    let top = 0;
    for (const i of model.byDegree) {
      if (top >= MAX_TOP_LABELS) break;
      if (!this.visible[i]) continue;
      if (this.focusActive && this.emphasis[i] !== 2) continue;
      if (model.entities[i].degree === 0 && model.entities.length > 1) continue;
      push(i, 'normal');
      top++;
    }
    // drop label elements that are no longer candidates
    for (const [i, el] of this.labels) {
      if (!used.has(i) || i === this.hovered) {
        el.remove();
        this.labels.delete(i);
      }
    }
    this.candidates = out;
  }

  private clearLabels() {
    for (const el of this.labels.values()) el.remove();
    this.labels.clear();
    this.candidates = [];
  }

  private labelWidth(text: string, kind: LabelKind, el: HTMLDivElement): number {
    const key = `${kind}\u0000${text}`;
    const hit = this.widthCache.get(key);
    if (hit !== undefined) return hit;
    let w: number;
    if (!this.measureCtx) this.measureCtx = document.createElement('canvas').getContext('2d');
    const style = getComputedStyle(el);
    const font = style.font || `500 12px ${style.fontFamily}`;
    const ctx = this.measureCtx;
    if (ctx) {
      if (this.labelFont !== font) {
        ctx.font = font;
        this.labelFont = font;
      }
      const pad = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 2;
      const max = parseFloat(style.maxWidth) || 220;
      w = Math.min(max, ctx.measureText(text).width + pad);
    } else {
      w = el.offsetWidth;
    }
    this.widthCache.set(key, w);
    return w;
  }

  // ------------------------------------------------------------- camera

  private startFlight(dir: Vector3, zoom: number, duration: number) {
    const d0 = this.camera.position.clone().normalize();
    const z0 = this.zoomRatio();
    if (this.reducedMotion || duration <= 0) {
      this.camera.position.copy(dir).multiplyScalar(this.fitDistance * zoom);
      this.camera.lookAt(0, 0, 0);
      this.flight = null;
      this.controls.update();
      this.requestRender();
      return;
    }
    // drop any inertia so the flight is not fought by damping
    this.controls.enableDamping = false;
    this.controls.update();
    this.flight = { d0, d1: dir.clone().normalize(), z0, z1: zoom, t0: performance.now(), dur: duration };
    this.requestRender();
  }

  private stepFlight(now: number): boolean {
    const f = this.flight;
    if (!f) return false;
    const t = clamp((now - f.t0) / f.dur, 0, 1);
    const e = easeOutCubic(t);
    slerpDir(f.d0, f.d1, e, this.v2);
    const z = f.z0 + (f.z1 - f.z0) * e;
    this.camera.position.copy(this.v2).multiplyScalar(this.fitDistance * z);
    this.camera.lookAt(0, 0, 0);
    if (t >= 1) {
      this.flight = null;
      this.controls.enableDamping = !this.reducedMotion;
    }
    return true;
  }

  private refit() {
    const w = this.width;
    const h = this.height;
    const ins = this.insets;
    const ratio = this.fitDistance > 0 ? this.zoomRatio() : 1;
    const fw = Math.max(80, w - ins.left - ins.right);
    const fh = Math.max(80, h - ins.top - ins.bottom);
    const focal = h / 2 / Math.tan((FOV * Math.PI) / 360);
    const rpx = (FIT * Math.min(fw, fh)) / 2;
    const alpha = Math.atan(rpx / focal);
    this.fitDistance = 1 / Math.sin(alpha);
    this.controls.minDistance = Math.max(1.25, this.fitDistance * MIN_ZOOM);
    this.controls.maxDistance = this.fitDistance * MAX_ZOOM;
    const cx = ins.left + fw / 2;
    const cy = ins.top + fh / 2;
    this.camera.setViewOffset(w, h, w / 2 - cx, h / 2 - cy, w, h);
    if (!this.flight) this.camera.position.setLength(this.fitDistance * ratio);
    this.camera.updateProjectionMatrix();
  }

  private resize() {
    if (this.disposed) return;
    const w = Math.max(1, this.host.clientWidth);
    const h = Math.max(1, this.host.clientHeight);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (w === this.width && h === this.height && dpr === this.dpr) return;
    this.width = w;
    this.height = h;
    this.dpr = dpr;
    this.renderer.setPixelRatio(dpr);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.hiMat.resolution.set(w, h);
    this.latticeMat.uniforms.uSize.value = (w < 520 ? 1.6 : 1.9) * dpr;
    this.refit();
    this.requestRender();
  }

  // ------------------------------------------------------------- rotation

  private pauseRotation() {
    window.clearTimeout(this.idleTimer);
    this.controls.autoRotate = false;
  }

  private scheduleResume() {
    window.clearTimeout(this.idleTimer);
    if (!this.rotateWanted) return;
    this.idleTimer = window.setTimeout(() => this.resumeRotation(), IDLE_RESUME_MS);
  }

  private resumeRotation() {
    window.clearTimeout(this.idleTimer);
    if (!this.rotateWanted || this.reducedMotion || this.disposed) return;
    if (this.selected !== null || this.hovered !== null || this.interacting) {
      this.scheduleResume();
      return;
    }
    this.controls.autoRotate = true;
    this.requestRender();
  }

  // ------------------------------------------------------------- events

  private bindEvents() {
    const c = this.canvas;
    const on = <K extends keyof HTMLElementEventMap>(
      target: HTMLElement,
      type: K,
      fn: (ev: HTMLElementEventMap[K]) => void,
      opts?: AddEventListenerOptions,
    ) => {
      target.addEventListener(type, fn, opts);
      this.cleanups.push(() => target.removeEventListener(type, fn, opts));
    };

    const onChange = () => this.requestRender();
    const onStart = () => {
      this.interacting = true;
      this.flight = null;
      this.controls.enableDamping = !this.reducedMotion;
      this.pauseRotation();
    };
    const onEnd = () => {
      this.interacting = false;
      this.scheduleResume();
    };
    this.controls.addEventListener('change', onChange);
    this.controls.addEventListener('start', onStart);
    this.controls.addEventListener('end', onEnd);
    this.cleanups.push(() => {
      this.controls.removeEventListener('change', onChange);
      this.controls.removeEventListener('start', onStart);
      this.controls.removeEventListener('end', onEnd);
    });

    on(c, 'pointermove', (ev) => {
      if (ev.pointerType === 'touch') return;
      if (ev.buttons !== 0) {
        if (this.hovered !== null) this.setHovered(null);
        c.style.cursor = 'grabbing';
        return;
      }
      this.setHovered(this.pick(ev.clientX, ev.clientY));
    });
    on(c, 'pointerleave', () => this.setHovered(null));
    on(c, 'pointerdown', (ev) => {
      this.pointerDown = { x: ev.clientX, y: ev.clientY, t: performance.now() };
      this.pauseRotation();
    });
    on(c, 'pointerup', (ev) => {
      const d = this.pointerDown;
      this.pointerDown = null;
      c.style.cursor = this.hovered !== null ? 'pointer' : 'grab';
      if (!d) return;
      const moved = Math.hypot(ev.clientX - d.x, ev.clientY - d.y);
      if (moved > CLICK_SLOP || performance.now() - d.t > 700) {
        this.scheduleResume();
        return;
      }
      const hit = this.pick(ev.clientX, ev.clientY);
      this.onSelect(hit);
      if (hit === null) this.scheduleResume();
    });
    on(c, 'dblclick', (ev) => {
      if (this.pick(ev.clientX, ev.clientY) === null) this.resetView();
    });
    on(c, 'wheel', () => this.pauseRotation(), { passive: true });

    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(this.raf);
        this.raf = 0;
      } else {
        this.lastFrame = 0;
        this.requestRender();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    this.cleanups.push(() => document.removeEventListener('visibilitychange', onVisibility));
    c.style.cursor = 'grab';
  }

  private setHovered(index: number | null) {
    if (index === this.hovered) return;
    this.hovered = index;
    this.canvas.style.cursor = index !== null ? 'pointer' : 'grab';
    if (index !== null) this.pauseRotation();
    else this.scheduleResume();
    this.refreshFocus();
    this.requestRender();
  }

  /** Raycast against the instanced entities; falls back to the nearest dot within a 24px target. */
  private pick(clientX: number, clientY: number): number | null {
    const model = this.model;
    const mesh = this.nodes;
    if (!model || !mesh) return null;
    const rect = this.canvas.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;
    this.ndc.set((x / rect.width) * 2 - 1, -(y / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.ndc, this.camera);
    const camLen = this.camera.position.length();
    const horizon = 1 / camLen;
    const camDir = this.v2.copy(this.camera.position).normalize();

    const hits = this.raycaster.intersectObject(mesh, false);
    for (const h of hits) {
      const i = h.instanceId;
      if (i === undefined || !this.visible[i]) continue;
      if (this.facing(i, camDir) > horizon) return i;
    }

    // nearest front-facing dot in screen space
    const focal = this.height / 2 / Math.tan((FOV * Math.PI) / 360);
    let best: number | null = null;
    let bestD = Infinity;
    for (let i = 0; i < this.radius.length; i++) {
      if (!this.visible[i]) continue;
      if (this.facing(i, camDir) <= horizon + 0.02) continue;
      this.v.set(this.center[3 * i], this.center[3 * i + 1], this.center[3 * i + 2]);
      const depth = this.v.distanceTo(this.camera.position);
      this.v.project(this.camera);
      const sx = ((this.v.x + 1) / 2) * this.width;
      const sy = ((1 - this.v.y) / 2) * this.height;
      const rpx = (this.radius[i] * focal) / depth;
      const reach = Math.max(12, rpx + 8);
      const d = Math.hypot(sx - x, sy - y);
      if (d < reach && d - rpx < bestD) {
        bestD = d - rpx;
        best = i;
      }
    }
    return best;
  }

  private facing(i: number, camDir: Vector3): number {
    return this.pos[3 * i] * camDir.x + this.pos[3 * i + 1] * camDir.y + this.pos[3 * i + 2] * camDir.z;
  }

  // ------------------------------------------------------------- loop

  private requestRender() {
    this.needsRender = true;
    this.ensureLoop();
  }

  private ensureLoop() {
    if (this.raf || this.disposed || document.hidden) return;
    this.raf = requestAnimationFrame(this.tick);
  }

  private readonly tick = (now: number) => {
    this.raf = 0;
    if (this.disposed) return;
    const dt = this.lastFrame ? Math.min(0.05, (now - this.lastFrame) / 1000) : 1 / 60;
    this.lastFrame = now;
    let animating = false;

    if (this.insetT0 >= 0) {
      const t = clamp((now - this.insetT0) / INSET_MS, 0, 1);
      const e = easeOutCubic(t);
      const a = this.insetsFrom;
      const b = this.insetsTarget;
      this.insets = {
        top: a.top + (b.top - a.top) * e,
        right: a.right + (b.right - a.right) * e,
        bottom: a.bottom + (b.bottom - a.bottom) * e,
        left: a.left + (b.left - a.left) * e,
      };
      this.refit();
      if (t >= 1) this.insetT0 = -1;
      animating = true;
    }

    if (this.stepFlight(now)) animating = true;
    const moved = this.controls.update(dt);
    if (moved || this.controls.autoRotate) animating = true;

    let pulseOnly = false;
    if (this.hi && !this.reducedMotion) {
      if (!animating) pulseOnly = true;
      animating = true;
    }

    // the pulse alone only needs ~30 fps
    const skip = pulseOnly && !this.needsRender && now - this.lastPulseRender < 32;
    if (!skip && (this.needsRender || animating)) {
      if (this.hi && !this.reducedMotion) {
        this.writePulse(now);
        this.lastPulseRender = now;
      }
      this.renderer.render(this.scene, this.camera);
      this.updateOverlay();
      this.needsRender = false;
    }
    if (animating) this.ensureLoop();
  };

  // ------------------------------------------------------------- overlay

  private updateOverlay() {
    const model = this.model;
    if (!model) return;
    const w = this.width;
    const h = this.height;
    const ins = this.insets;
    const camPos = this.camera.position;
    const camLen = camPos.length();
    const horizon = 1 / camLen;
    const camDir = this.v2.copy(camPos).normalize();
    const focal = h / 2 / Math.tan((FOV * Math.PI) / 360);
    const placed: Array<[number, number, number, number]> = [];
    const minX = ins.left + 4;
    const maxX = w - ins.right - 4;
    const minY = ins.top + 4;
    const maxY = h - ins.bottom - 4;

    const screen = (i: number) => {
      this.v.set(this.center[3 * i], this.center[3 * i + 1], this.center[3 * i + 2]);
      const depth = this.v.distanceTo(camPos);
      this.v.project(this.camera);
      return {
        x: ((this.v.x + 1) / 2) * w,
        y: ((1 - this.v.y) / 2) * h,
        r: (this.radius[i] * focal) / depth,
      };
    };
    const fadeOf = (i: number) => smoothstep(horizon + 0.03, horizon + 0.22, this.facing(i, camDir));

    // selection ring (in --text via CSS)
    const sel = this.selected;
    if (sel !== null && this.visible[sel] && fadeOf(sel) > 0.01) {
      const p = screen(sel);
      const size = Math.max(16, 2 * p.r * 1.3 + 10);
      this.ring.style.width = `${size}px`;
      this.ring.style.height = `${size}px`;
      this.ring.style.transform = `translate3d(${p.x - size / 2}px, ${p.y - size / 2}px, 0)`;
      this.ring.style.opacity = String(fadeOf(sel));
      placed.push([p.x - size / 2, p.y - size / 2, p.x + size / 2, p.y + size / 2]);
    } else {
      this.ring.style.opacity = '0';
    }

    // hover tooltip
    const hov = this.hovered;
    if (hov !== null && hov !== sel && this.visible[hov]) {
      const e = model.entities[hov];
      if (this.tooltip.dataset.index !== String(hov)) {
        this.tooltip.dataset.index = String(hov);
        this.tooltipName.textContent = e.name;
        this.tooltipMetaText.textContent = e.category;
        this.tooltipDot.style.background = `var(${e.family.cssVar})`;
      }
      const p = screen(hov);
      const tw = this.tooltip.offsetWidth;
      const th = this.tooltip.offsetHeight;
      let tx = p.x + p.r + 10;
      let ty = p.y - th - p.r - 6;
      if (tx + tw > w - 8) tx = p.x - p.r - 10 - tw;
      if (ty < 8) ty = p.y + p.r + 10;
      this.tooltip.style.transform = `translate3d(${Math.max(8, tx)}px, ${ty}px, 0)`;
      this.tooltip.style.opacity = '1';
    } else {
      this.tooltip.style.opacity = '0';
      delete this.tooltip.dataset.index;
    }

    // labels, highest priority first, skipping collisions
    for (const cand of this.candidates) {
      const i = cand.index;
      let el = this.labels.get(i);
      const fade = fadeOf(i);
      if (fade <= 0.02) {
        if (el) el.style.opacity = '0';
        continue;
      }
      if (!el) {
        el = document.createElement('div');
        el.textContent = model.entities[i].name;
        this.overlay.append(el);
        this.labels.set(i, el);
      }
      const cls =
        cand.kind === 'active'
          ? `${this.cls.label} ${this.cls.labelActive}`
          : cand.kind === 'strong'
            ? `${this.cls.label} ${this.cls.labelStrong}`
            : this.cls.label;
      if (el.className !== cls) el.className = cls;
      const p = screen(i);
      const lw = this.labelWidth(model.entities[i].name, cand.kind, el);
      const lh = cand.kind === 'active' ? 24 : 16;
      const gap = cand.kind === 'active' ? p.r * 1.3 + 10 : p.r + LABEL_GAP;
      let x = p.x + gap;
      const y = p.y - lh / 2;
      let ok = this.fits(x, y, lw, lh, placed, minX, maxX, minY, maxY);
      if (!ok) {
        x = p.x - gap - lw;
        ok = this.fits(x, y, lw, lh, placed, minX, maxX, minY, maxY);
      }
      if (!ok && cand.kind === 'active') {
        x = clamp(p.x - lw / 2, minX, maxX - lw);
        ok = true;
      }
      if (!ok) {
        el.style.opacity = '0';
        continue;
      }
      placed.push([x - 3, y - 2, x + lw + 3, y + lh + 2]);
      el.style.transform = `translate3d(${Math.round(x)}px, ${Math.round(y)}px, 0)`;
      el.style.opacity = String(Math.round(fade * 100) / 100);
    }
  }

  private fits(
    x: number,
    y: number,
    w: number,
    h: number,
    placed: Array<[number, number, number, number]>,
    minX: number,
    maxX: number,
    minY: number,
    maxY: number,
  ): boolean {
    if (x < minX || x + w > maxX || y < minY || y + h > maxY) return false;
    for (const b of placed) if (x < b[2] && x + w > b[0] && y < b[3] && y + h > b[1]) return false;
    return true;
  }
}
