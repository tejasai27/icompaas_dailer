import React, { useEffect, useState } from 'react';
import {
    Box, Card, CardContent, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Chip, IconButton, Tooltip,
    Dialog, DialogTitle, DialogContent, DialogActions, Button, TextField,
    Select, MenuItem, FormControl, InputLabel, Grid, Pagination, InputAdornment
} from '@mui/material';
import { Search, Download, Mic, PlayArrow, Stop } from '@mui/icons-material';
import api from '../services/api';
import toast from 'react-hot-toast';

const CALL_COLORS = {
    answered: '#10b981', 'no-answer': '#f59e0b', busy: '#f59e0b',
    failed: '#ef4444', completed: '#6366f1', initiated: '#3b82f6', cancelled: '#64748b'
};

export default function CallLogsPage() {
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('');
    const [selected, setSelected] = useState(null);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const PAGE_SIZE = 20;

    const fetchLogs = async () => {
        setLoading(true);
        try {
            let url = `/call-logs/?ordering=-initiated_at&page=${page}`;
            if (statusFilter) url += `&status=${statusFilter}`;
            if (search) url += `&search=${search}`;
            const { data } = await api.get(url);
            setLogs(data.results || data);
            setTotalPages(Math.ceil((data.count || (data.results || data).length) / PAGE_SIZE));
        } catch (e) {
            toast.error('Failed to load call logs');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchLogs(); }, [page, statusFilter, search]);

    const triggerTranscription = async (id) => {
        try {
            await api.post(`/call-logs/${id}/trigger_transcription/`);
            toast.success('Transcription started');
            fetchLogs();
        } catch (e) { toast.error('Failed'); }
    };

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Call Logs</Typography>
                    <Typography color="text.secondary" variant="body2">Complete history of all dialer calls</Typography>
                </Box>
            </Box>

            {/* Filters */}
            <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                <TextField
                    placeholder="Search contacts, phones…"
                    value={search}
                    onChange={e => { setSearch(e.target.value); setPage(1); }}
                    size="small"
                    InputProps={{
                        startAdornment: <InputAdornment position="start"><Search sx={{ color: '#64748b', fontSize: 18 }} /></InputAdornment>
                    }}
                    sx={{ width: 280 }}
                />
                <FormControl size="small" sx={{ width: 180 }}>
                    <InputLabel>Status</InputLabel>
                    <Select value={statusFilter} label="Status" onChange={e => { setStatusFilter(e.target.value); setPage(1); }}>
                        <MenuItem value="">All</MenuItem>
                        {['answered', 'no-answer', 'busy', 'failed', 'completed', 'cancelled'].map(s => (
                            <MenuItem key={s} value={s}>{s}</MenuItem>
                        ))}
                    </Select>
                </FormControl>
            </Box>

            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Contact</TableCell>
                                <TableCell>Phone</TableCell>
                                <TableCell>Campaign</TableCell>
                                <TableCell>Agent</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Duration</TableCell>
                                <TableCell>Recording</TableCell>
                                <TableCell>Transcript</TableCell>
                                <TableCell>Date/Time</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {logs.map(log => (
                                <TableRow key={log.id} hover
                                    onClick={() => setSelected(log)}
                                    sx={{ cursor: 'pointer' }}>
                                    <TableCell>
                                        <Typography fontWeight={500} fontSize="0.875rem">{log.contact_name}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem" fontFamily="monospace">{log.contact_phone}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem" noWrap maxWidth={140}>{log.campaign_name}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem">{log.agent_name}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Chip label={log.status} size="small"
                                            sx={{ bgcolor: `${CALL_COLORS[log.status] || '#64748b'}25`, color: CALL_COLORS[log.status] || '#94a3b8', fontSize: '0.7rem' }} />
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem" fontFamily="monospace">{log.duration_formatted}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        {log.recording_url ? (
                                            <Tooltip title="Download Recording">
                                                <IconButton size="small" href={log.recording_url} target="_blank"
                                                    sx={{ color: '#6366f1' }} onClick={e => e.stopPropagation()}>
                                                    <Download fontSize="small" />
                                                </IconButton>
                                            </Tooltip>
                                        ) : <Typography fontSize="0.75rem" color="text.disabled">—</Typography>}
                                    </TableCell>
                                    <TableCell>
                                        {log.transcript_status === 'completed' ? (
                                            <Chip label="Done" size="small"
                                                sx={{ bgcolor: '#10b98120', color: '#10b981', fontSize: '0.65rem' }} />
                                        ) : log.recording_url && log.transcript_status !== 'processing' ? (
                                            <Tooltip title="Run Transcription">
                                                <IconButton size="small" onClick={e => { e.stopPropagation(); triggerTranscription(log.id); }}
                                                    sx={{ color: '#6366f1' }}>
                                                    <Mic fontSize="small" />
                                                </IconButton>
                                            </Tooltip>
                                        ) : <Typography fontSize="0.75rem" color="text.disabled">—</Typography>}
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.75rem" color="text.secondary">
                                            {new Date(log.initiated_at).toLocaleDateString()}<br />
                                            {new Date(log.initiated_at).toLocaleTimeString()}
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
                {totalPages > 1 && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                        <Pagination count={totalPages} page={page} onChange={(_, v) => setPage(v)}
                            sx={{ '& .MuiPaginationItem-root': { color: '#94a3b8' }, '& .Mui-selected': { bgcolor: 'rgba(99,102,241,0.2)', color: '#818cf8' } }} />
                    </Box>
                )}
            </Card>

            {/* Detail dialog */}
            {selected && (
                <Dialog open onClose={() => setSelected(null)} maxWidth="sm" fullWidth
                    PaperProps={{ sx: { bgcolor: '#1a1a2e', border: '1px solid rgba(99,102,241,0.2)' } }}>
                    <DialogTitle>
                        <Box>
                            <Typography fontWeight={700}>{selected.contact_name}</Typography>
                            <Typography variant="caption" color="text.secondary">{selected.contact_phone}</Typography>
                        </Box>
                    </DialogTitle>
                    <DialogContent>
                        <Grid container spacing={2} sx={{ mb: 2 }}>
                            {[
                                { label: 'Status', value: selected.status },
                                { label: 'Duration', value: selected.duration_formatted },
                                { label: 'Agent', value: selected.agent_name },
                                { label: 'Campaign', value: selected.campaign_name },
                                { label: 'Date', value: new Date(selected.initiated_at).toLocaleString() },
                            ].map(({ label, value }) => (
                                <Grid item xs={6} key={label}>
                                    <Typography variant="caption" color="text.secondary">{label}</Typography>
                                    <Typography fontWeight={500} fontSize="0.9rem">{value}</Typography>
                                </Grid>
                            ))}
                        </Grid>
                        {selected.transcript && (
                            <Box sx={{ mt: 2 }}>
                                <Typography variant="subtitle2" fontWeight={600} mb={1}>📝 Transcript</Typography>
                                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(99,102,241,0.05)', maxHeight: 300, overflow: 'auto' }}>
                                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                                        {selected.transcript}
                                    </Typography>
                                </Box>
                            </Box>
                        )}
                    </DialogContent>
                    <DialogActions>
                        <Button onClick={() => setSelected(null)}>Close</Button>
                    </DialogActions>
                </Dialog>
            )}
        </Box>
    );
}
