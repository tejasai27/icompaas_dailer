import { useEffect, useState } from 'react';

/**
 * Debounce a value. Returns the debounced value that updates
 * only after `delay` ms of inactivity.
 *
 * Usage:
 *   const [search, setSearch] = useState('');
 *   const debouncedSearch = useDebounce(search, 300);
 *
 *   useEffect(() => {
 *       fetchResults(debouncedSearch);
 *   }, [debouncedSearch]);
 *
 * @param {*} value - the value to debounce
 * @param {number} delay - debounce delay in ms (default 300)
 */
export default function useDebounce(value, delay = 300) {
    const [debounced, setDebounced] = useState(value);

    useEffect(() => {
        const timer = setTimeout(() => setDebounced(value), delay);
        return () => clearTimeout(timer);
    }, [value, delay]);

    return debounced;
}
