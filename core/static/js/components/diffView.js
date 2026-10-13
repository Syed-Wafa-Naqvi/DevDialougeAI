/* ==========================================================================
   DevDialogue AI — Diff Viewer Component (§4.9)
   Unified diff view with green/red tinted lines, + / - markers, action buttons
   ========================================================================== */

import { escapeHTML } from '../render/markdown.js';

export function renderDiffView(container, diffData, onAccept, onRequestChange, onRevert) {
    if (!container) return;

    if (!diffData || (!diffData.diff_text && (!diffData.lines || diffData.lines.length === 0))) {
        container.innerHTML = `
            <div class="diff-viewer-container">
                <div class="empty-code-view" style="padding:var(--space-5);">
                    <i data-lucide="git-compare" style="width:36px;height:36px;color:var(--pencil);"></i>
                    <h4>No File Modifications to Review</h4>
                    <p class="text-pencil text-sm">When code repairs or user requested changes occur, diffs will appear here for side-by-side inspection.</p>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        return;
    }

    const linesHTML = parseDiffTextToHTML(diffData.diff_text || '');

    container.innerHTML = `
        <div class="diff-viewer-container">
            <div class="diff-header-bar">
                <span class="diff-reason-text">
                    <i data-lucide="git-commit" style="width:14px;height:14px;color:var(--blueprint);display:inline;vertical-align:middle;"></i>
                    ${escapeHTML(diffData.reason || 'Code modification diff')}
                </span>
                <div style="display:flex;gap:var(--space-2);">
                    <button type="button" class="btn btn-secondary btn-sm" id="btn-diff-revert">Revert</button>
                    <button type="button" class="btn btn-primary btn-sm" id="btn-diff-accept">Accept Change</button>
                </div>
            </div>
            <div class="diff-content-pane">
                <table class="diff-table">
                    <tbody>
                        ${linesHTML}
                    </tbody>
                </table>
            </div>
        </div>
    `;

    if (typeof lucide !== 'undefined') lucide.createIcons();

    const acceptBtn = container.querySelector('#btn-diff-accept');
    if (acceptBtn && onAccept) acceptBtn.addEventListener('click', onAccept);

    const revertBtn = container.querySelector('#btn-diff-revert');
    if (revertBtn && onRevert) revertBtn.addEventListener('click', onRevert);
}

function parseDiffTextToHTML(diffText) {
    if (!diffText) return '';

    const lines = diffText.split('\n');
    let html = '';
    let oldNum = 1;
    let newNum = 1;

    lines.forEach(line => {
        if (line.startsWith('+++') || line.startsWith('---')) return;

        if (line.startsWith('+')) {
            html += `
                <tr class="diff-row diff-row-added">
                    <td class="diff-num"></td>
                    <td class="diff-num">${newNum++}</td>
                    <td class="diff-marker">+</td>
                    <td class="diff-line-code">${escapeHTML(line.substring(1))}</td>
                </tr>
            `;
        } else if (line.startsWith('-')) {
            html += `
                <tr class="diff-row diff-row-removed">
                    <td class="diff-num">${oldNum++}</td>
                    <td class="diff-num"></td>
                    <td class="diff-marker">−</td>
                    <td class="diff-line-code">${escapeHTML(line.substring(1))}</td>
                </tr>
            `;
        } else {
            html += `
                <tr class="diff-row">
                    <td class="diff-num">${oldNum++}</td>
                    <td class="diff-num">${newNum++}</td>
                    <td class="diff-marker"></td>
                    <td class="diff-line-code">${escapeHTML(line)}</td>
                </tr>
            `;
        }
    });

    return html;
}
