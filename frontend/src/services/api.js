import axios from 'axios';

const inferredApiBase =
    typeof window !== 'undefined'
        ? `${window.location.protocol}//${window.location.hostname}:8002/api/v1/dialer`
        : 'http://localhost:8002/api/v1/dialer';

const BASE_URL =
    import.meta.env.VITE_API_URL ||
    import.meta.env.VITE_API_BASE_URL ||
    import.meta.env.VITE_API_BASE ||
    (typeof process !== 'undefined' ? process.env.REACT_APP_API_URL : undefined) ||
    inferredApiBase;

const api = axios.create({
    baseURL: BASE_URL,
    headers: { 'Content-Type': 'application/json' },
});

// Attach JWT token to every request
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
});

// Auto-refresh on 401
api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const original = error.config;
        if (error.response?.status === 401 && !original._retry) {
            original._retry = true;
            const refresh = localStorage.getItem('refresh_token');
            if (refresh) {
                try {
                    const { data } = await axios.post(`${BASE_URL}/auth/refresh/`, { refresh });
                    localStorage.setItem('access_token', data.access);
                    original.headers.Authorization = `Bearer ${data.access}`;
                    return api(original);
                } catch {
                    localStorage.removeItem('access_token');
                    localStorage.removeItem('refresh_token');
                    localStorage.removeItem('user');
                }
            }
        }
        return Promise.reject(error);
    }
);

export default api;
