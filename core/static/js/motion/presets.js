/**
 * DevDialogue AI — Animation Presets & Reveals (§6.1, §6.3, §6.5)
 */

import { EASES } from './ease.js';
import { qualityManager } from './quality.js';

export function initScrollReveals() {
    if (typeof gsap === 'undefined' || qualityManager.getTier() === 'Reduced') return;

    const elements = document.querySelectorAll('[data-reveal]');
    elements.forEach((el) => {
        const type = el.dataset.reveal || 'up';
        
        switch (type) {
            case 'up':
                gsap.fromTo(el, 
                    { y: 40, opacity: 0 },
                    { y: 0, opacity: 1, duration: 0.8, ease: 'expo.out',
                      scrollTrigger: { trigger: el, start: 'top 85%' }
                    }
                );
                break;
            case 'scale':
                gsap.fromTo(el, 
                    { scale: 0.9, opacity: 0 },
                    { scale: 1, opacity: 1, duration: 0.8, ease: 'expo.out',
                      scrollTrigger: { trigger: el, start: 'top 85%' }
                    }
                );
                break;
            case 'tilt':
                gsap.fromTo(el,
                    { rotateX: 18, y: 30, opacity: 0 },
                    { rotateX: 0, y: 0, opacity: 1, duration: 0.9, ease: 'expo.out',
                      scrollTrigger: { trigger: el, start: 'top 85%' }
                    }
                );
                break;
            case 'fade':
                gsap.fromTo(el,
                    { opacity: 0 },
                    { opacity: 1, duration: 0.6, ease: 'power2.out',
                      scrollTrigger: { trigger: el, start: 'top 90%' }
                    }
                );
                break;
        }
    });
}

/**
 * 3D Card Tilt Interaction (§6.5)
 */
export function initTiltCards() {
    if (qualityManager.getTier() === 'Reduced') return;

    const cards = document.querySelectorAll('.tilt-card');
    cards.forEach((card) => {
        let glare = card.querySelector('.tilt-card-glare');
        if (!glare) {
            glare = document.createElement('div');
            glare.className = 'tilt-card-glare';
            card.appendChild(glare);
        }

        const handleMove = (e) => {
            const rect = card.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const centerX = rect.width / 2;
            const centerY = rect.height / 2;
            const rotateX = ((y - centerY) / centerY) * -10;
            const rotateY = ((x - centerX) / centerX) * 10;

            card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
            if (glare) {
                glare.style.opacity = '1';
                glare.style.background = `radial-gradient(circle at ${(x / rect.width) * 100}% ${(y / rect.height) * 100}%, rgba(255,255,255,0.18), transparent 60%)`;
            }
        };

        const handleLeave = () => {
            card.style.transform = 'perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)';
            if (glare) glare.style.opacity = '0';
        };

        card.removeEventListener('mousemove', card._tiltMove);
        card.removeEventListener('mouseleave', card._tiltLeave);

        card._tiltMove = handleMove;
        card._tiltLeave = handleLeave;

        card.addEventListener('mousemove', handleMove);
        card.addEventListener('mouseleave', handleLeave);
    });
}

/**
 * Magnetic Button Interaction (§6.5)
 */
export function initMagneticButtons() {
    if (qualityManager.getTier() === 'Reduced') return;

    const buttons = document.querySelectorAll('.magnetic-btn, .btn-primary');
    buttons.forEach((btn) => {
        const handleMove = (e) => {
            const rect = btn.getBoundingClientRect();
            const x = e.clientX - (rect.left + rect.width / 2);
            const y = e.clientY - (rect.top + rect.height / 2);
            gsap.to(btn, { x: x * 0.35, y: y * 0.35, duration: 0.3, ease: 'power2.out' });
        };

        const handleLeave = () => {
            gsap.to(btn, { x: 0, y: 0, duration: 0.5, ease: 'elastic.out(1, 0.4)' });
        };

        btn.addEventListener('mousemove', handleMove);
        btn.addEventListener('mouseleave', handleLeave);
    });
}
