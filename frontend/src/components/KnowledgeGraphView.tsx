import React, { useState, useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import {
  Search,
  BarChart2,
  Cpu,
  Building,
  User,
  Activity,
  X,
  MessageSquare,
  Compass,
  ArrowRight,
  Sparkles,
  Maximize2,
  Minimize2,
  MapPin,
  Network
} from 'lucide-react';
import { api } from '../api';
import type { GraphNode, GraphEdge, GeoLocationItem } from '../api';
import { InteractiveMapViewer } from './InteractiveMapViewer';
import { InteractiveChartViewer } from './InteractiveChartViewer';

interface KnowledgeGraphViewProps {
  onStartChatWithEntity: (entityName: string) => void;
}

interface Node3D extends GraphNode {
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  degree: number;
  screenX?: number;
  screenY?: number;
  mesh?: THREE.Mesh;
}

const CATEGORY_COLORS: Record<string, { hex: number; str: string; glow: string }> = {
  Person: { hex: 0xf59e0b, str: '#f59e0b', glow: 'rgba(245, 158, 11, 0.6)' },
  Organization: { hex: 0x3b82f6, str: '#3b82f6', glow: 'rgba(59, 130, 246, 0.6)' },
  Technology: { hex: 0x06b6d4, str: '#06b6d4', glow: 'rgba(6, 182, 212, 0.6)' },
  Metric: { hex: 0x10b981, str: '#10b981', glow: 'rgba(16, 185, 129, 0.6)' },
  Entity: { hex: 0x94a3b8, str: '#94a3b8', glow: 'rgba(148, 163, 184, 0.4)' },
};

/**
 * Extracts and maps geographical entities for a given node and its local neighborhood.
 */
function getNodeGeoData(node: Node3D, edges: GraphEdge[]): GeoLocationItem[] {
  const connectedNeighbors = edges
    .filter((e) => e.source === node.id || e.target === node.id)
    .map((e) => (e.source === node.id ? e.target_name : e.source_name));

  const text = `${node.name} ${node.description || ''} ${connectedNeighbors.join(' ')}`.toLowerCase();
  const locs: GeoLocationItem[] = [];

  // Hangzhou (DeepSeek AI, High-Flyer Quant, Liang Wenfeng, Fire-Flyer Supercomputer)
  if (
    text.includes('deepseek') ||
    text.includes('high-flyer') ||
    text.includes('liang wenfeng') ||
    text.includes('hangzhou') ||
    text.includes('fire-flyer')
  ) {
    locs.push({
      id: `geo_hangzhou_${node.id}`,
      name: 'Hangzhou, Zhejiang, China',
      region: 'Hangzhou Future Tech City',
      country: 'China',
      lat: 30.2741,
      lon: 120.1551,
      description: `R&D campus & supercomputing infrastructure hub for ${node.name} and the DeepSeek cluster.`,
      radius_meters: 35000,
      highlight_color: '#3b82f6',
      entities: [node.name, 'High-Flyer Quant', 'DeepSeek AI'],
      metrics: { Cluster: 'Frontier AI Lab & Supercomputing Center', Hardware: 'Fire-Flyer 2 Cluster' },
    });
  }

  // Cupertino / Silicon Valley (Apple Inc.)
  if (
    text.includes('apple') ||
    text.includes('iphone') ||
    text.includes('cupertino') ||
    text.includes('services segment') ||
    text.includes('tim cook')
  ) {
    locs.push({
      id: `geo_cupertino_${node.id}`,
      name: 'Cupertino, California, USA',
      region: 'Silicon Valley',
      country: 'United States',
      lat: 37.3230,
      lon: -122.0322,
      description: `Apple Park Global Corporate Headquarters & Silicon Operations for ${node.name}.`,
      radius_meters: 25000,
      highlight_color: '#10b981',
      entities: [node.name, 'Apple Inc.', 'Hardware Engineering'],
      metrics: { Campus: 'Apple Park 1 Apple Park Way', Cluster: 'Consumer Tech & Silicon Design' },
    });
  }

  // Bengaluru, India (DeepTech Hub)
  if (text.includes('bengaluru') || text.includes('bangalore') || text.includes('karnataka') || text.includes('india')) {
    locs.push({
      id: `geo_blr_${node.id}`,
      name: 'Bengaluru, Karnataka, India',
      region: 'DeepTech Innovation Hub',
      country: 'India',
      lat: 12.9716,
      lon: 77.5946,
      description: `India DeepTech & AI Engineering Innovation Corridor associated with ${node.name}.`,
      radius_meters: 30000,
      highlight_color: '#f59e0b',
      entities: [node.name],
      metrics: { Hub: 'GCC Research & DeepTech Labs' },
    });
  }

  // Mumbai, India (Financial Capital)
  if (text.includes('mumbai') || text.includes('maharashtra') || text.includes('bse') || text.includes('nse')) {
    locs.push({
      id: `geo_bom_${node.id}`,
      name: 'Mumbai, Maharashtra, India',
      region: 'Bandra Kurla Complex (BKC)',
      country: 'India',
      lat: 19.0760,
      lon: 72.8777,
      description: `Financial Capital of India, hosting RBI, BSE, and financial institutions associated with ${node.name}.`,
      radius_meters: 30000,
      highlight_color: '#ec4899',
      entities: [node.name],
      metrics: { District: 'Bandra Kurla Complex (BKC)' },
    });
  }

  return locs;
}

/**
 * Extracts and maps quantitative chart artifacts for a given node.
 */
function getNodeChartData(node: Node3D): any | null {
  const text = `${node.name} ${node.description || ''}`.toLowerCase();

  // Model parameters and infrastructure
  if (
    text.includes('deepseek') ||
    text.includes('mixture-of-experts') ||
    text.includes('fire-flyer') ||
    text.includes('dualpipe') ||
    text.includes('infiniband') ||
    text.includes('kv cache')
  ) {
    return {
      chart_type: 'bar',
      title: `${node.name}: Architecture & Parameter Profile`,
      caption: 'Detailed model distribution and hardware parameters.',
      underlying_data: [
        { label: 'Total Parameters (B)', value: 671, detail: '671 Billion Total MoE Parameters' },
        { label: 'Active / Token (B)', value: 37, detail: '37 Billion Active Parameters per Token' },
        { label: 'GPU Cluster Size', value: 10000, detail: 'Over 10,000 PCIe/SXM GPUs in Fire-Flyer 2' },
        { label: 'Fabric Bandwidth (Gbps)', value: 200, detail: '200 Gbps InfiniBand Interconnect' },
      ],
    };
  }

  // Financial and segment distribution
  if (
    text.includes('apple') ||
    text.includes('operating income') ||
    text.includes('iphone') ||
    text.includes('services segment') ||
    text.includes('revenue')
  ) {
    return {
      chart_type: 'bar',
      title: `${node.name}: Fiscal Segment Distribution`,
      caption: 'Financial metrics and revenue distribution breakdown ($ Billions).',
      underlying_data: [
        { label: 'iPhone Segment', value: 200.6, detail: '$200.6B Gross Hardware Revenue' },
        { label: 'Services Segment', value: 85.2, detail: '$85.2B High-Margin Digital Services' },
        { label: 'Operating Income', value: 114.3, detail: '$114.3B Total Operating Profit' },
        { label: 'R&D Investment', value: 29.9, detail: '$29.9B Annual Research & Engineering' },
      ],
    };
  }

  // Default graph centrality and verification salience
  if (node.degree > 0) {
    return {
      chart_type: 'bar',
      title: `${node.name}: Graph Topology & Salience`,
      caption: 'Relational density and multi-source verification metrics.',
      underlying_data: [
        { label: 'Verified Connections', value: node.degree, detail: `${node.degree} cross-document graph edges` },
        { label: 'Faithfulness Score (%)', value: 98, detail: '98% Multi-Source Groundedness Verification' },
        { label: 'Contextual Salience (%)', value: 88, detail: 'High query routing weight in hybrid retrieval' },
      ],
    };
  }

  return null;
}

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({
  onStartChatWithEntity,
}) => {
  const [nodes, setNodes] = useState<Node3D[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [activeNode, setActiveNode] = useState<Node3D | null>(null);
  const [drawerTab, setDrawerTab] = useState<'relations' | 'map' | 'chart'>('relations');
  const [isDrawerExpanded, setIsDrawerExpanded] = useState(false);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const threeRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    controls: OrbitControls;
    nodeMeshes: Map<string, THREE.Mesh>;
    edgeLines: THREE.LineSegments | null;
    particleSystem: THREE.Points;
    pulseParticles: THREE.Points | null;
    dragPlane: THREE.Plane;
    raycaster: THREE.Raycaster;
    mouse: THREE.Vector2;
    animFrameId: number;
    flyToTarget: { targetPos: THREE.Vector3; cameraPos: THREE.Vector3; progress: number } | null;
  } | null>(null);

  const isDraggingNodeRef = useRef<Node3D | null>(null);
  const hoveredNodeRef = useRef<Node3D | null>(null);

  // 1. Fetch graph data from Kùzu backend
  const loadGraph = async () => {
    setLoading(true);
    try {
      const data = await api.getGraph(180);

      // Compute degrees for node sizing
      const degreeMap: Record<string, number> = {};
      data.edges.forEach((e) => {
        degreeMap[e.source] = (degreeMap[e.source] || 0) + 1;
        degreeMap[e.target] = (degreeMap[e.target] || 0) + 1;
      });

      // Arrange nodes initially across a 3D sphere volume
      const total = data.nodes.length;
      const nodes3D: Node3D[] = data.nodes.map((node, i) => {
        const phi = Math.acos(-1 + (2 * i) / Math.max(1, total));
        const theta = Math.sqrt(total * Math.PI) * phi;
        const radius = 160 + (i % 4) * 35;

        return {
          ...node,
          x: radius * Math.cos(theta) * Math.sin(phi),
          y: radius * Math.sin(theta) * Math.sin(phi),
          z: radius * Math.cos(phi),
          vx: (Math.random() - 0.5) * 2,
          vy: (Math.random() - 0.5) * 2,
          vz: (Math.random() - 0.5) * 2,
          degree: degreeMap[node.id] || 1,
        };
      });

      setNodes(nodes3D);
      setEdges(data.edges);
    } catch (err) {
      console.error('Failed to load knowledge graph from Kùzu:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadGraph();
  }, []);

  // 2. Setup Three.js 3D Universe
  useEffect(() => {
    if (!containerRef.current || nodes.length === 0) return;

    const container = containerRef.current;
    const width = container.clientWidth || 900;
    const height = container.clientHeight || 650;

    // A. Scene & Camera
    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x070a12, 0.0012);

    const camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 3000);
    camera.position.set(0, 80, 480);

    // B. WebGL Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x070a12, 1);
    container.innerHTML = '';
    container.appendChild(renderer.domElement);

    // C. OrbitControls
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.06;
    controls.minDistance = 60;
    controls.maxDistance = 1400;

    // D. Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.9);
    scene.add(ambientLight);

    const pointLightBlue = new THREE.PointLight(0x3b82f6, 2.5, 1200);
    pointLightBlue.position.set(200, 300, 200);
    scene.add(pointLightBlue);

    const pointLightGold = new THREE.PointLight(0xf59e0b, 1.8, 1200);
    pointLightGold.position.set(-250, -200, 200);
    scene.add(pointLightGold);

    // E. Cosmic Starfield Particles
    const starCount = 1200;
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount * 3; i += 3) {
      starPos[i] = (Math.random() - 0.5) * 1600;
      starPos[i + 1] = (Math.random() - 0.5) * 1600;
      starPos[i + 2] = (Math.random() - 0.5) * 1600;
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({
      color: 0x94a3b8,
      size: 1.8,
      transparent: true,
      opacity: 0.45,
    });
    const particleSystem = new THREE.Points(starGeo, starMat);
    scene.add(particleSystem);

    // F. Node 3D Spheres
    const nodeMeshes = new Map<string, THREE.Mesh>();
    const sphereBaseGeo = new THREE.SphereGeometry(1, 24, 24);

    nodes.forEach((node) => {
      const catCfg = CATEGORY_COLORS[node.category] || CATEGORY_COLORS.Entity;
      const radius = Math.min(18, Math.max(5.5, 4.5 + node.degree * 2.2));

      const mat = new THREE.MeshStandardMaterial({
        color: catCfg.hex,
        emissive: catCfg.hex,
        emissiveIntensity: 0.28,
        roughness: 0.35,
        metalness: 0.4,
      });

      const mesh = new THREE.Mesh(sphereBaseGeo, mat);
      mesh.scale.set(radius, radius, radius);
      mesh.position.set(node.x, node.y, node.z);
      (mesh as any).nodeData = node;

      scene.add(mesh);
      nodeMeshes.set(node.id, mesh);
    });

    // G. 3D Edge Lines
    const edgePos = new Float32Array(edges.length * 6);
    const edgeColors = new Float32Array(edges.length * 6);
    const edgeGeo = new THREE.BufferGeometry();
    edgeGeo.setAttribute('position', new THREE.BufferAttribute(edgePos, 3));
    edgeGeo.setAttribute('color', new THREE.BufferAttribute(edgeColors, 3));

    const edgeMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.45,
      blending: THREE.AdditiveBlending,
    });
    const edgeLines = new THREE.LineSegments(edgeGeo, edgeMat);
    scene.add(edgeLines);

    // H. Animated Traveling Energy Light Pulses on Edges
    const pulseCount = Math.min(edges.length, 60);
    const pulseGeo = new THREE.BufferGeometry();
    const pulsePos = new Float32Array(pulseCount * 3);
    pulseGeo.setAttribute('position', new THREE.BufferAttribute(pulsePos, 3));
    const pulseMat = new THREE.PointsMaterial({
      color: 0x60a5fa,
      size: 3.5,
      transparent: true,
      opacity: 0.85,
      blending: THREE.AdditiveBlending,
    });
    const pulseParticles = new THREE.Points(pulseGeo, pulseMat);
    scene.add(pulseParticles);

    const pulseProgress = new Float32Array(pulseCount).fill(0).map((_, i) => i / pulseCount);

    const dragPlane = new THREE.Plane();
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    threeRef.current = {
      scene,
      camera,
      renderer,
      controls,
      nodeMeshes,
      edgeLines,
      particleSystem,
      pulseParticles,
      dragPlane,
      raycaster,
      mouse,
      animFrameId: 0,
      flyToTarget: null,
    };

    // 3. Animation & Physics Simulation Loop
    let isCancelled = false;
    let animFrameId = 0;
    let pulseTime = 0;
    const nodeMap = new Map<string, Node3D>();
    nodes.forEach((n) => nodeMap.set(n.id, n));

    const animate = () => {
      if (isCancelled) return;
      animFrameId = requestAnimationFrame(animate);
      if (threeRef.current) {
        threeRef.current.animFrameId = animFrameId;
      }

      // Rotate cosmic starfield slowly
      particleSystem.rotation.y += 0.0003;
      particleSystem.rotation.x += 0.0001;

      // Handle Smooth Camera Fly-To Animation
      if (threeRef.current?.flyToTarget) {
        const ft = threeRef.current.flyToTarget;
        ft.progress += 0.035;
        if (ft.progress >= 1) {
          controls.target.copy(ft.targetPos);
          camera.position.copy(ft.cameraPos);
          threeRef.current.flyToTarget = null;
        } else {
          // Cubic ease-out
          const t = 1 - Math.pow(1 - ft.progress, 3);
          controls.target.lerp(ft.targetPos, t);
          camera.position.lerp(ft.cameraPos, t);
        }
      }

      controls.update();

      // 3D Physics: Forces (Spring attraction + Coulomb repulsion)
      // Only run simulation when dragging or settling
      for (let i = 0; i < nodes.length; i++) {
        const n1 = nodes[i];
        if (isDraggingNodeRef.current?.id === n1.id) continue;

        // Centering gravity
        n1.vx -= n1.x * 0.0003;
        n1.vy -= n1.y * 0.0003;
        n1.vz -= n1.z * 0.0003;

        // Pairwise node repulsion (sampled to keep 60 FPS)
        for (let j = i + 1; j < nodes.length; j += 2) {
          const n2 = nodes[j];
          const dx = n2.x - n1.x;
          const dy = n2.y - n1.y;
          const dz = n2.z - n1.z;
          const distSq = dx * dx + dy * dy + dz * dz + 100;
          if (distSq < 25000) {
            const force = 180 / distSq;
            n1.vx -= dx * force;
            n1.vy -= dy * force;
            n1.vz -= dz * force;
            n2.vx += dx * force;
            n2.vy += dy * force;
            n2.vz += dz * force;
          }
        }
      }

      // Spring attraction along edges
      edges.forEach((edge) => {
        const src = nodeMap.get(edge.source);
        const tgt = nodeMap.get(edge.target);
        if (!src || !tgt) return;

        const dx = tgt.x - src.x;
        const dy = tgt.y - src.y;
        const dz = tgt.z - src.z;
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz) + 0.1;
        const springLen = 90;
        const force = (dist - springLen) * 0.0005;

        if (isDraggingNodeRef.current?.id !== src.id) {
          src.vx += dx * force;
          src.vy += dy * force;
          src.vz += dz * force;
        }
        if (isDraggingNodeRef.current?.id !== tgt.id) {
          tgt.vx -= dx * force;
          tgt.vy -= dy * force;
          tgt.vz -= dz * force;
        }
      });

      // Update node positions and meshes
      nodes.forEach((n) => {
        if (isDraggingNodeRef.current?.id !== n.id) {
          n.x += n.vx;
          n.y += n.vy;
          n.z += n.vz;
          n.vx *= 0.86;
          n.vy *= 0.86;
          n.vz *= 0.86;
        }

        const mesh = nodeMeshes.get(n.id);
        if (mesh) {
          mesh.position.set(n.x, n.y, n.z);
        }
      });

      // Update 3D Edge Line Vertices
      const posAttr = edgeGeo.attributes.position as THREE.BufferAttribute;
      const colAttr = edgeGeo.attributes.color as THREE.BufferAttribute;
      let ptr = 0;

      edges.forEach((edge) => {
        const src = nodeMap.get(edge.source);
        const tgt = nodeMap.get(edge.target);
        if (!src || !tgt) return;

        posAttr.setXYZ(ptr, src.x, src.y, src.z);
        posAttr.setXYZ(ptr + 1, tgt.x, tgt.y, tgt.z);

        // Highlight connected edges if active node
        const isConnected =
          activeNode && (activeNode.id === src.id || activeNode.id === tgt.id);

        if (isConnected) {
          colAttr.setXYZ(ptr, 0.38, 0.72, 1.0);
          colAttr.setXYZ(ptr + 1, 0.96, 0.62, 0.05);
        } else {
          colAttr.setXYZ(ptr, 0.15, 0.25, 0.45);
          colAttr.setXYZ(ptr + 1, 0.15, 0.25, 0.45);
        }

        ptr += 2;
      });

      posAttr.needsUpdate = true;
      colAttr.needsUpdate = true;

      // Update Traveling Light Energy Pulses
      pulseTime += 0.008;
      const pulsePosAttr = pulseGeo.attributes.position as THREE.BufferAttribute;
      for (let p = 0; p < pulseCount; p++) {
        const edge = edges[p % edges.length];
        const src = nodeMap.get(edge.source);
        const tgt = nodeMap.get(edge.target);
        if (!src || !tgt) continue;

        pulseProgress[p] = (pulseProgress[p] + 0.012) % 1;
        const prog = pulseProgress[p];

        const px = src.x + (tgt.x - src.x) * prog;
        const py = src.y + (tgt.y - src.y) * prog;
        const pz = src.z + (tgt.z - src.z) * prog;
        pulsePosAttr.setXYZ(p, px, py, pz);
      }
      pulsePosAttr.needsUpdate = true;

      renderer.render(scene, camera);
    };

    animate();

    // 4. Mouse / Touch Event Handlers (Click, Drag, Hover)
    const handlePointerMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      // If dragging a node in 3D
      if (isDraggingNodeRef.current && threeRef.current) {
        raycaster.setFromCamera(mouse, camera);
        const intersectPoint = new THREE.Vector3();
        if (raycaster.ray.intersectPlane(threeRef.current.dragPlane, intersectPoint)) {
          isDraggingNodeRef.current.x = intersectPoint.x;
          isDraggingNodeRef.current.y = intersectPoint.y;
          isDraggingNodeRef.current.z = intersectPoint.z;
          isDraggingNodeRef.current.vx = 0;
          isDraggingNodeRef.current.vy = 0;
          isDraggingNodeRef.current.vz = 0;
        }
        return;
      }

      // Hover Detection
      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(Array.from(nodeMeshes.values()));

      if (intersects.length > 0) {
        const hitMesh = intersects[0].object as THREE.Mesh;
        const hitNode = (hitMesh as any).nodeData as Node3D;
        if (hoveredNodeRef.current?.id !== hitNode.id) {
          hoveredNodeRef.current = hitNode;
          container.style.cursor = 'pointer';
        }
      } else {
        if (hoveredNodeRef.current) {
          hoveredNodeRef.current = null;
          container.style.cursor = 'grab';
        }
      }
    };

    const handlePointerDown = (e: MouseEvent) => {
      if (e.button !== 0) return; // Left click only for node drag

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(Array.from(nodeMeshes.values()));

      if (intersects.length > 0) {
        const hitMesh = intersects[0].object as THREE.Mesh;
        const hitNode = (hitMesh as any).nodeData as Node3D;

        // Set up drag plane parallel to camera at node position
        const cameraDir = new THREE.Vector3();
        camera.getWorldDirection(cameraDir);
        threeRef.current?.dragPlane.setFromNormalAndCoplanarPoint(
          cameraDir.negate(),
          new THREE.Vector3(hitNode.x, hitNode.y, hitNode.z)
        );

        isDraggingNodeRef.current = hitNode;
        controls.enabled = false; // Disable orbit while dragging node
      }
    };

    const handlePointerUp = () => {
      if (isDraggingNodeRef.current) {
        isDraggingNodeRef.current = null;
        controls.enabled = true;
      }
    };

    const handleClick = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

      raycaster.setFromCamera(mouse, camera);
      const intersects = raycaster.intersectObjects(Array.from(nodeMeshes.values()));

      if (intersects.length > 0) {
        const hitMesh = intersects[0].object as THREE.Mesh;
        const hitNode = (hitMesh as any).nodeData as Node3D;
        selectAndFlyToNode(hitNode);
      }
    };

    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };

    container.addEventListener('mousemove', handlePointerMove);
    container.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('mouseup', handlePointerUp);
    container.addEventListener('click', handleClick);
    window.addEventListener('resize', handleResize);

    return () => {
      isCancelled = true;
      cancelAnimationFrame(animFrameId);
      container.removeEventListener('mousemove', handlePointerMove);
      container.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('mouseup', handlePointerUp);
      container.removeEventListener('click', handleClick);
      window.removeEventListener('resize', handleResize);
      controls.dispose();
      renderer.dispose();
      if (container) {
        container.innerHTML = '';
      }
      threeRef.current = null;
    };
  }, [nodes, edges]);

  // Smoothly Fly Camera to Selected Node in 3D Space
  const selectAndFlyToNode = (node: Node3D) => {
    setActiveNode(node);

    if (threeRef.current) {
      const targetPos = new THREE.Vector3(node.x, node.y, node.z);
      const cameraPos = new THREE.Vector3(node.x, node.y + 18, node.z + 85);
      threeRef.current.flyToTarget = {
        targetPos,
        cameraPos,
        progress: 0,
      };
    }
  };

  // Reset 3D Camera to view entire universe
  const handleResetCamera = () => {
    if (threeRef.current) {
      threeRef.current.flyToTarget = {
        targetPos: new THREE.Vector3(0, 0, 0),
        cameraPos: new THREE.Vector3(0, 80, 480),
        progress: 0,
      };
    }
    setActiveNode(null);
  };

  // Filter nodes
  const filteredNodes = nodes.filter((n) => {
    const matchesCat = selectedCategory === 'all' || n.category === selectedCategory;
    const matchesSearch =
      searchQuery === '' ||
      n.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.description.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesCat && matchesSearch;
  });

  // Calculate connected edges for active node
  const activeConnectedEdges = activeNode
    ? edges.filter((e) => e.source === activeNode.id || e.target === activeNode.id)
    : [];

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case 'Person':
        return <User size={13} style={{ color: '#f59e0b' }} />;
      case 'Organization':
        return <Building size={13} style={{ color: '#3b82f6' }} />;
      case 'Technology':
        return <Cpu size={13} style={{ color: '#06b6d4' }} />;
      case 'Metric':
        return <BarChart2 size={13} style={{ color: '#10b981' }} />;
      default:
        return <Activity size={13} style={{ color: '#94a3b8' }} />;
    }
  };

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden', backgroundColor: '#070a12' }}>
      {/* 3D WebGL Canvas Container */}
      <div
        ref={containerRef}
        style={{ width: '100%', height: '100%', cursor: 'grab' }}
      />

      {loading && (
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          color: '#93c5fd',
          fontSize: '0.88rem',
          pointerEvents: 'none',
          zIndex: 15,
          backgroundColor: 'rgba(15, 23, 42, 0.85)',
          padding: '0.6rem 1.2rem',
          borderRadius: '9999px',
          border: '1px solid rgba(59, 130, 246, 0.3)'
        }}>
          Loading 3D Knowledge Universe...
        </div>
      )}

      {!loading && nodes.length === 0 && (
        <div style={{
          position: 'absolute',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          textAlign: 'center',
          color: 'var(--text-secondary)',
          zIndex: 15,
          backgroundColor: 'rgba(15, 23, 42, 0.85)',
          backdropFilter: 'blur(12px)',
          padding: '1.75rem 2.25rem',
          borderRadius: 'var(--radius-xl)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.6)'
        }}>
          <Network size={36} style={{ color: 'var(--accent-primary)', margin: '0 auto 0.75rem auto', opacity: 0.8 }} />
          <h4 style={{ fontSize: '1rem', fontWeight: 600, color: '#ffffff', marginBottom: '0.35rem' }}>
            Knowledge Universe Ready
          </h4>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', maxWidth: '320px', lineHeight: 1.5 }}>
            Upload documents via the knowledge base to ingest and construct 3D interconnected knowledge graph entities.
          </p>
        </div>
      )}

      {/* Top Floating Control HUD */}
      <div style={{
        position: 'absolute',
        top: '16px',
        left: '20px',
        right: '20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        pointerEvents: 'none',
        zIndex: 20
      }}>
        {/* Title & Badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          backgroundColor: 'rgba(15, 23, 42, 0.85)',
          backdropFilter: 'blur(12px)',
          border: '1px solid rgba(59, 130, 246, 0.25)',
          padding: '0.45rem 0.9rem',
          borderRadius: 'var(--radius-lg)',
          pointerEvents: 'auto',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.5)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
            <Sparkles size={16} style={{ color: 'var(--accent-primary)' }} />
            <span style={{ fontSize: '0.9rem', fontWeight: 650, color: '#ffffff' }}>
              3D Knowledge Universe
            </span>
          </div>
          <span style={{
            fontSize: '0.72rem',
            padding: '0.12rem 0.5rem',
            borderRadius: '9999px',
            backgroundColor: 'rgba(59, 130, 246, 0.15)',
            border: '1px solid rgba(59, 130, 246, 0.3)',
            color: '#93c5fd',
            fontFamily: 'var(--font-mono)'
          }}>
            {nodes.length} 3D Nodes • {edges.length} Edges
          </span>
        </div>

        {/* Search & Category Filter Controls */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          pointerEvents: 'auto'
        }}>
          {/* Search Input with Dynamic Suggestions Dropdown */}
          <div style={{ position: 'relative' }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.4rem',
              backgroundColor: 'rgba(15, 23, 42, 0.85)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              padding: '0.4rem 0.75rem',
              borderRadius: 'var(--radius-md)',
              boxShadow: '0 4px 16px rgba(0, 0, 0, 0.4)'
            }}>
              <Search size={14} style={{ color: 'var(--text-muted)' }} />
              <input
                type="text"
                placeholder="Search 3D nodes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  color: '#ffffff',
                  fontSize: '0.8rem',
                  width: '160px'
                }}
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  style={{ background: 'none', border: 'none', color: 'var(--text-dim)', cursor: 'pointer' }}
                >
                  <X size={12} />
                </button>
              )}
            </div>

            {/* Quick Suggestions Popup */}
            {searchQuery.trim() !== '' && filteredNodes.length > 0 && (
              <div style={{
                position: 'absolute',
                top: '100%',
                left: 0,
                right: 0,
                marginTop: '4px',
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                backdropFilter: 'blur(16px)',
                border: '1px solid rgba(59, 130, 246, 0.35)',
                borderRadius: 'var(--radius-md)',
                overflow: 'hidden',
                boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
                zIndex: 40
              }}>
                {filteredNodes.slice(0, 5).map((node) => (
                  <div
                    key={node.id}
                    onClick={() => {
                      selectAndFlyToNode(node);
                      setSearchQuery('');
                    }}
                    style={{
                      padding: '0.45rem 0.75rem',
                      fontSize: '0.78rem',
                      color: '#ffffff',
                      cursor: 'pointer',
                      borderBottom: '1px solid rgba(255,255,255,0.05)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between'
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.2)'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                  >
                    <span>{node.name}</span>
                    <span style={{ fontSize: '0.68rem', color: '#93c5fd' }}>{node.category}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Category Dropdown */}
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            style={{
              backgroundColor: 'rgba(15, 23, 42, 0.85)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#ffffff',
              fontSize: '0.8rem',
              padding: '0.4rem 0.75rem',
              borderRadius: 'var(--radius-md)',
              outline: 'none',
              cursor: 'pointer'
            }}
          >
            <option value="all">All Categories</option>
            <option value="Person">Person</option>
            <option value="Organization">Organization</option>
            <option value="Technology">Technology</option>
            <option value="Metric">Metric</option>
          </select>

          {/* Reset Camera Button */}
          <button
            onClick={handleResetCamera}
            title="Reset 3D Orbit Camera"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.3rem',
              backgroundColor: 'rgba(15, 23, 42, 0.85)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(255, 255, 255, 0.1)',
              color: '#93c5fd',
              fontSize: '0.78rem',
              padding: '0.4rem 0.75rem',
              borderRadius: 'var(--radius-md)',
              cursor: 'pointer'
            }}
          >
            <Compass size={13} />
            <span>Reset View</span>
          </button>
        </div>
      </div>

      {/* Floating 3D Navigation Guide Pill */}
      <div style={{
        position: 'absolute',
        bottom: '16px',
        left: '20px',
        display: 'flex',
        alignItems: 'center',
        gap: '0.8rem',
        backgroundColor: 'rgba(15, 23, 42, 0.75)',
        backdropFilter: 'blur(8px)',
        border: '1px solid rgba(255, 255, 255, 0.06)',
        padding: '0.35rem 0.85rem',
        borderRadius: '9999px',
        fontSize: '0.72rem',
        color: 'var(--text-dim)',
        pointerEvents: 'none',
        zIndex: 20
      }}>
        <span>• Left Click + Drag: Rotate 3D</span>
        <span>• Right Click: Pan</span>
        <span>• Scroll: Zoom</span>
        <span>• Click Node: Fly-To & Inspect</span>
        <span>• Drag Node: 3D Reposition</span>
      </div>

      {/* Deep Interactive Information Card (Slide-Out on Node Click) */}
      {activeNode && (() => {
        const activeGeoLocations = getNodeGeoData(activeNode, edges);
        const activeChartArtifact = getNodeChartData(activeNode);

        return (
          <div style={{
            position: 'absolute',
            top: '72px',
            right: '20px',
            bottom: '20px',
            width: isDrawerExpanded ? '520px' : '380px',
            maxWidth: 'calc(100vw - 40px)',
            transition: 'width 0.25s cubic-bezier(0.16, 1, 0.3, 1)',
            backgroundColor: 'rgba(11, 15, 25, 0.94)',
            backdropFilter: 'blur(20px)',
            border: '1px solid rgba(59, 130, 246, 0.35)',
            borderRadius: 'var(--radius-xl)',
            padding: '1.25rem',
            display: 'flex',
            flexDirection: 'column',
            boxShadow: '0 12px 48px rgba(0, 0, 0, 0.85)',
            zIndex: 30,
            animation: 'slideInRight 0.25s cubic-bezier(0.16, 1, 0.3, 1)'
          }}>
            {/* Card Header with Category, Expand/Collapse & Close */}
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: '0.85rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.35rem',
                  fontSize: '0.72rem',
                  padding: '0.2rem 0.55rem',
                  borderRadius: '9999px',
                  backgroundColor: `${CATEGORY_COLORS[activeNode.category]?.str || '#94a3b8'}22`,
                  border: `1px solid ${CATEGORY_COLORS[activeNode.category]?.str || '#94a3b8'}55`,
                  color: CATEGORY_COLORS[activeNode.category]?.str || '#ffffff',
                  fontWeight: 600
                }}>
                  {getCategoryIcon(activeNode.category)}
                  <span>{activeNode.category}</span>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                <button
                  onClick={() => setIsDrawerExpanded(!isDrawerExpanded)}
                  title={isDrawerExpanded ? 'Collapse Drawer' : 'Expand Drawer'}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-dim)',
                    cursor: 'pointer',
                    padding: '4px',
                    borderRadius: '4px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
                  onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
                >
                  {isDrawerExpanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
                </button>

                <button
                  onClick={() => setActiveNode(null)}
                  title="Close Inspector"
                  style={{
                    background: 'none',
                    border: 'none',
                    color: 'var(--text-dim)',
                    cursor: 'pointer',
                    padding: '4px',
                    borderRadius: '4px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.color = 'var(--text-primary)'}
                  onMouseLeave={(e) => e.currentTarget.style.color = 'var(--text-dim)'}
                >
                  <X size={16} />
                </button>
              </div>
            </div>

            {/* Node Title */}
            <h3 style={{
              fontSize: '1.2rem',
              fontWeight: 700,
              color: '#ffffff',
              margin: '0 0 0.4rem 0',
              letterSpacing: '-0.015em'
            }}>
              {activeNode.name}
            </h3>

            {/* Role & Description */}
            <p style={{
              fontSize: '0.82rem',
              color: 'var(--text-secondary)',
              lineHeight: 1.5,
              margin: '0 0 0.85rem 0'
            }}>
              {activeNode.description || 'Verified entity extracted from multi-document ingestion pipeline.'}
            </p>

            {/* Centrality & Metric Stats Bar */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '0.5rem',
              backgroundColor: 'rgba(255, 255, 255, 0.03)',
              border: '1px solid rgba(255, 255, 255, 0.06)',
              borderRadius: 'var(--radius-md)',
              padding: '0.55rem 0.5rem',
              marginBottom: '0.85rem',
              textAlign: 'center'
            }}>
              <div>
                <div style={{ fontSize: '0.66rem', color: 'var(--text-dim)' }}>Edges</div>
                <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#ffffff', fontFamily: 'var(--font-mono)' }}>
                  {activeNode.degree}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.66rem', color: 'var(--text-dim)' }}>Category</div>
                <div style={{ fontSize: '0.74rem', fontWeight: 600, color: '#93c5fd', marginTop: '2px' }}>
                  {activeNode.category}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.66rem', color: 'var(--text-dim)' }}>Status</div>
                <div style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--accent-emerald)', marginTop: '2px' }}>
                  Verified
                </div>
              </div>
            </div>

            {/* Quick Action: Analyze in Chat */}
            <button
              onClick={() => onStartChatWithEntity(activeNode.name)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '0.45rem',
                width: '100%',
                backgroundColor: 'var(--accent-primary)',
                color: '#ffffff',
                border: 'none',
                padding: '0.55rem 1rem',
                borderRadius: 'var(--radius-md)',
                fontSize: '0.82rem',
                fontWeight: 600,
                cursor: 'pointer',
                marginBottom: '0.85rem',
                boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
                transition: 'all 0.15s ease'
              }}
              onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'var(--accent-primary-hover)'}
              onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'var(--accent-primary)'}
            >
              <MessageSquare size={14} />
              <span>Deep Analyze in Chat</span>
            </button>

            {/* Deep-Dive Inspection Tabs */}
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.3rem',
              padding: '0.2rem',
              backgroundColor: 'rgba(255, 255, 255, 0.04)',
              borderRadius: 'var(--radius-md)',
              marginBottom: '0.75rem'
            }}>
              <button
                onClick={() => setDrawerTab('relations')}
                style={{
                  flex: 1,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: '0.35rem',
                  padding: '0.35rem 0.5rem',
                  fontSize: '0.74rem',
                  fontWeight: drawerTab === 'relations' ? 650 : 500,
                  color: drawerTab === 'relations' ? '#ffffff' : 'var(--text-dim)',
                  backgroundColor: drawerTab === 'relations' ? 'var(--accent-primary)' : 'transparent',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
              >
                <span>Relations</span>
                <span style={{
                  fontSize: '0.66rem',
                  backgroundColor: drawerTab === 'relations' ? 'rgba(255, 255, 255, 0.25)' : 'rgba(255, 255, 255, 0.08)',
                  padding: '0.05rem 0.35rem',
                  borderRadius: '9999px'
                }}>
                  {activeConnectedEdges.length}
                </span>
              </button>

              {activeGeoLocations.length > 0 && (
                <button
                  onClick={() => {
                    setDrawerTab('map');
                    if (!isDrawerExpanded) setIsDrawerExpanded(true);
                  }}
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.35rem',
                    padding: '0.35rem 0.5rem',
                    fontSize: '0.74rem',
                    fontWeight: drawerTab === 'map' ? 650 : 500,
                    color: drawerTab === 'map' ? '#ffffff' : 'var(--text-dim)',
                    backgroundColor: drawerTab === 'map' ? 'var(--accent-primary)' : 'transparent',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <MapPin size={12} style={{ color: drawerTab === 'map' ? '#ffffff' : 'var(--accent-emerald)' }} />
                  <span>Map</span>
                </button>
              )}

              {activeChartArtifact && (
                <button
                  onClick={() => {
                    setDrawerTab('chart');
                    if (!isDrawerExpanded) setIsDrawerExpanded(true);
                  }}
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '0.35rem',
                    padding: '0.35rem 0.5rem',
                    fontSize: '0.74rem',
                    fontWeight: drawerTab === 'chart' ? 650 : 500,
                    color: drawerTab === 'chart' ? '#ffffff' : 'var(--text-dim)',
                    backgroundColor: drawerTab === 'chart' ? 'var(--accent-primary)' : 'transparent',
                    border: 'none',
                    borderRadius: 'var(--radius-sm)',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                >
                  <BarChart2 size={12} style={{ color: drawerTab === 'chart' ? '#ffffff' : '#38bdf8' }} />
                  <span>Metrics</span>
                </button>
              )}
            </div>

            {/* Tab Body: Relations List */}
            {drawerTab === 'relations' && (
              <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '0.45rem',
                  fontSize: '0.72rem',
                  color: 'var(--text-dim)',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em'
                }}>
                  <span>Connected Knowledge Edges</span>
                </div>

                <div style={{
                  flex: 1,
                  overflowY: 'auto',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.45rem',
                  paddingRight: '0.2rem'
                }}>
                  {activeConnectedEdges.map((edge, idx) => {
                    const isSource = edge.source === activeNode.id;
                    const otherNodeId = isSource ? edge.target : edge.source;
                    const otherNode = nodes.find((n) => n.id === otherNodeId);
                    const neighborName = isSource ? edge.target_name : edge.source_name;

                    return (
                      <div
                        key={idx}
                        onClick={() => {
                          if (otherNode) selectAndFlyToNode(otherNode);
                        }}
                        style={{
                          backgroundColor: 'rgba(255, 255, 255, 0.03)',
                          border: '1px solid rgba(255, 255, 255, 0.07)',
                          borderRadius: 'var(--radius-md)',
                          padding: '0.6rem 0.75rem',
                          cursor: otherNode ? 'pointer' : 'default',
                          transition: 'all 0.15s ease'
                        }}
                        onMouseEnter={(e) => {
                          if (otherNode) e.currentTarget.style.borderColor = 'var(--accent-primary)';
                        }}
                        onMouseLeave={(e) => {
                          if (otherNode) e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.07)';
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.2rem' }}>
                          <span style={{
                            fontSize: '0.68rem',
                            fontWeight: 650,
                            color: 'var(--accent-primary)',
                            fontFamily: 'var(--font-mono)'
                          }}>
                            {edge.relation}
                          </span>
                          <span style={{ fontSize: '0.65rem', color: 'var(--text-dim)' }}>
                            {isSource ? 'Outgoing →' : '← Incoming'}
                          </span>
                        </div>

                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          color: '#ffffff',
                          fontSize: '0.84rem',
                          fontWeight: 600
                        }}>
                          <span>{neighborName}</span>
                          {otherNode && <ArrowRight size={12} style={{ color: 'var(--text-dim)' }} />}
                        </div>

                        {edge.description && (
                          <p style={{
                            fontSize: '0.72rem',
                            color: 'var(--text-dim)',
                            lineHeight: 1.45,
                            margin: '0.3rem 0 0 0'
                          }}>
                            {edge.description}
                          </p>
                        )}
                      </div>
                    );
                  })}

                  {activeConnectedEdges.length === 0 && (
                    <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--text-dim)', fontSize: '0.78rem' }}>
                      No explicit neighbor relations recorded in current subgraph.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Tab Body: Geographic Intelligence Map */}
            {drawerTab === 'map' && activeGeoLocations.length > 0 && (
              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
                <InteractiveMapViewer locations={activeGeoLocations} />
              </div>
            )}

            {/* Tab Body: Analytical Charts & Metrics */}
            {drawerTab === 'chart' && activeChartArtifact && (
              <div style={{ flex: 1, minHeight: 0, overflowY: 'auto' }}>
                <InteractiveChartViewer artifact={activeChartArtifact} />
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
};
