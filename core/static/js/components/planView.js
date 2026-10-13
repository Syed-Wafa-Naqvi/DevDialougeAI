/* ==========================================================================
   DevDialogue AI — Plan View Component (§4.5, §5.2)
   Renders "The Drafting Table" signature Drawing Sheet Plan
   ========================================================================== */

import { escapeHTML } from '../render/markdown.js';

export function renderPlanView(container, planData, onApprovePlan) {
    if (!container) return;

    if (!planData || !planData.files || planData.files.length === 0) {
        container.innerHTML = `
            <div class="plan-sheet-container">
                <div class="empty-code-view">
                    <i data-lucide="map" style="width:36px;height:36px;color:var(--pencil);"></i>
                    <h4>Architectural Plan Being Drafted</h4>
                    <p>DevDialogue AI is interviewing and preparing your blueprint. The drawing sheet will appear here once initial requirements are gathered.</p>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    const titleBlockHTML = `
        <div class="plan-title-block">
            ${planData.approved ? '<div class="approval-stamp">APPROVED ✓</div>' : ''}
            <div class="title-block-field">
                <span class="title-block-label">PROJECT NAME</span>
                <span class="title-block-value">${escapeHTML(planData.project_name || 'System Plan')}</span>
            </div>
            <div class="title-block-field">
                <span class="title-block-label">TECH STACK</span>
                <span class="title-block-value">${escapeHTML(planData.tech_stack || 'Python / Django')}</span>
            </div>
            <div class="title-block-field">
                <span class="title-block-label">PLAN VERSION</span>
                <span class="title-block-value">v${planData.version || '1.0'}</span>
            </div>
            <div class="title-block-field">
                <span class="title-block-label">MODULE COUNT</span>
                <span class="title-block-value">${planData.files.length} Files</span>
            </div>
        </div>
    `;

    const fileCardsHTML = planData.files.map(f => `
        <div class="plan-file-card" data-path="${escapeHTML(f.path)}">
            <div class="plan-file-card-header">
                <span class="plan-file-path">${escapeHTML(f.path)}</span>
                <span class="badge badge-info">${escapeHTML(f.layer || 'Module')}</span>
            </div>
            <p class="plan-file-purpose">${escapeHTML(f.purpose || 'Implements core architecture component.')}</p>
            ${f.exports ? `<div class="plan-file-exports">Exports: ${escapeHTML(f.exports.join(', '))}</div>` : ''}
        </div>
    `).join('');

    // Render Topological Dependency SVG Graph (§4.5)
    const svgGraphHTML = renderDependencySVG(planData.files);

    const actionsHTML = `
        <div class="plan-actions-bar">
            <div class="plan-version-info">
                <span class="text-pencil text-sm">Reviewing blueprint requirements</span>
            </div>
            <div class="plan-btn-group">
                ${!planData.approved ? `
                    <button type="button" class="btn btn-primary" id="btn-approve-plan-action">
                        <i data-lucide="check-circle"></i> Approve Plan and Build
                    </button>
                ` : `
                    <span class="badge badge-ok"><i data-lucide="check"></i> Blueprint Approved</span>
                `}
            </div>
        </div>
    `;

    container.innerHTML = `
        <div class="plan-sheet-container">
            ${titleBlockHTML}
            <div class="plan-modules-grid">
                ${fileCardsHTML}
            </div>
            <div class="dependency-graph-section">
                <h4 style="margin-bottom:var(--space-2);">Topological Dependency Graph</h4>
                ${svgGraphHTML}
            </div>
            ${actionsHTML}
        </div>
    `;

    if (typeof lucide !== 'undefined') lucide.createIcons();

    const approveBtn = container.querySelector('#btn-approve-plan-action');
    if (approveBtn && onApprovePlan) {
        approveBtn.addEventListener('click', onApprovePlan);
    }
}

function renderDependencySVG(files) {
    if (!files || files.length === 0) return '';

    const width = 600;
    const height = 160;
    const nodeWidth = 110;
    const nodeHeight = 32;

    const layers = {};
    files.forEach((f, idx) => {
        const layerIdx = idx % 3; // Layer columns
        if (!layers[layerIdx]) layers[layerIdx] = [];
        layers[layerIdx].push({ ...f, id: idx });
    });

    let nodesSVG = '';
    let edgesSVG = '';

    const positions = {};

    Object.keys(layers).forEach(layerKey => {
        const col = parseInt(layerKey);
        const colFiles = layers[layerKey];
        const x = 50 + col * 200;

        colFiles.forEach((file, row) => {
            const y = 30 + row * 45;
            positions[file.path] = { x: x + nodeWidth / 2, y: y + nodeHeight / 2 };

            nodesSVG += `
                <g class="dep-node-group">
                    <rect x="${x}" y="${y}" width="${nodeWidth}" height="${nodeHeight}" class="dep-node" />
                    <text x="${x + nodeWidth / 2}" y="${y + nodeHeight / 2}" class="dep-node-text">${escapeHTML(file.path.split('/').pop())}</text>
                </g>
            `;
        });
    });

    // Draw dependency lines between nodes
    files.forEach(f => {
        if (f.deps && Array.isArray(f.deps)) {
            f.deps.forEach(depPath => {
                if (positions[f.path] && positions[depPath]) {
                    const start = positions[depPath];
                    const end = positions[f.path];
                    edgesSVG += `<line x1="${start.x}" y1="${start.y}" x2="${end.x}" y2="${end.y}" class="dep-edge" />`;
                }
            });
        }
    });

    return `
        <svg viewBox="0 0 ${width} ${height}" class="dependency-graph-svg">
            ${edgesSVG}
            ${nodesSVG}
        </svg>
    `;
}
