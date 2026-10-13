/* ==========================================================================
   DevDialogue AI — Status Pill Presence Controller (§7.3)
   States: idle, thinking, streaming, building, verified, error
   ========================================================================== */

export class PresenceOrb {
    static setState(element, state = 'idle', label = '') {
        if (!element) return;
        
        element.setAttribute('data-state', state);
        
        const labelElem = element.querySelector('.status-pill-label, .orb-sr-label');
        if (labelElem) {
            const displayLabel = label || {
                idle: 'Ready',
                thinking: 'Thinking…',
                streaming: 'Generating response…',
                building: 'Building code…',
                verified: 'Checks passed',
                error: 'Action required'
            }[state] || 'Ready';
            labelElem.textContent = displayLabel;
        }
    }

    static create(size = 'sm', initialState = 'idle', labelText = 'Ready') {
        const wrapper = document.createElement('div');
        wrapper.className = 'presence-status-pill';
        wrapper.setAttribute('data-state', initialState);
        wrapper.setAttribute('aria-live', 'polite');

        const iconContainer = document.createElement('span');
        iconContainer.className = 'presence-status-icon';
        if (initialState === 'thinking') {
            iconContainer.innerHTML = '<span class="presence-status-dot"></span><span class="presence-status-dot"></span><span class="presence-status-dot"></span>';
        }

        const label = document.createElement('span');
        label.className = 'status-pill-label';
        label.textContent = labelText;

        wrapper.appendChild(iconContainer);
        wrapper.appendChild(label);
        return wrapper;
    }
}
