/* ==========================================================================
   DevDialogue AI — File Tree Component (§4.7)
   Collapsible folders, status badges (checked ✓, warnings ⚠, errors ✕), file icons
   ========================================================================== */

import { escapeHTML } from '../render/markdown.js';

export function renderFileTree(container, files, activeFileId, onFileSelect, expandedNodes, onToggleNode) {
    if (!container) return;

    if (!files || files.length === 0) {
        container.innerHTML = `
            <div class="file-tree-container">
                <div class="empty-code-view" style="padding:var(--space-5);">
                    <i data-lucide="folder-open" style="width:32px;height:32px;color:var(--pencil);"></i>
                    <p class="text-pencil text-sm">No project files generated yet.</p>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    const fileListHTML = files.map(f => {
        const isActive = f.id == activeFileId;
        const statusBadgeHTML = getStatusBadgeHTML(f.status || 'checked');

        return `
            <li class="tree-node">
                <div class="tree-item-row ${isActive ? 'active' : ''}" data-id="${f.id}" data-path="${escapeHTML(f.module_name)}">
                    <div class="tree-item-left">
                        <i data-lucide="file-code" style="width:14px;height:14px;color:var(--blueprint);"></i>
                        <span class="tree-item-name">${escapeHTML(f.module_name)}</span>
                    </div>
                    ${statusBadgeHTML}
                </div>
            </li>
        `;
    }).join('');

    container.innerHTML = `
        <div class="file-tree-container">
            <div class="file-tree-toolbar">
                <input type="text" class="file-search-input" id="tree-search-filter" placeholder="Filter files by name..." />
            </div>
            <ul class="tree-view-list">
                ${fileListHTML}
            </ul>
        </div>
    `;

    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Attach row click handlers
    container.querySelectorAll('.tree-item-row').forEach(row => {
        row.addEventListener('click', () => {
            const fileId = row.getAttribute('data-id');
            if (onFileSelect) onFileSelect(fileId);
        });
    });

    // Search filter handling
    const searchInput = container.querySelector('#tree-search-filter');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase();
            container.querySelectorAll('.tree-item-row').forEach(row => {
                const path = row.getAttribute('data-path').toLowerCase();
                row.style.display = path.includes(query) ? 'flex' : 'none';
            });
        });
    }
}

function getStatusBadgeHTML(status) {
    switch (status) {
        case 'verified':
        case 'checked':
            return `<span class="badge badge-ok">✓ verified</span>`;
        case 'warning':
        case 'warnings':
            return `<span class="badge badge-warn">⚠ warning</span>`;
        case 'error':
        case 'errors':
            return `<span class="badge badge-err">✕ error</span>`;
        case 'writing':
        case 'generating':
            return `<span class="badge badge-info">⏳ writing</span>`;
        default:
            return `<span class="badge badge-neutral">pending</span>`;
    }
}
