import axios from 'axios';

// Force same-origin API calls so frontend always routes through /api proxy.
const BASE_URL = '/api/v1/dialer';

/**
 * Read the CSRF token from the cookie set by Django.
 */
function getCSRFToken() {
    try {
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : '';
    } catch {
        return '';
    }
}

const api = axios.create({
    baseURL: BASE_URL,
    headers: { 'Content-Type': 'application/json' },
    withCredentials: true, // Send cookies with every request
});

// Attach CSRF token to state-changing requests
api.interceptors.request.use((config) => {
    const method = (config.method || '').toLowerCase();
    if (['post', 'put', 'patch', 'delete'].includes(method)) {
        config.headers['X-CSRFToken'] = getCSRFToken();
    }
    return config;
});

// Auto-refresh on 401
let isRefreshing = false;
let refreshQueue = [];

function processQueue(success) {
    refreshQueue.forEach(({ resolve, reject }) => {
        success ? resolve() : reject();
    });
    refreshQueue = [];
}

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const original = error.config;

        if (error.response?.status === 401 && !original._retry) {
            // Don't retry refresh or login calls
            if (original.url?.includes('/auth/refresh/') || original.url?.includes('/auth/login/')) {
                return Promise.reject(error);
            }

            original._retry = true;

            if (isRefreshing) {
                // Queue this request until refresh completes
                return new Promise((resolve, reject) => {
                    refreshQueue.push({
                        resolve: () => resolve(api(original)),
                        reject: () => reject(error),
                    });
                });
            }

            isRefreshing = true;

            try {
                // Refresh token is sent automatically via cookie
                await axios.post(`${BASE_URL}/auth/refresh/`, {}, { withCredentials: true });
                processQueue(true);
                return api(original);
            } catch {
                processQueue(false);
                window.location.href = '/login';
                return Promise.reject(error);
            } finally {
                isRefreshing = false;
            }
        }

        return Promise.reject(error);
    }
);

export default api;
