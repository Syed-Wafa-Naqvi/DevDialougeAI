/* ==========================================================================
   DevDialogue AI — Toast Notifications (§4.12)
   Bottom-right stacked toasts, auto-dismiss 4s for success, dismissible
   ========================================================================== */

import { escapeHTML } from '../render/markdown.js';

class ToastManager {
    constructor() {
        this.container = null;
    }

    init() {
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    }

    show(message, type = 'info', duration = 4000) {
        this.init();

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        
        let iconName = 'info';
        if (type === 'ok' || type === 'success') iconName = 'check-circle';
        if (type === 'warn' || type === 'warning') iconName = 'alert-triangle';
        if (type === 'err' || type === 'error') iconName = 'alert-circle';

        toast.innerHTML = `
            <i data-lucide="${iconName}" style="width:18px;height:18px;flex-shrink:0;"></i>
            <span style="flex:1;">${escapeHTML(message)}</span>
            <button type="button" style="background:none;border:none;color:var(--pencil);cursor:pointer;padding:2px;" aria-label="Dismiss">&times;</button>
        `;

        if (typeof lucide !== 'undefined') lucide.createIcons();

        const dismissBtn = toast.querySelector('button');
        dismissBtn.addEventListener('click', () => this.dismiss(toast));

        // Limit stack to max 3 toasts
        while (this.container.children.length >= 3) {
            this.dismiss(this.container.firstChild);
        }

        this.container.appendChild(toast);

        if (type !== 'err' && type !== 'error' && duration > 0) {
            setTimeout(() => this.dismiss(toast), duration);
        }
    }

    dismiss(toast) {
        if (!toast || !toast.parentNode) return;
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        toast.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
        setTimeout(() => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 200);
    }
}

export const toast = new ToastManager();
