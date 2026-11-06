/**
 * DevDialogue AI — Animation Presets & Reveals (§6.1, §6.3, §6.5)
 */

import { EASES } from './ease.js';
import { qualityManager } from './quality.js';

export function initScrollReveals() {
    try {
        if (typeof gsap === 'undefined' || typeof ScrollTrigger === 'undefined') {
            document.documentElement.classList.remove('js');
            return;
        }
        gsap.registerPlugin(ScrollTrigger);

        const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const isReduced = prefersReducedMotion || qualityManager.getTier() === 'Reduced';

        if (isReduced) {
            gsap.set('[data-reveal]', { opacity: 0 });
            ScrollTrigger.batch('[data-reveal]', {
                start: 'top 85%',
                once: true,
                onEnter: (batch) => {
                    gsap.to(batch, {
                        opacity: 1,
                        duration: 0.4,
                        ease: 'power2.out',
                        overwrite: 'auto'
                    });
                }
            });
            return;
        }

        // normal mode
        gsap.set('[data-reveal]', { opacity: 0, y: 36 });
        ScrollTrigger.batch('[data-reveal]', {
            start: 'top 85%',
            once: true,
            onEnter: (batch) => {
                gsap.to(batch, {
                    opacity: 1,
                    y: 0,
                    duration: 1.35,
                    ease: 'power2.out',
                    stagger: 0.22,
                    overwrite: 'auto'
                });
            }
        });
    } catch (err) {
        console.error('[initScrollReveals] Error initializing scroll reveals:', err);
        document.documentElement.classList.remove('js');
    }
}

/**
 * 3D Card Tilt Interaction (§6.5)
 */
export function initTiltCards() {
    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion || qualityManager.getTier() === 'Reduced' || typeof gsap === 'undefined') return;

    const cards = document.querySelectorAll('.tilt-card');
    cards.forEach((card) => {
        let glare = card.querySelector('.tilt-card-glare');
        if (!glare) {
            glare = document.createElement('div');
            glare.className = 'tilt-card-glare';
            card.appendChild(glare);
        }

        gsap.set(card, { transformPerspective: 1000, transformStyle: 'preserve-3d' });

        const setRotX = gsap.quickTo(card, 'rotationX', { duration: 0.5, ease: 'power3.out' });
        const setRotY = gsap.quickTo(card, 'rotationY', { duration: 0.5, ease: 'power3.out' });

        const handleEnter = () => {
            gsap.to(card, { scale: 1.01, duration: 0.5, ease: 'power3.out', overwrite: 'auto' });
        };

        const handleMove = (e) => {
            const rect = card.getBoundingClientRect();
            const x = (e.clientX - rect.left) / rect.width - 0.5; // -0.5 to 0.5
            const y = (e.clientY - rect.top) / rect.height - 0.5; // -0.5 to 0.5
            // Max rotation ±5° (not ±10°)
            const rotX = -y * 10;
            const rotY = x * 10;

            setRotX(rotX);
            setRotY(rotY);

            if (glare) {
                glare.style.opacity = '0.12'; // soft glare max opacity 0.12
                glare.style.background = `radial-gradient(circle at ${(x + 0.5) * 100}% ${(y + 0.5) * 100}%, rgba(255,255,255,1), transparent 60%)`;
            }
        };

        const handleLeave = () => {
            // On mouseleave, ease back to 0 over 0.6s with 'power3.out'
            gsap.to(card, {
                rotationX: 0,
                rotationY: 0,
                scale: 1,
                duration: 0.6,
                ease: 'power3.out',
                overwrite: 'auto'
            });
            if (glare) {
                glare.style.opacity = '0';
            }
        };

        card.removeEventListener('mouseenter', card._tiltEnter);
        card.removeEventListener('mousemove', card._tiltMove);
        card.removeEventListener('mouseleave', card._tiltLeave);

        card._tiltEnter = handleEnter;
        card._tiltMove = handleMove;
        card._tiltLeave = handleLeave;

        card.addEventListener('mouseenter', handleEnter);
        card.addEventListener('mousemove', handleMove);
        card.addEventListener('mouseleave', handleLeave);
    });
}

/**
 * Magnetic Button Interaction (§6.5)
 */
export function initMagneticButtons() {
    const prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion || qualityManager.getTier() === 'Reduced' || typeof gsap === 'undefined') return;

    const buttons = document.querySelectorAll('.magnetic-btn, .btn-primary');
    buttons.forEach((btn) => {
        const handleMove = (e) => {
            const rect = btn.getBoundingClientRect();
            const x = e.clientX - (rect.left + rect.width / 2);
            const y = e.clientY - (rect.top + rect.height / 2);
            // Pull strength 0.15, duration 0.5 'power3.out'
            gsap.to(btn, { x: x * 0.15, y: y * 0.15, duration: 0.5, ease: 'power3.out', overwrite: 'auto' });
        };

        const handleLeave = () => {
            // Return duration 0.6 'power3.out' (not elastic)
            gsap.to(btn, { x: 0, y: 0, duration: 0.6, ease: 'power3.out', overwrite: 'auto' });
        };

        btn.removeEventListener('mousemove', btn._magMove);
        btn.removeEventListener('mouseleave', btn._magLeave);
        btn._magMove = handleMove;
        btn._magLeave = handleLeave;

        btn.addEventListener('mousemove', handleMove);
        btn.addEventListener('mouseleave', handleLeave);
    });
}
