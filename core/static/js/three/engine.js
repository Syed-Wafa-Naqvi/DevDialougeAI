/**
 * DevDialogue AI — Three.js Architecture & Nebula Engine (v4 Studio Light §7.2)
 * Clean, bright diagram-like 3D architecture graph and subtle ambient nebula
 * with soft glowing points, thin lines, restrained depth, and low resource overhead.
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
        this.renderer.setSize(canvasElement.clientWidth, canvasElement.clientHeight || 400, false);

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
                        this.renderer.setSize(width, height, false);
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

function createGlowingPointTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 30);
    grad.addColorStop(0, 'rgba(255, 255, 255, 1)');
    grad.addColorStop(0.25, 'rgba(96, 165, 250, 0.85)');
    grad.addColorStop(0.6, 'rgba(37, 72, 232, 0.35)');
    grad.addColorStop(1, 'rgba(37, 72, 232, 0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(32, 32, 30, 0, Math.PI * 2);
    ctx.fill();
    const texture = new THREE.CanvasTexture(canvas);
    return texture;
}

/**
 * LandingNebulaScene — Ambient 3D Hero Soft Constellation Engine
 * Soft glowing points in brand blue, faint connecting lines, dynamic section sizing,
 * subtle camera parallax (max ±0.6 units) only when fine mouse is present.
 * Zero solid boxes or obtrusive elements to maintain pristine text readability.
 */
export class LandingNebulaScene extends ThreeEngine {
    constructor(canvas) {
        super(canvas);
        if (!this.renderer) return;

        this.camera.position.set(0, 0, 38);
        this.camBaseZ = 38;
        this.targetCamX = 0;
        this.targetCamY = 0;

        const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        this.reducedMotion = prefersReducedMotion || this.tier === 'Reduced';
        this.hasMouse = window.matchMedia && window.matchMedia('(any-hover: hover) and (any-pointer: fine)').matches;

        // Mobile coarse pointer detection (Item 6): reduce particles & skip connecting lines
        const isMobileCoarse = window.matchMedia &&
            window.matchMedia('(any-pointer: coarse)').matches &&
            !window.matchMedia('(any-pointer: fine)').matches;
        this.isMobileCoarse = isMobileCoarse;

        // Size dynamically from the enclosing hero section
        this.heroSection = this.canvas.closest('.hero-section') || this.canvas.parentElement || this.canvas;
        this.initSectionResizeObserver();

        this.buildScene();
        this.bindEvents();

        if (this.reducedMotion) {
            this.renderer.render(this.scene, this.camera);
        } else {
            this.animate();
        }
    }

    initSectionResizeObserver() {
        const updateSize = () => {
            if (!this.heroSection || !this.renderer || !this.camera) return;
            const w = this.heroSection.clientWidth;
            const h = this.heroSection.clientHeight || 500;
            if (w > 0 && h > 0) {
                this.camera.aspect = w / h;
                this.camera.updateProjectionMatrix();
                this.renderer.setSize(w, h, false);
            }
        };

        updateSize();

        this.sectionResizeObserver = new ResizeObserver(() => updateSize());
        this.sectionResizeObserver.observe(this.heroSection);
    }

    buildScene() {
        this.masterGroup = new THREE.Group();
        this.pointTexture = createGlowingPointTexture();

        // 1. Soft glowing background particle cloud across full width and height
        // Mobile battery saving: ~60 particles on coarse-only mobile displays
        this.particleCount = this.isMobileCoarse ? 60 : ((this.tier === 'High') ? 220 : 100);
        const particleGeo = new THREE.BufferGeometry();
        const positions = new Float32Array(this.particleCount * 3);
        const colors = new Float32Array(this.particleCount * 3);
        this.basePositions = new Float32Array(this.particleCount * 3);
        this.phases = new Float32Array(this.particleCount);

        const colorBrand = new THREE.Color(0x2548E8);
        const colorSoft = new THREE.Color(0x60A5FA);

        for (let i = 0; i < this.particleCount; i++) {
            let x, y, z;
            let attempts = 0;
            // Widen keep-out zone around headline, paragraph, and buttons (|x| < 30 and y in [-14, 20])
            do {
                x = (Math.random() - 0.5) * 110;
                y = (Math.random() - 0.5) * 44;
                z = (Math.random() - 0.5) * 22;
                attempts++;
            } while (attempts < 100 && (Math.abs(x) < 30 && y > -14 && y < 20));

            positions[i * 3] = x;
            positions[i * 3 + 1] = y;
            positions[i * 3 + 2] = z;

            this.basePositions[i * 3] = x;
            this.basePositions[i * 3 + 1] = y;
            this.basePositions[i * 3 + 2] = z;

            this.phases[i] = Math.random() * Math.PI * 2;

            // Two tones: brand cobalt (#2548E8) and sky blue (#60A5FA)
            const c = (Math.random() > 0.45) ? colorBrand : colorSoft;
            colors[i * 3] = c.r;
            colors[i * 3 + 1] = c.g;
            colors[i * 3 + 2] = c.b;
        }

        particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        particleGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));

        const particleMat = new THREE.PointsMaterial({
            map: this.pointTexture,
            size: 3.8,
            sizeAttenuation: true,
            transparent: true,
            opacity: 0.7,
            vertexColors: true,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });

        this.particles = new THREE.Points(particleGeo, particleMat);
        this.masterGroup.add(this.particles);

        // 2. 12 larger "node" points placed strictly at the left and right perimeters
        const leftNodes = [
            new THREE.Vector3(-46, 12, -2),
            new THREE.Vector3(-36, 4, 3),
            new THREE.Vector3(-44, -7, 1),
            new THREE.Vector3(-32, 14, 0),
            new THREE.Vector3(-33, -3, -1),
            new THREE.Vector3(-35, -12, 2)
        ];

        const rightNodes = [
            new THREE.Vector3(46, 12, -2),
            new THREE.Vector3(36, 4, 3),
            new THREE.Vector3(44, -7, 1),
            new THREE.Vector3(32, 14, 0),
            new THREE.Vector3(33, -3, -1),
            new THREE.Vector3(35, -12, 2)
        ];

        const allNodes = [...leftNodes, ...rightNodes];
        const nodeGeo = new THREE.BufferGeometry().setFromPoints(allNodes);
        const nodeMat = new THREE.PointsMaterial({
            color: 0x60A5FA,
            map: this.pointTexture,
            size: 4.8,
            sizeAttenuation: true,
            transparent: true,
            opacity: 0.8,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });

        this.nodePoints = new THREE.Points(nodeGeo, nodeMat);
        this.masterGroup.add(this.nodePoints);

        // 3. Faint connecting lines strictly within side clusters (skipped on mobile to save battery)
        if (!this.isMobileCoarse) {
            const lineConnections = [
                // Left loose graph
                leftNodes[0], leftNodes[1],
                leftNodes[1], leftNodes[2],
                leftNodes[0], leftNodes[3],
                leftNodes[3], leftNodes[4],
                leftNodes[1], leftNodes[4],
                leftNodes[2], leftNodes[5],
                leftNodes[4], leftNodes[5],

                // Right loose graph
                rightNodes[0], rightNodes[1],
                rightNodes[1], rightNodes[2],
                rightNodes[0], rightNodes[3],
                rightNodes[3], rightNodes[4],
                rightNodes[1], rightNodes[4],
                rightNodes[2], rightNodes[5],
                rightNodes[4], rightNodes[5]
            ];

            const lineGeo = new THREE.BufferGeometry().setFromPoints(lineConnections);
            const lineMat = new THREE.LineBasicMaterial({
                color: 0x60A5FA,
                transparent: true,
                opacity: 0.25,
                blending: THREE.AdditiveBlending,
                linewidth: 1
            });

            this.connectionLines = new THREE.LineSegments(lineGeo, lineMat);
            this.masterGroup.add(this.connectionLines);
        }

        this.scene.add(this.masterGroup);
    }

    bindEvents() {
        this.onMouseMove = (e) => {
            if (!this.hasMouse || this.reducedMotion) return;
            const nx = (e.clientX / window.innerWidth - 0.5) * 2;
            const ny = (e.clientY / window.innerHeight - 0.5) * 2;
            // Camera parallax lerps up to ±1.5 units toward cursor
            this.targetCamX = Math.max(-1.5, Math.min(1.5, nx * 1.5));
            this.targetCamY = Math.max(-1.5, Math.min(1.5, -ny * 1.5));
        };
        window.addEventListener('mousemove', this.onMouseMove);
    }

    dispose() {
        if (this.onMouseMove) window.removeEventListener('mousemove', this.onMouseMove);
        if (this.sectionResizeObserver) this.sectionResizeObserver.disconnect();
        if (this.pointTexture) this.pointTexture.dispose();
        super.dispose();
    }

    animate() {
        if (this.disposed) return;
        this.animId = requestAnimationFrame(() => this.animate());
        if (this.paused) return;

        // Smooth camera parallax lerp toward target (max ±1.5 units)
        if (this.hasMouse && !this.reducedMotion) {
            this.camera.position.x += (this.targetCamX - this.camera.position.x) * 0.05;
            this.camera.position.y += (this.targetCamY - this.camera.position.y) * 0.05;
            this.camera.lookAt(0, 0, 0);
        }

        // Slow organic drift: sine-based y offset per particle and slow whole-group rotation
        if (this.particles && this.particles.geometry.attributes.position) {
            const time = performance.now() * 0.001;
            const posAttr = this.particles.geometry.attributes.position;
            const arr = posAttr.array;
            for (let i = 0; i < this.particleCount; i++) {
                const idx = i * 3 + 1;
                arr[idx] = this.basePositions[idx] + Math.sin(time * 0.7 + this.phases[i]) * 0.8;
            }
            posAttr.needsUpdate = true;
        }

        if (this.masterGroup) {
            this.masterGroup.rotation.y += 0.0003;
        }

        this.renderer.render(this.scene, this.camera);
    }
}
