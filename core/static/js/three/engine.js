/**
 * DevDialogue AI — Three.js Architecture Graph Engine (v4 Studio Light §7.2)
 * Clean, bright diagram-like 3D architecture graph with crisp nodes, thin lines, and restrained depth.
 */

import { qualityManager } from '../motion/quality.js';

export class ThreeEngine {
    constructor(canvasElement) {
        if (!canvasElement || typeof THREE === 'undefined') return;
        this.canvas = canvasElement;
        this.tier = qualityManager.getTier();

        if (this.tier === 'Lite' || this.tier === 'Reduced') return;

        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(50, canvasElement.clientWidth / canvasElement.clientHeight, 0.1, 1000);
        this.renderer = new THREE.WebGLRenderer({
            canvas: canvasElement,
            alpha: true,
            antialias: true,
            powerPreference: 'high-performance'
        });

        const pixelRatio = Math.min(window.devicePixelRatio, 2);
        this.renderer.setPixelRatio(pixelRatio);
        this.renderer.setSize(canvasElement.clientWidth, canvasElement.clientHeight);

        this.disposed = false;
        this.animId = null;
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
        window.addEventListener('mousemove', (e) => {
            this.mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
            this.mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
        });
    }

    animate() {
        if (this.disposed) return;
        this.animId = requestAnimationFrame(() => this.animate());

        if (this.graphGroup) {
            this.camera.position.x += (this.mouseX * 3 - this.camera.position.x) * 0.05;
            this.camera.position.y += (-this.mouseY * 3 - this.camera.position.y) * 0.05;
            this.camera.lookAt(this.scene.position);
        }

        this.renderer.render(this.scene, this.camera);
    }
}
