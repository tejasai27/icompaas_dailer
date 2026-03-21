import { useEffect, useRef } from 'react';

/**
 * Like setInterval but pauses when the tab is hidden.
 * Resumes and fires immediately when the tab becomes visible again.
 *
 * @param {Function} callback - function to call on each interval
 * @param {number|null} delay - interval in ms, or null to disable
 */
export default function useVisibleInterval(callback, delay) {
    const savedCallback = useRef(callback);

    useEffect(() => {
        savedCallback.current = callback;
    }, [callback]);

    useEffect(() => {
        if (delay === null || delay === undefined) return undefined;

        let intervalId = null;

        function start() {
            stop();
            intervalId = setInterval(() => savedCallback.current(), delay);
        }

        function stop() {
            if (intervalId !== null) {
                clearInterval(intervalId);
                intervalId = null;
            }
        }

        function handleVisibility() {
            if (document.hidden) {
                stop();
            } else {
                savedCallback.current(); // Fire immediately on return
                start();
            }
        }

        // Start polling if tab is visible
        if (!document.hidden) {
            start();
        }

        document.addEventListener('visibilitychange', handleVisibility);

        return () => {
            stop();
            document.removeEventListener('visibilitychange', handleVisibility);
        };
    }, [delay]);
}
