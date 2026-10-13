/* ==========================================================================
   DevDialogue AI — Application Store (§7.1)
   Lightweight reactive store for workspace state, active tab, active file, plan, draft
   ========================================================================== */

class AppStore {
    constructor() {
        this.state = {
            sessionId: null,
            activeTab: localStorage.getItem('devdialogue_active_tab') || 'plan',
            activeFileId: null,
            expandedNodes: new Set(JSON.parse(localStorage.getItem('devdialogue_tree_nodes') || '[]')),
            workspaceWidth: localStorage.getItem('devdialogue_workspace_width') || '45%',
            workspaceOpen: localStorage.getItem('devdialogue_workspace_open') !== 'false',
            plan: null,
            verification: null,
            tree: [],
            diffs: [],
            activeJob: null
        };
        this.listeners = new Set();
    }

    getState() {
        return this.state;
    }

    setState(partial) {
        this.state = { ...this.state, ...partial };
        if ('activeTab' in partial) {
            localStorage.setItem('devdialogue_active_tab', partial.activeTab);
        }
        if ('workspaceWidth' in partial) {
            localStorage.setItem('devdialogue_workspace_width', partial.workspaceWidth);
        }
        if ('workspaceOpen' in partial) {
            localStorage.setItem('devdialogue_workspace_open', String(partial.workspaceOpen));
        }
        this.notify();
    }

    toggleNode(nodePath) {
        if (this.state.expandedNodes.has(nodePath)) {
            this.state.expandedNodes.delete(nodePath);
        } else {
            this.state.expandedNodes.add(nodePath);
        }
        localStorage.setItem('devdialogue_tree_nodes', JSON.stringify(Array.from(this.state.expandedNodes)));
        this.notify();
    }

    subscribe(listener) {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }

    notify() {
        for (const listener of this.listeners) {
            listener(this.state);
        }
    }
}

export const store = new AppStore();
