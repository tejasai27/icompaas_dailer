const CALL_LOG_KEY = "icompaas_dialer_call_log";

export function readCallLog() {
  try {
    const raw = window.localStorage.getItem(CALL_LOG_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function writeCallLog(entries) {
  const safeEntries = Array.isArray(entries) ? entries.slice(0, 200) : [];
  window.localStorage.setItem(CALL_LOG_KEY, JSON.stringify(safeEntries));
}

export function appendCallLog(entry) {
  const current = readCallLog();
  const next = [entry, ...current].slice(0, 200);
  writeCallLog(next);
  return next;
}
