/**
 * Shared call-status colours, normalisation, and formatting.
 *
 * Import from here instead of re-declaring per page.
 */

export const CALL_STATUS_COLORS = {
    answered: '#10b981',
    'sdr-cut': '#ef4444',
    'no-answer': '#f59e0b',
    no_answer: '#f59e0b',
    busy: '#f59e0b',
    failed: '#ef4444',
    completed: '#0142a2',
    initiated: '#3b82f6',
    cancelled: '#64748b',
};

export const CAMPAIGN_STATUS_COLORS = {
    active: { bg: '#10b98125', text: '#10b981', label: 'Active' },
    paused: { bg: '#f59e0b25', text: '#f59e0b', label: 'Paused' },
    completed: { bg: '#0142a225', text: '#0142a2', label: 'Completed' },
    draft: { bg: '#64748b25', text: '#94a3b8', label: 'Draft' },
    archived: { bg: '#37415125', text: '#94a3b8', label: 'Archived' },
};

export function normalizeCallStatus(status) {
    return String(status || '').trim().toLowerCase().replace(/_/g, '-');
}

export function formatCallStatus(status) {
    const normalized = normalizeCallStatus(status);
    if (!normalized) return '-';
    if (normalized === 'sdr-cut') return 'SDR Cut the Call';
    return normalized
        .split('-')
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

export function formatSeconds(total) {
    const value = Math.max(0, Math.floor(Number(total || 0)));
    const minutes = Math.floor(value / 60);
    const seconds = value % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}
