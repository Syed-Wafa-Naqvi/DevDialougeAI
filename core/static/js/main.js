/* ==========================================================================
   DevDialogue AI — Main Application Entry (§7.1)
   Initializes global features: keyboard shortcuts, offline banner, drag divider
   ========================================================================== */

import { toast } from './components/toast.js';
import { CommandPalette } from './components/commandPalette.js';

document.addEventListener('DOMContentLoaded', () => {
    console.log('DevDialogue AI UI System Initialized.');

    // 1. Theme Management (§2.2)
    initThemeManager();

    // 2. Offline Banner (§4.12)
    initOfflineBanner();

    // 3. Keyboard Shortcuts Listener (§6)
    initKeyboardShortcuts();

    // 4. Resizable Workspace Divider (§3.1)
    initResizableWorkspace();

    // 5. Command Palette Init (Ctrl+K §3.8)
    CommandPalette.init();
});

function initThemeManager() {
    const savedTheme = localStorage.getItem('theme');
    if (savedTheme) {
        document.documentElement.setAttribute('data-theme', savedTheme);
    }

    const themeToggleBtn = document.getElementById('theme-toggle');
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            const current = document.documentElement.getAttribute('data-theme') || 'dark';
            const nextTheme = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', nextTheme);
            localStorage.setItem('theme', nextTheme);
            toast.show(`Switched to ${nextTheme} theme`, 'info', 2000);
        });
    }
}

function initOfflineBanner() {
    const updateOnlineStatus = () => {
        if (!navigator.onLine) {
            toast.show('Network connection lost. Waiting to reconnect...', 'err', 0);
        } else {
            toast.show('Connection restored.', 'ok', 3000);
        }
    };

    window.addEventListener('online', updateOnlineStatus);
    window.addEventListener('offline', updateOnlineStatus);
}

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Open Keyboard Shortcuts Dialog on '?'
        if (e.key === '?' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
            e.preventDefault();
            showShortcutsDialog();
        }

        // Toggle left sidebar Ctrl+B or Cmd+B
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {
            e.preventDefault();
            if (typeof window.toggleSidebar === 'function') {
                window.toggleSidebar();
            }
        }

        // Toggle workspace panel Ctrl+J or Cmd+J
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'j') {
            e.preventDefault();
            if (typeof window.toggleCodeWorkspace === 'function') {
                window.toggleCodeWorkspace();
            }
        }
    });
}

function showShortcutsDialog() {
    let dialog = document.getElementById('keyboard-shortcuts-modal');
    if (!dialog) {
        dialog = document.createElement('dialog');
        dialog.id = 'keyboard-shortcuts-modal';
        dialog.className = 'modal-dialog';
        dialog.innerHTML = `
            <h3>Keyboard Shortcuts</h3>
            <div style="margin:var(--space-4) 0;display:flex;flex-direction:column;gap:var(--space-2);">
                <div style="display:flex;justify-content:space-between;"><kbd>Ctrl / Cmd + Enter</kbd> <span>Send message</span></div>
                <div style="display:flex;justify-content:space-between;"><kbd>Ctrl / Cmd + B</kbd> <span>Toggle left sidebar</span></div>
                <div style="display:flex;justify-content:space-between;"><kbd>Ctrl / Cmd + J</kbd> <span>Toggle workspace panel</span></div>
                <div style="display:flex;justify-content:space-between;"><kbd>?</kbd> <span>Open this shortcuts menu</span></div>
                <div style="display:flex;justify-content:space-between;"><kbd>Esc</kbd> <span>Close modal / Cancel generation</span></div>
            </div>
            <div style="text-align:right;">
                <button type="button" class="btn btn-secondary" onclick="this.closest('dialog').close()">Close</button>
            </div>
        `;
        document.body.appendChild(dialog);
    }
    dialog.showModal();
}

function initResizableWorkspace() {
    const divider = document.getElementById('workspace-drag-divider');
    const workspace = document.querySelector('.workspace-region');

    if (!divider || !workspace) return;

    let isDragging = false;

    divider.addEventListener('mousedown', (e) => {
        isDragging = true;
        divider.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const containerWidth = window.innerWidth;
        const newWidth = ((containerWidth - e.clientX) / containerWidth) * 100;
        if (newWidth >= 25 && newWidth <= 75) {
            workspace.style.width = `${newWidth}%`;
            localStorage.setItem('devdialogue_workspace_width', `${newWidth}%`);
        }
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            divider.classList.remove('dragging');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}
