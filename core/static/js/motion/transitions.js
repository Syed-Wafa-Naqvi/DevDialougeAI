/**
 * DevDialogue AI — Page Transition & Animation Re-Initialization Engine
 */

import { initScrollReveals, initTiltCards, initMagneticButtons } from './presets.js';
import { initSmoothScroll } from './scroll.js';
import { qualityManager } from './quality.js';

export function initPageTransitions() {
    if (typeof barba === 'undefined') {
        return;
    }

    // Register Barba hooks to re-initialize scripts after container swap
    barba.hooks.afterEnter(() => {
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
        initScrollReveals();
        initTiltCards();
        initMagneticButtons();
        initSmoothScroll();
    });

    barba.init({
        prevent: ({ el }) => {
            // Prevent Barba on forms, workspace actions, auth routes, or external links
            return el.hasAttribute('data-barba-prevent') || 
                   el.tagName === 'FORM' || 
                   el.href?.includes('/chat/') || 
                   el.href?.includes('/dashboard/') || 
                   el.href?.includes('/settings/') || 
                   el.href?.includes('/login/') || 
                   el.href?.includes('/signup/') || 
                   el.href?.includes('/welcome/');
        },
        transitions: [{
            name: 'fade-rise',
            async leave({ current }) {
                const container = current.container;
                if (qualityManager.getTier() === 'Reduced') {
                    return gsap.to(container, { opacity: 0, duration: 0.15 });
                }
                return gsap.to(container, {
                    scale: 0.98,
                    opacity: 0,
                    duration: 0.25,
                    ease: 'power2.in'
                });
            },
            enter({ next }) {
                const container = next.container;
                window.scrollTo(0, 0);

                if (qualityManager.getTier() === 'Reduced') {
                    return gsap.fromTo(container, { opacity: 0 }, { opacity: 1, duration: 0.2 });
                }

                return gsap.fromTo(container,
                    { y: 16, opacity: 0 },
                    {
                        y: 0,
                        opacity: 1,
                        duration: 0.35,
                        ease: 'power2.out',
                        onComplete: () => {
                            if (typeof lucide !== 'undefined') lucide.createIcons();
                            initScrollReveals();
                            initTiltCards();
                            initMagneticButtons();
                        }
                    }
                );
            }
        }]
    });
}
