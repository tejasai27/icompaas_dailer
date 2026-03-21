/**
 * Centralized date/time formatting utilities.
 *
 * All functions accept a date string, Date object, or timestamp.
 * Returns '-' for null/undefined/invalid inputs.
 */

function toDate(value) {
    if (!value) return null;
    const d = value instanceof Date ? value : new Date(value);
    return Number.isNaN(d.getTime()) ? null : d;
}

/**
 * Relative time: "Just now", "5m ago", "2h ago", "Yesterday", "Mar 15"
 */
export function relativeTime(value) {
    const d = toDate(value);
    if (!d) return '-';

    const now = Date.now();
    const diffMs = now - d.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffSec < 60) return 'Just now';
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay === 1) return 'Yesterday';
    if (diffDay < 7) return `${diffDay}d ago`;

    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * Short date + time: "Mar 15, 2:30 PM"
 */
export function shortDateTime(value) {
    const d = toDate(value);
    if (!d) return '-';
    return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
    });
}

/**
 * Full date + time: "Mar 15, 2025, 2:30:45 PM"
 */
export function fullDateTime(value) {
    const d = toDate(value);
    if (!d) return '-';
    return d.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
    });
}

/**
 * Time only: "2:30 PM"
 */
export function timeOnly(value) {
    const d = toDate(value);
    if (!d) return '-';
    return d.toLocaleTimeString(undefined, {
        hour: 'numeric',
        minute: '2-digit',
    });
}

/**
 * Date only: "Mar 15, 2025"
 */
export function dateOnly(value) {
    const d = toDate(value);
    if (!d) return '-';
    return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
    });
}
