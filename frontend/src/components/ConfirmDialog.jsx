import React from 'react';
import {
    Button, Dialog, DialogTitle, DialogContent, DialogActions,
    Typography,
} from '@mui/material';

/**
 * Styled replacement for window.confirm().
 *
 * Usage:
 *   const [confirm, ConfirmDialog] = useConfirm();
 *   const ok = await confirm({ title: 'Delete?', body: 'This cannot be undone.' });
 *   if (ok) { ... }
 *
 * Props (when used standalone):
 *   open, onClose, onConfirm, title, body, confirmLabel, confirmColor, cancelLabel
 */
export default function ConfirmDialog({
    open,
    onClose,
    onConfirm,
    title = 'Are you sure?',
    body = '',
    confirmLabel = 'Confirm',
    confirmColor = 'error',
    cancelLabel = 'Cancel',
}) {
    return (
        <Dialog
            open={open}
            onClose={onClose}
            maxWidth="xs"
            fullWidth
            PaperProps={{ sx: { borderRadius: 3, bgcolor: '#f0f4f9', border: '1px solid rgba(1,66,162,0.2)' } }}
        >
            <DialogTitle sx={{ fontWeight: 700 }}>{title}</DialogTitle>
            {body && (
                <DialogContent>
                    <Typography color="text.secondary">{body}</Typography>
                </DialogContent>
            )}
            <DialogActions sx={{ px: 3, pb: 2 }}>
                <Button onClick={onClose}>{cancelLabel}</Button>
                <Button
                    variant="contained"
                    color={confirmColor}
                    onClick={() => { onConfirm(); onClose(); }}
                >
                    {confirmLabel}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
