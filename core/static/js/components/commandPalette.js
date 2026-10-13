/* ==========================================================================
   DevDialogue AI — Command Palette Controller (`Ctrl/Cmd+K` §3.8)
   ========================================================================== */

import { escapeHTML } from '../render/markdown.js';

export class CommandPalette {
    static init() {
        let dialog = document.getElementById('command-palette-modal');
        if (!dialog) {
            dialog = document.createElement('dialog');
            dialog.id = 'command-palette-modal';
            dialog.className = 'command-palette-dialog';
            dialog.innerHTML = `
                <div class="palette-input-row">
                    <i data-lucide="search" style="width:18px;height:18px;color:var(--text-muted);"></i>
                    <input type="text" class="palette-search-input" id="palette-query" placeholder="Type a command or search project..." autofocus />
                    <kbd class="palette-shortcut-badge">ESC</kbd>
                </div>
                <ul class="palette-results-list" id="palette-results">
                    <!-- Dynamic items -->
                </ul>
            `;
            document.body.appendChild(dialog);
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }

        const queryInput = dialog.querySelector('#palette-query');
        const resultsList = dialog.querySelector('#palette-results');

        const commands = [
            { label: 'New Project', action: () => window.location.href = '/new-chat/', shortcut: 'Ctrl+N' },
            { label: 'Switch to Stage: Discover (Interview)', action: () => switchStage('discover'), shortcut: 'Alt+1' },
            { label: 'Switch to Stage: Blueprint (Plan)', action: () => switchStage('blueprint'), shortcut: 'Alt+2' },
            { label: 'Switch to Stage: Build (Generate)', action: () => switchStage('build'), shortcut: 'Alt+3' },
            { label: 'Switch to Stage: Review (IDE)', action: () => switchStage('review'), shortcut: 'Alt+4' },
            { label: 'Switch to Stage: Export (ZIP)', action: () => switchStage('export'), shortcut: 'Alt+5' },
            { label: 'Toggle Light / Dark Theme', action: () => document.getElementById('theme-toggle')?.click(), shortcut: '' },
            { label: 'Open Account Settings', action: () => window.location.href = '/settings/', shortcut: '' },
            { label: 'Open Keyboard Shortcuts', action: () => document.dispatchEvent(new KeyboardEvent('keydown', { key: '?' })), shortcut: '?' }
        ];

        function renderResults(filterText = '') {
            const query = filterText.toLowerCase().trim();
            const filtered = commands.filter(c => c.label.toLowerCase().includes(query));

            resultsList.innerHTML = filtered.map((cmd, idx) => `
                <li class="palette-item ${idx === 0 ? 'selected' : ''}" data-idx="${idx}">
                    <span>${escapeHTML(cmd.label)}</span>
                    ${cmd.shortcut ? `<kbd class="palette-shortcut-badge">${escapeHTML(cmd.shortcut)}</kbd>` : ''}
                </li>
            `).join('');

            resultsList.querySelectorAll('.palette-item').forEach((item, idx) => {
                item.addEventListener('click', () => {
                    filtered[idx].action();
                    dialog.close();
                });
            });
        }

        queryInput.addEventListener('input', (e) => renderResults(e.target.value));

        // Keyboard navigation inside palette
        dialog.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const selected = resultsList.querySelector('.palette-item.selected');
                if (selected) {
                    selected.click();
                }
            }
        });

        // Toggle palette on Ctrl+K / Cmd+K
        document.addEventListener('keydown', (e) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                renderResults();
                dialog.showModal();
                queryInput.focus();
            }
        });
    }
}

function switchStage(stageName) {
    if (typeof window.switchStageView === 'function') {
        window.switchStageView(stageName);
    }
}
