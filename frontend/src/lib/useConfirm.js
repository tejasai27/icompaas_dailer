import React, { useCallback, useRef, useState } from 'react';
import ConfirmDialog from '../components/ConfirmDialog';

/**
 * Hook that provides an async confirm() function and a ConfirmDialog element.
 *
 * Usage:
 *   const [confirm, ConfirmEl] = useConfirm();
 *
 *   async function handleDelete() {
 *       const ok = await confirm({
 *           title: 'Delete contact?',
 *           body: 'John Doe (+919999999999) will be permanently deleted.',
 *           confirmLabel: 'Delete',
 *           confirmColor: 'error',
 *       });
 *       if (!ok) return;
 *       // proceed with delete
 *   }
 *
 *   return <>{ConfirmEl}<button onClick={handleDelete}>Delete</button></>;
 */
export default function useConfirm() {
    const [state, setState] = useState({
        open: false,
        title: '',
        body: '',
        confirmLabel: 'Confirm',
        confirmColor: 'error',
        cancelLabel: 'Cancel',
    });
    const resolveRef = useRef(null);

    const confirm = useCallback((options = {}) => {
        return new Promise((resolve) => {
            resolveRef.current = resolve;
            setState({
                open: true,
                title: options.title || 'Are you sure?',
                body: options.body || '',
                confirmLabel: options.confirmLabel || 'Confirm',
                confirmColor: options.confirmColor || 'error',
                cancelLabel: options.cancelLabel || 'Cancel',
            });
        });
    }, []);

    const handleClose = useCallback(() => {
        setState((prev) => ({ ...prev, open: false }));
        resolveRef.current?.(false);
        resolveRef.current = null;
    }, []);

    const handleConfirm = useCallback(() => {
        resolveRef.current?.(true);
        resolveRef.current = null;
    }, []);

    const element = React.createElement(ConfirmDialog, {
        open: state.open,
        onClose: handleClose,
        onConfirm: handleConfirm,
        title: state.title,
        body: state.body,
        confirmLabel: state.confirmLabel,
        confirmColor: state.confirmColor,
        cancelLabel: state.cancelLabel,
    });

    return [confirm, element];
}
