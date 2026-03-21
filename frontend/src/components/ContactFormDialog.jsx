import React from 'react';
import {
    Button, Dialog, DialogTitle, DialogContent, DialogActions,
    Grid, TextField,
} from '@mui/material';

const PHONE_E164_RE = /^\+[1-9]\d{6,14}$/;

function validatePhone(value) {
    const trimmed = (value || '').trim();
    if (!trimmed) return 'Phone is required';
    if (!PHONE_E164_RE.test(trimmed)) return 'Use E.164 format (e.g. +919999999999)';
    return '';
}

function validateEmail(value) {
    const trimmed = (value || '').trim();
    if (!trimmed) return ''; // optional
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) return 'Invalid email format';
    return '';
}

/**
 * Reusable dialog for creating or editing a contact.
 */
export default function ContactFormDialog({
    open,
    onClose,
    title,
    form,
    onChange,
    onSubmit,
    submitting,
    submitLabel = 'Save',
}) {
    const nameError = form.full_name && !form.full_name.trim() ? 'Name is required' : '';
    const phoneError = form.phone_e164 ? validatePhone(form.phone_e164) : '';
    const emailError = validateEmail(form.email);

    const canSubmit = !submitting
        && form.full_name.trim()
        && !validatePhone(form.phone_e164)
        && !emailError;

    return (
        <Dialog
            open={open}
            onClose={() => !submitting && onClose()}
            fullWidth
            maxWidth="sm"
            PaperProps={{ sx: { bgcolor: '#f0f4f9', border: '1px solid rgba(1,66,162,0.2)' } }}
        >
            <DialogTitle>{title}</DialogTitle>
            <DialogContent>
                <Grid container spacing={2} sx={{ mt: 0.5 }}>
                    <Grid item xs={12}>
                        <TextField
                            fullWidth
                            required
                            label="Full Name"
                            value={form.full_name}
                            onChange={(e) => onChange({ ...form, full_name: e.target.value })}
                            error={Boolean(nameError)}
                            helperText={nameError}
                        />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                        <TextField
                            fullWidth
                            required
                            label="Phone (E.164)"
                            placeholder="+9199XXXXXXXX"
                            value={form.phone_e164}
                            onChange={(e) => onChange({ ...form, phone_e164: e.target.value })}
                            error={Boolean(phoneError)}
                            helperText={phoneError}
                        />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                        <TextField
                            fullWidth
                            label="Email"
                            value={form.email}
                            onChange={(e) => onChange({ ...form, email: e.target.value })}
                            error={Boolean(emailError)}
                            helperText={emailError}
                        />
                    </Grid>
                    <Grid item xs={12}>
                        <TextField
                            fullWidth
                            label="Company"
                            value={form.company_name}
                            onChange={(e) => onChange({ ...form, company_name: e.target.value })}
                        />
                    </Grid>
                </Grid>
            </DialogContent>
            <DialogActions sx={{ px: 3, pb: 2 }}>
                <Button onClick={onClose} disabled={submitting}>
                    Cancel
                </Button>
                <Button
                    variant="contained"
                    onClick={onSubmit}
                    disabled={!canSubmit}
                    sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                >
                    {submitting ? `${submitLabel}...` : submitLabel}
                </Button>
            </DialogActions>
        </Dialog>
    );
}
