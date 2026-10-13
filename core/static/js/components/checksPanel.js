/* ==========================================================================
   DevDialogue AI — Verification Checks Component (§4.8)
   Grouped verification issues with severity badges and line jumper links
   ========================================================================== */

import { escapeHTML } from '../render/markdown.js';

export function renderChecksPanel(container, verificationData, onJumpToLine) {
    if (!container) return;

    const summaryText = verificationData ? (
        verificationData.errors_count === 0 && verificationData.warnings_count === 0
            ? 'Static checks: passed · Runtime checks: not run (Off)'
            : `${verificationData.errors_count || 0} errors, ${verificationData.warnings_count || 0} warnings remaining`
    ) : 'No checks run yet. Checks run automatically during build.';

    const issues = (verificationData && verificationData.issues) ? verificationData.issues : [];

    const issuesListHTML = issues.length > 0 ? issues.map(iss => `
        <div class="issue-card-item ${iss.severity === 'error' ? 'issue-err' : 'issue-warn'}" data-file="${escapeHTML(iss.file)}" data-line="${iss.line || 1}">
            <i data-lucide="${iss.severity === 'error' ? 'alert-circle' : 'alert-triangle'}" style="color:var(--${iss.severity === 'error' ? 'err' : 'warn'});width:18px;height:18px;flex-shrink:0;"></i>
            <div class="issue-details">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                    <span style="font-weight:600;font-size:var(--text-sm);">${escapeHTML(iss.file)}</span>
                    <span class="issue-line-badge">Line ${iss.line || 1}</span>
                </div>
                <span class="issue-message-text">${escapeHTML(iss.message || iss.check_name)}</span>
            </div>
        </div>
    `).join('') : `
        <div class="empty-code-view" style="padding:var(--space-5);">
            <i data-lucide="shield-check" style="width:36px;height:36px;color:var(--ok);"></i>
            <h4>All Static Verification Checks Passed</h4>
            <p class="text-pencil text-sm">No syntax or import errors detected across project modules.</p>
        </div>
    `;

    container.innerHTML = `
        <div class="checks-panel-container">
            <div class="checks-summary-banner">
                <span class="checks-summary-status">
                    <i data-lucide="shield" style="color:var(--blueprint);width:16px;height:16px;"></i>
                    ${escapeHTML(summaryText)}
                </span>
            </div>
            <div class="issues-group">
                ${issuesListHTML}
            </div>
        </div>
    `;

    if (typeof lucide !== 'undefined') lucide.createIcons();

    // Attach jumper handlers
    container.querySelectorAll('.issue-card-item').forEach(card => {
        card.addEventListener('click', () => {
            const filePath = card.getAttribute('data-file');
            const lineNumber = parseInt(card.getAttribute('data-line'), 10);
            if (onJumpToLine) onJumpToLine(filePath, lineNumber);
        });
    });
}
