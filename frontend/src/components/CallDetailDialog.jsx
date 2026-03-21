import React from 'react';
import {
    Box, Button, Chip, Dialog, DialogTitle, DialogContent,
    DialogActions, Grid, Typography,
} from '@mui/material';
import { formatCallStatus } from '../lib/callStatus';
import { shortDateTime } from '../lib/formatDate';
import { resolveMediaUrl } from '../lib/mediaUrl';

/**
 * Dialog showing details of a single call log entry.
 *
 * Props:
 *  - call: the call/log object (null to hide)
 *  - onClose: close handler
 *  - extraFields: optional array of { label, value } to add to the info grid
 *  - children: optional extra content rendered after the default sections
 */
export default function CallDetailDialog({ call, onClose, extraFields, children }) {
    if (!call) return null;

    const baseFields = [
        { label: 'Phone', value: call.contact_phone },
        { label: 'SDR', value: call.agent_name },
        { label: 'Duration', value: call.duration_formatted },
        { label: 'Time', value: shortDateTime(call.initiated_at) },
    ];

    const allFields = extraFields ? [...baseFields, ...extraFields] : baseFields;

    return (
        <Dialog
            open={Boolean(call)}
            onClose={onClose}
            maxWidth="md"
            fullWidth
            PaperProps={{ sx: { bgcolor: '#f0f4f9', border: '1px solid rgba(1,66,162,0.2)' } }}
        >
            <DialogTitle>
                <Box>
                    <Typography fontWeight={700} component="span">
                        Call with {call.contact_name}
                    </Typography>
                    <Chip label={formatCallStatus(call.status)} size="small" sx={{ ml: 2 }} />
                </Box>
            </DialogTitle>
            <DialogContent>
                <Grid container spacing={2} sx={{ mb: 2 }}>
                    {allFields.map(({ label, value }) => (
                        <Grid item xs={6} key={label}>
                            <Typography variant="caption" color="text.secondary">{label}</Typography>
                            <Typography fontWeight={500}>{value}</Typography>
                        </Grid>
                    ))}
                </Grid>

                {call.recording_url && (
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="subtitle2" fontWeight={600} mb={1}>Recording</Typography>
                        <audio controls preload="none" src={resolveMediaUrl(call.recording_url)} style={{ width: '100%' }} />
                    </Box>
                )}

                {call.agent_notes && (
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="subtitle2" fontWeight={600} mb={1}>SDR Notes</Typography>
                        <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.05)' }}>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                                {call.agent_notes}
                            </Typography>
                        </Box>
                    </Box>
                )}

                {call.transcript && (
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="subtitle2" fontWeight={600} mb={1}>Transcript</Typography>
                        <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.05)', border: '1px solid rgba(1,66,162,0.1)', maxHeight: 300, overflow: 'auto' }}>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                                {call.transcript}
                            </Typography>
                        </Box>
                    </Box>
                )}

                {!call.transcript && call.transcript_error && (
                    <Box sx={{ mt: 2 }}>
                        <Typography variant="subtitle2" fontWeight={600} mb={1}>Transcript</Typography>
                        <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(239,68,68,0.08)' }}>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7, color: '#b91c1c' }}>
                                {call.transcript_error}
                            </Typography>
                        </Box>
                    </Box>
                )}

                {children}
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose}>Close</Button>
            </DialogActions>
        </Dialog>
    );
}
