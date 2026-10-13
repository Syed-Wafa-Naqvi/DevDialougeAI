/* ==========================================================================
   DevDialogue AI — Markdown Renderer & DOMPurify Sanitizer (§4.3, §7.3)
   Fixes XSS vulnerability by sanitizing LLM text/markdown before DOM insertion.
   ========================================================================== */

export function renderSanitizedMarkdown(rawMarkdown) {
    if (!rawMarkdown) return '';

    // Step 1: Render Markdown if marked is loaded
    let rawHTML = '';
    if (typeof window.marked !== 'undefined' && typeof window.marked.parse === 'function') {
        rawHTML = window.marked.parse(rawMarkdown, {
            gfm: true,
            breaks: true
        });
    } else {
        // Safe basic fallback formatting
        const escaped = escapeHTML(rawMarkdown);
        rawHTML = escaped.replace(/\n/g, '<br>');
    }

    // Step 2: Sanitize HTML output using DOMPurify
    let cleanHTML = rawHTML;
    if (typeof window.DOMPurify !== 'undefined' && typeof window.DOMPurify.sanitize === 'function') {
        cleanHTML = window.DOMPurify.sanitize(rawHTML, {
            ADD_ATTR: ['target', 'rel'],
            USE_PROFILES: { html: true }
        });
    }

    // Step 3: Enhance links with security attributes (rel="noopener noreferrer" target="_blank")
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = cleanHTML;

    tempDiv.querySelectorAll('a').forEach(anchor => {
        anchor.setAttribute('target', '_blank');
        anchor.setAttribute('rel', 'noopener noreferrer');
    });

    // Step 4: Wrap code blocks with interactive copy header
    tempDiv.querySelectorAll('pre').forEach(pre => {
        const codeElement = pre.querySelector('code');
        const langClass = codeElement ? Array.from(codeElement.classList).find(c => c.startsWith('language-')) : '';
        const langName = langClass ? langClass.replace('language-', '') : 'code';

        const wrapper = document.createElement('div');
        wrapper.className = 'chat-code-wrapper';

        const header = document.createElement('div');
        header.className = 'chat-code-header';
        header.innerHTML = `
            <span class="chat-code-lang">${escapeHTML(langName)}</span>
            <button type="button" class="btn btn-ghost btn-sm btn-copy-code" title="Copy code">
                <i data-lucide="copy" style="width:14px;height:14px;"></i> Copy
            </button>
        `;

        pre.classList.add('chat-code-pre');
        
        // Setup copy button action
        const copyBtn = header.querySelector('.btn-copy-code');
        copyBtn.addEventListener('click', () => {
            const textToCopy = codeElement ? codeElement.textContent : pre.textContent;
            navigator.clipboard.writeText(textToCopy).then(() => {
                copyBtn.innerHTML = `<i data-lucide="check" style="width:14px;height:14px;color:var(--ok);"></i> Copied!`;
                if (typeof lucide !== 'undefined') lucide.createIcons();
                setTimeout(() => {
                    copyBtn.innerHTML = `<i data-lucide="copy" style="width:14px;height:14px;"></i> Copy`;
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                }, 1500);
            });
        });

        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(header);
        wrapper.appendChild(pre);

        // Highlight with Prism if available
        if (typeof window.Prism !== 'undefined' && codeElement) {
            window.Prism.highlightElement(codeElement);
        }
    });

    return tempDiv.innerHTML;
}

export function escapeHTML(str) {
    if (!str) return '';
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}
