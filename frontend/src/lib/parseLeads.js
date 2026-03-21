/**
 * Parse manual/separate lead text into an array of lead objects.
 * Supports "Name,+91..." or just "+91..." per line.
 */
export function parseManualLeads(text) {
    return String(text || '')
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
            const [first = '', second = ''] = line.split(',').map((value) => value.trim());
            if (second) return { full_name: first, phone_e164: second };
            return { phone_e164: first };
        });
}
