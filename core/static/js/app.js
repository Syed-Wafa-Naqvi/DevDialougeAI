/**
 * DevDialogue AI — Master Application Entry Point (v3 Rebuild)
 * Modular ES Architecture, WebGL 3D, GSAP Motion Engine, Lenis & Barba.js
 */

import { registerEases } from './motion/ease.js';
import { initScrollReveals, initTiltCards, initMagneticButtons } from './motion/presets.js';
import { initSmoothScroll } from './motion/scroll.js';
import { initPageTransitions } from './motion/transitions.js';
import { qualityManager } from './motion/quality.js';
import { LandingNebulaScene } from './three/engine.js';
import { CommandPalette } from './components/commandPalette.js';
import { toast } from './components/toast.js';

// Global toggleTheme helper function
window.toggleTheme = function() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('devdialogue_theme', next);
    
    document.querySelectorAll('#theme-toggle-btn, .theme-toggle-btn').forEach(btn => {
        const icon = btn.querySelector('[data-lucide], i');
        if (icon) {
            icon.setAttribute('data-lucide', next === 'dark' ? 'moon' : 'sun');
        }
    });

    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    console.log('[DevDialogue AI] Theme toggled to:', next);
    return next;
};

class App {
    constructor() {
        this.heroScene = null;
        this.init();
    }

    init() {
        const runSetup = () => {
            registerEases();
            qualityManager.startFrameTimingMonitor();

            // Motion & Page Setup
            initSmoothScroll();
            initScrollReveals();
            initTiltCards();
            initMagneticButtons();
            initPageTransitions();
            CommandPalette.init();
            toast.init();
            this.initCustomCursor();
            this.initThreeScenes();

            // Theme toggle listener
            this.bindThemeToggle();

            console.log('[DevDialogue AI v3] Frontend Initialized successfully | Tier:', qualityManager.getTier());
        };

        if (document.readyState !== 'loading') {
            runSetup();
        } else {
            document.addEventListener('DOMContentLoaded', runSetup);
        }
    }

    initThreeScenes() {
        const heroCanvas = document.getElementById('hero-canvas');
        if (heroCanvas && qualityManager.getTier() !== 'Lite' && qualityManager.getTier() !== 'Reduced') {
            if (this.heroScene) this.heroScene.dispose();
            this.heroScene = new LandingNebulaScene(heroCanvas);
        }
    }

    initCustomCursor() {
        if (qualityManager.getTier() === 'Reduced' || 'ontouchstart' in window) return;

        let dot = document.querySelector('.custom-cursor-dot');
        let ring = document.querySelector('.custom-cursor-ring');

        if (!dot) {
            dot = document.createElement('div');
            dot.className = 'custom-cursor-dot';
            document.body.appendChild(dot);
        }
        if (!ring) {
            ring = document.createElement('div');
            ring.className = 'custom-cursor-ring';
            document.body.appendChild(ring);
        }

        document.body.classList.add('has-custom-cursor');

        window.addEventListener('mousemove', (e) => {
            if (dot && ring) {
                dot.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`;
                ring.style.transform = `translate3d(${e.clientX}px, ${e.clientY}px, 0)`;
            }
        });

        document.querySelectorAll('a, button, input, textarea, select, .tilt-card').forEach((el) => {
            el.addEventListener('mouseenter', () => document.body.classList.add('cursor-hover'));
            el.addEventListener('mouseleave', () => document.body.classList.remove('cursor-hover'));
        });
    }

    bindThemeToggle() {
        document.querySelectorAll('#theme-toggle-btn, .theme-toggle-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                window.toggleTheme();
            });
        });
    }
}

export const app = new App();
