/**
 * DevDialogue AI — Performance Tier Manager (v4 Studio Light)
 * Ultra: 3D + Perspective Composition + High FPS
 * High: Smooth CSS 3D + Transitions + Motion Effects (DEFAULT)
 * Lite: Simple CSS transforms & transitions
 * Reduced: Simple fades, accessible static layouts (Explicit user choice)
 */

class QualityManager {
    constructor() {
        this.tier = 'High'; // Default High Tier for full motion
        this.frameTimeHistory = [];
        this.monitoring = false;
        this.init();
    }

    init() {
        const stored = localStorage.getItem('devdialogue_quality_tier');
        if (stored) {
            this.tier = stored;
        } else {
            this.tier = 'High'; // Ensure smooth animations out of the box
        }

        this.applyTierClasses();
    }

    applyTierClasses() {
        document.body.classList.remove('tier-ultra', 'tier-high', 'tier-lite', 'reduce-motion');
        if (this.tier === 'Reduced') {
            document.body.classList.add('reduce-motion');
        } else {
            document.body.classList.add(`tier-${this.tier.toLowerCase()}`);
        }
    }

    setTier(newTier) {
        this.tier = newTier;
        localStorage.setItem('devdialogue_quality_tier', newTier);
        this.applyTierClasses();
        window.dispatchEvent(new CustomEvent('quality-tier-changed', { detail: { tier: newTier } }));
    }

    getTier() {
        return this.tier;
    }

    startFrameTimingMonitor() {
        if (this.monitoring || this.tier === 'Lite' || this.tier === 'Reduced') return;
        this.monitoring = true;
        let lastTime = performance.now();
        let frames = 0;

        const check = (now) => {
            if (!this.monitoring) return;
            const delta = now - lastTime;
            lastTime = now;
            this.frameTimeHistory.push(delta);
            if (this.frameTimeHistory.length > 60) this.frameTimeHistory.shift();

            frames++;
            if (frames > 120) {
                const avg = this.frameTimeHistory.reduce((a, b) => a + b, 0) / this.frameTimeHistory.length;
                if (avg > 35 && this.tier === 'Ultra') {
                    this.setTier('High');
                }
                frames = 0;
            }
            requestAnimationFrame(check);
        };
        requestAnimationFrame(check);
    }
}

export const qualityManager = new QualityManager();
