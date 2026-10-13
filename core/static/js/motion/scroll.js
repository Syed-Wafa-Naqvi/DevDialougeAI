/**
 * DevDialogue AI — Lenis Smooth Scrolling Engine (§6.2)
 */

import { qualityManager } from './quality.js';

let lenisInstance = null;

export function initSmoothScroll() {
    if (qualityManager.getTier() === 'Reduced') return null;
    if (typeof Lenis === 'undefined') return null;

    if (lenisInstance) {
        lenisInstance.destroy();
        lenisInstance = null;
    }

    lenisInstance = new Lenis({
        duration: 1.2,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        orientation: 'vertical',
        gestureOrientation: 'vertical',
        smoothWheel: true,
        wheelMultiplier: 1.0,
        touchMultiplier: 1.5
    });

    if (typeof ScrollTrigger !== 'undefined') {
        lenisInstance.on('scroll', ScrollTrigger.update);
        gsap.ticker.add((time) => {
            if (lenisInstance) {
                lenisInstance.raf(time * 1000);
            }
        });
        gsap.ticker.lagSmoothing(0);
    }

    // Top scroll progress bar sync
    const progress = document.querySelector('.top-progress-bar');
    if (progress) {
        lenisInstance.on('scroll', ({ progress: p }) => {
            progress.style.transform = `scaleX(${p})`;
        });
    }

    return lenisInstance;
}

export function getLenis() {
    return lenisInstance;
}

export function destroySmoothScroll() {
    if (lenisInstance) {
        lenisInstance.destroy();
        lenisInstance = null;
    }
}
