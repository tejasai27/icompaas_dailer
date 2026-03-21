/**
 * Resolve a media/audio URL from the backend.
 *
 * The Django backend may return:
 *   - An absolute URL like http://backend:8000/media/... or http://localhost:8000/media/...
 *   - A relative URL like /media/dialer/recordings/filename.mp3
 *
 * In both cases, we need a same-origin path (/media/...) so the Vite dev
 * server proxy (or nginx in production) can forward the request to the backend.
 */

/**
 * Convert any media URL to a browser-accessible path.
 *
 * Absolute URLs pointing at the backend (e.g. http://localhost:8000/media/...)
 * are stripped to just the path (/media/...) so they route through the
 * frontend proxy.
 *
 * @param {string|null|undefined} url - The URL returned from the API
 * @returns {string} - A URL the browser can fetch
 */
export function resolveMediaUrl(url) {
    if (!url) return '';
    const trimmed = String(url).trim();
    if (!trimmed) return '';

    // Absolute URL — extract just the path portion so it goes through the proxy
    if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
        try {
            const parsed = new URL(trimmed);
            // Return only the path (e.g. /media/dialer/recordings/file.mp3)
            return parsed.pathname + parsed.search;
        } catch {
            return trimmed;
        }
    }

    // Already a relative path — use as-is
    return trimmed;
}
