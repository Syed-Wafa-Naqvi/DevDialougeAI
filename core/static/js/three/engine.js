/**
 * DevDialogue AI — Three.js Architecture & Nebula Engine (v4 Studio Light §7.2)
 * Clean, bright diagram-like 3D architecture graph and subtle ambient nebula
 * with crisp nodes, thin lines, restrained depth, and low resource overhead.
 */

import { qualityManager } from '../motion/quality.js';

export class ThreeEngine {
    constructor(canvasElement) {
        if (!canvasElement || typeof THREE === 'undefined') return;
        this.canvas = canvasElement;
        this.tier = qualityManager.getTier();

        if (this.tier === 'Lite' || this.tier === 'Reduced') return;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(50, canvasElement.clientWidth / (canvasElement.clientHeight || 1), 0.1, 1000);
        this.renderer = new THREE.WebGLRenderer({
            canvas: canvasElement,
            alpha: true,
            antialias: true,
            powerPreference: 'high-performance'
        });

        // Cap pixel ratio at 1.5 to protect battery and GPU fillrate
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
        this.renderer.setPixelRatio(pixelRatio);
        this.renderer.setSize(canvasElement.clientWidth, canvasElement.clientHeight || 400);

        this.disposed = false;
        this.paused = false;
        this.animId = null;

        // Visibility Change Listener — pause loop when tab is backgrounded
        this.handleVisibility = () => {
            this.paused = document.hidden;
        };
        document.addEventListener('visibilitychange', this.handleVisibility);

        this.initResizeObserver();
    }

    initResizeObserver() {
        this.resizeObserver = new ResizeObserver((entries) => {
            for (let entry of entries) {
                if (entry.contentBoxSize) {
                    const width = entry.contentRect.width;
                    const height = entry.contentRect.height;
                    if (width > 0 && height > 0 && this.camera && this.renderer) {
                        this.camera.aspect = width / height;
                        this.camera.updateProjectionMatrix();
                        this.renderer.setSize(width, height);
                    }
                }
            }
        });
        this.resizeObserver.observe(this.canvas.parentElement || this.canvas);
    }

    dispose() {
        this.disposed = true;
        if (this.animId) cancelAnimationFrame(this.animId);
        document.removeEventListener('visibilitychange', this.handleVisibility);
        if (this.resizeObserver) this.resizeObserver.disconnect();
        if (this.renderer) {
            this.renderer.dispose();
            this.renderer.forceContextLoss();
        }
    }
}

/**
 * 7.2 Diagrammatic 3D Architecture Graph Scene (Studio Light Style)
 * Crisp white node cards with colored folder stripes and thin border connection lines.
 */
export class ArchitectureGraphScene extends ThreeEngine {
    constructor(canvas) {
        super(canvas);
        if (!this.renderer) return;

        this.camera.position.z = 35;
        this.mouseX = 0;
        this.mouseY = 0;

        this.buildDiagramGraph();
        this.bindEvents();
        this.animate();
    }

    buildDiagramGraph() {
        this.graphGroup = new THREE.Group();

        // 1. Create Nodes (Rounded White Boxes with Cobalt Active Node)
        const nodePositions = [
            { x: -12, y: 6, z: 0, label: "Core API", type: "module" },
            { x: -12, y: -6, z: 0, label: "Auth Service", type: "module" },
            { x: 0, y: 8, z: 2, label: "User Views", type: "file" },
            { x: 0, y: 0, z: 0, label: "Dialogue Engine", type: "core", active: true },
            { x: 0, y: -8, z: -2, label: "DB Models", type: "file" },
            { x: 12, y: 5, z: 0, label: "Code Synthesizer", type: "module" },
            { x: 12, y: -5, z: 0, label: "Verification Test", type: "module" },
        ];

        const cardGeo = new THREE.BoxGeometry(4.5, 2.2, 0.3);

        this.nodes = [];
        nodePositions.forEach((pos) => {
            const mat = new THREE.MeshBasicMaterial({
                color: pos.active ? 0x2548E8 : 0xFFFFFF
            });
            const mesh = new THREE.Mesh(cardGeo, mat);
            mesh.position.set(pos.x, pos.y, pos.z);
            this.graphGroup.add(mesh);
            this.nodes.push(mesh.position);
        });

        // 2. Crisp Connection Lines (Clean Border Color)
        const lineMat = new THREE.LineBasicMaterial({
            color: 0xC9CED6,
            linewidth: 1
        });

        const activeLineMat = new THREE.LineBasicMaterial({
            color: 0x2548E8,
            linewidth: 2
        });

        const connections = [
            [0, 2], [0, 3], [1, 3], [1, 4], [3, 5], [3, 6], [5, 6]
        ];

        connections.forEach(([fromIdx, toIdx]) => {
            const p1 = this.nodes[fromIdx];
            const p2 = this.nodes[toIdx];
            const lineGeo = new THREE.BufferGeometry().setFromPoints([p1, p2]);
            const isSelectedPath = (fromIdx === 3 || toIdx === 3);
            const line = new THREE.Line(lineGeo, isSelectedPath ? activeLineMat : lineMat);
            this.graphGroup.add(line);
        });

        this.scene.add(this.graphGroup);
    }

    bindEvents() {
        this.onMouseMove = (e) => {
            this.mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
            this.mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
        };
        window.addEventListener('mousemove', this.onMouseMove);
    }

    dispose() {
        if (this.onMouseMove) window.removeEventListener('mousemove', this.onMouseMove);
        super.dispose();
    }

    animate() {
        if (this.disposed) return;
        this.animId = requestAnimationFrame(() => this.animate());
        if (this.paused) return;

        if (this.graphGroup) {
            this.camera.position.x += (this.mouseX * 3 - this.camera.position.x) * 0.05;
            this.camera.position.y += (-this.mouseY * 3 - this.camera.position.y) * 0.05;
            this.camera.lookAt(this.scene.position);
        }

        this.renderer.render(this.scene, this.camera);
    }
}

/**
 * LandingNebulaScene — Ambient 3D Hero Constellation & Architecture Graph
 * Blends interactive node graph with soft dialogue particle nebula.
 * Smooth mouse parallax, ultra-low GPU draw call overhead, battery friendly.
 */
export class LandingNebulaScene extends ThreeEngine {
    constructor(canvas) {
        super(canvas);
        if (!this.renderer) return;

        this.camera.position.z = 40;
        this.mouseX = 0;
        this.mouseY = 0;
        this.targetMouseX = 0;
        this.targetMouseY = 0;

        const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        this.reducedMotion = prefersReducedMotion || this.tier === 'Reduced';

        this.buildScene();
        this.bindEvents();

        if (this.reducedMotion) {
            // Render single static frame without continuous requestAnimationFrame loop
            this.renderer.render(this.scene, this.camera);
        } else {
            this.animate();
        }
    }

    buildScene() {
        this.masterGroup = new THREE.Group();

        // 1. Particle Constellation (Dialogue / Token Stream)
        const particleCount = this.tier === 'High' ? 140 : 80;
        const particleGeo = new THREE.BufferGeometry();
        const positions = new Float32Array(particleCount * 3);
        const scales = new Float32Array(particleCount);

        for (let i = 0; i < particleCount; i++) {
            positions[i * 3] = (Math.random() - 0.5) * 60;
            positions[i * 3 + 1] = (Math.random() - 0.5) * 40;
            positions[i * 3 + 2] = (Math.random() - 0.5) * 30;
            scales[i] = Math.random() * 2 + 1;
        }

        particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));

        const particleMat = new THREE.PointsMaterial({
            color: 0x2548E8,
            size: 1.2,
            transparent: true,
            opacity: 0.45,
            blending: THREE.NormalBlending
        });

        this.particles = new THREE.Points(particleGeo, particleMat);
        this.masterGroup.add(this.particles);

        // 2. Core Architecture Blueprint Nodes
        const nodesData = [
            { x: -14, y: 7, z: -2, color: 0x2548E8, size: 2.2, label: "Discover" },
            { x: -7, y: -4, z: 2, color: 0x4F46E5, size: 2.6, label: "Blueprint" },
            { x: 0, y: 5, z: 4, color: 0x2548E8, size: 3.2, label: "Synthesizer" },
            { x: 8, y: -5, z: 1, color: 0x06B6D4, size: 2.6, label: "Verify" },
            { x: 15, y: 6, z: -1, color: 0x10B981, size: 2.4, label: "Export" }
        ];

        this.nodeMeshes = [];
        const boxGeo = new THREE.BoxGeometry(4.0, 2.0, 0.4);
        const ringGeo = new THREE.RingGeometry(2.4, 2.6, 24);

        nodesData.forEach((node) => {
            const nodeGroup = new THREE.Group();
            nodeGroup.position.set(node.x, node.y, node.z);

            const mat = new THREE.MeshBasicMaterial({
                color: node.color,
                transparent: true,
                opacity: 0.85
            });
            const box = new THREE.Mesh(boxGeo, mat);
            nodeGroup.add(box);

            const ringMat = new THREE.MeshBasicMaterial({
                color: node.color,
                side: THREE.DoubleSide,
                transparent: true,
                opacity: 0.35
            });
            const ring = new THREE.Mesh(ringGeo, ringMat);
            ring.position.z = 0.3;
            nodeGroup.add(ring);

            this.masterGroup.add(nodeGroup);
            this.nodeMeshes.push(nodeGroup);
        });

        // 3. Connective Pipeline Lines
        const linePoints = this.nodeMeshes.map(m => m.position);
        const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints);
        const lineMat = new THREE.LineBasicMaterial({
            color: 0x2548E8,
            transparent: true,
            opacity: 0.35,
            linewidth: 1
        });
        const lineMesh = new THREE.Line(lineGeo, lineMat);
        this.masterGroup.add(lineMesh);

        this.scene.add(this.masterGroup);
    }

    bindEvents() {
        this.onMouseMove = (e) => {
            this.targetMouseX = (e.clientX / window.innerWidth - 0.5) * 2;
            this.targetMouseY = (e.clientY / window.innerHeight - 0.5) * 2;
        };
        window.addEventListener('mousemove', this.onMouseMove);
    }

    dispose() {
        if (this.onMouseMove) window.removeEventListener('mousemove', this.onMouseMove);
        super.dispose();
    }

    animate() {
        if (this.disposed) return;
        this.animId = requestAnimationFrame(() => this.animate());
        if (this.paused) return;

        // Smooth camera and group parallax with easing
        this.mouseX += (this.targetMouseX - this.mouseX) * 0.04;
        this.mouseY += (this.targetMouseY - this.mouseY) * 0.04;

        if (this.masterGroup) {
            this.masterGroup.rotation.y = this.mouseX * 0.12;
            this.masterGroup.rotation.x = -this.mouseY * 0.08;
        }

        if (this.particles) {
            this.particles.rotation.y += 0.0006;
            this.particles.rotation.x += 0.0003;
        }

        this.renderer.render(this.scene, this.camera);
    }
}
