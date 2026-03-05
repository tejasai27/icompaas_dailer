/**
 * Resolve a media/audio URL from the backend.
 *
 * The Django backend sometimes returns a relative URL like:
 *   /media/dialer/recordings/filename.mp3
 *
 * When this is served through Docker, the browser cannot reach
 * the Django media server via a relative path (which hits port 5173).
 * We prefix it with the backend's public URL (port 8002).
 */

const BACKEND_BASE =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8002`
    : 'http://localhost:8002';

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

  // Relative path like /media/... — prefix with backend base
  if (trimmed.startsWith('/')) {
    return `${BACKEND_BASE}${trimmed}`;
  }

  // Unexpected format — return as-is
  return trimmed;
}
