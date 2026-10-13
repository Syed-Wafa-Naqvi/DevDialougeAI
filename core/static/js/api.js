/* ==========================================================================
   DevDialogue AI — API Wrapper (§7.2)
   Attaches CSRF, handles JSON, timeouts via AbortController, error normalization
   ========================================================================== */

export class APIClient {
    static getCSRFToken() {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        if (csrfInput) return csrfInput.value;
        const cookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
        return cookie ? cookie.split('=')[1] : '';
    }

    static async request(url, options = {}) {
        const timeoutMs = options.timeout || 20000;
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

        const defaultHeaders = {
            'Content-Type': 'application/json',
            'X-CSRFToken': APIClient.getCSRFToken(),
            'Accept': 'application/json'
        };

        const config = {
            method: options.method || 'GET',
            headers: { ...defaultHeaders, ...options.headers },
            signal: controller.signal,
            ...(options.body ? { body: typeof options.body === 'string' ? options.body : JSON.stringify(options.body) } : {})
        };

        try {
            const response = await fetch(url, config);
            clearTimeout(timeoutId);

            let data;
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                data = await response.json();
            } else {
                data = { raw: await response.text() };
            }

            if (!response.ok) {
                const errorMessage = data.error || data.message || `HTTP ${response.status}: Request failed`;
                throw new Error(errorMessage);
            }

            return data;
        } catch (error) {
            clearTimeout(timeoutId);
            if (error.name === 'AbortError') {
                throw new Error('The request timed out. Please check your connection and try again.');
            }
            throw error;
        }
    }

    static get(url, options = {}) {
        return APIClient.request(url, { ...options, method: 'GET' });
    }

    static post(url, body, options = {}) {
        return APIClient.request(url, { ...options, method: 'POST', body });
    }
}
