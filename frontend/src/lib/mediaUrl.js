/**
 * Resolve a media/audio URL from the backend.
 *
 * The Django backend sometimes returns a relative URL like:
 *   /media/dialer/recordings/filename.mp3
 *
 * In Docker/Vite setups, we prefer same-origin URLs so the dev server
 * proxy can forward /media requests to backend.
 */

const trimTrailingSlashes = (value) => String(value || '').trim().replace(/\/+$/, '');
const stripDialerPath = (value) => {
  const base = trimTrailingSlashes(value);
  if (!base) return '';
  if (base.endsWith('/api/v1/dialer')) {
    return base.slice(0, -'/api/v1/dialer'.length);
  }
  return base;
};
const BACKEND_BASE = stripDialerPath(
  import.meta.env.VITE_API_BASE ||
  import.meta.env.VITE_API_URL
);

/**
 * Convert a potentially relative media URL to a fully-qualified URL
 * pointing at the backend server.
 *
 * @param {string|null|undefined} url - The URL returned from the API
 * @returns {string} - A fully-qualified URL the browser can fetch
 */
export function resolveMediaUrl(url) {
  if (!url) return '';
  const trimmed = String(url).trim();
  if (!trimmed) return '';

  // Already a full URL — return as-is
  if (trimmed.startsWith('http://') || trimmed.startsWith('https://')) {
    return trimmed;
  }

  // Relative path like /media/... — use same-origin unless backend base is explicitly configured
  if (trimmed.startsWith('/')) {
    return BACKEND_BASE ? `${BACKEND_BASE}${trimmed}` : trimmed;
  }

  // Unexpected format — return as-is
  return trimmed;
}
