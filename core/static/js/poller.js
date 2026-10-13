/* ==========================================================================
   DevDialogue AI — Job Event Poller (§7.2)
   Polls job events at 1.5s interval while active, backs off to 5s when tab is hidden,
   stops when job finishes or tab hidden > 5 minutes.
   ========================================================================== */

import { APIClient } from './api.js';

export class JobPoller {
    constructor(sessionId, onUpdate, onComplete) {
        this.sessionId = sessionId;
        this.onUpdate = onUpdate;
        this.onComplete = onComplete;
        this.timer = null;
        this.interval = 1500;
        this.isRunning = false;
        this.hiddenTime = 0;

        this.handleVisibilityChange = this.handleVisibilityChange.bind(this);
    }

    start() {
        if (this.isRunning) return;
        this.isRunning = true;
        document.addEventListener('visibilitychange', this.handleVisibilityChange);
        this.poll();
    }

    stop() {
        this.isRunning = false;
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
        document.removeEventListener('visibilitychange', this.handleVisibilityChange);
    }

    handleVisibilityChange() {
        if (document.hidden) {
            this.interval = 5000;
            this.hiddenTime = Date.now();
        } else {
            this.interval = 1500;
            if (Date.now() - this.hiddenTime > 300000) {
                // Hidden for >5 minutes, perform a refresh poll
                this.poll();
            }
        }
    }

    async poll() {
        if (!this.isRunning) return;

        try {
            const data = await APIClient.get(`/api/session/${this.sessionId}/status/`);
            if (this.onUpdate) this.onUpdate(data);

            if (data.status === 'completed' || data.status === 'failed') {
                this.stop();
                if (this.onComplete) this.onComplete(data);
                return;
            }
        } catch (err) {
            console.warn('Poller encountered transient error:', err.message);
        }

        if (this.isRunning) {
            this.timer = setTimeout(() => this.poll(), this.interval);
        }
    }
}
