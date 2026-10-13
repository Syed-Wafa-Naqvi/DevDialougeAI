/**
 * DevDialogue AI — Custom Motion Eases (v3 Rebuild)
 */

export function registerEases() {
    if (typeof gsap === 'undefined') return;
    
    // Register custom eases if CustomEase plugin is present or fallback to GSAP built-in eases
    if (gsap.parseEase) {
        gsap.defaults({
            ease: 'expo.out',
            duration: 0.5
        });
    }
}

export const EASES = {
    expoOut: 'expo.out',
    power3In: 'power3.in',
    power2InOut: 'power2.inOut',
    springOut: 'back.out(1.7)',
    bounce: 'elastic.out(1, 0.5)'
};
