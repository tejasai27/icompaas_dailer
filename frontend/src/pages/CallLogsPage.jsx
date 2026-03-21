import React, { useEffect, useState } from 'react';
import {
    Box, Card, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Chip, IconButton, Tooltip,
    Button, TextField, Select, MenuItem, FormControl, InputLabel,
    Pagination, InputAdornment, Skeleton
} from '@mui/material';
import { Search, Mic, Sync } from '@mui/icons-material';
import api from '../services/api';
import toast from 'react-hot-toast';
import { CALL_STATUS_COLORS as CALL_COLORS, normalizeCallStatus, formatCallStatus } from '../lib/callStatus';
import CallDetailDialog from '../components/CallDetailDialog';
const normalizeHubspotSyncStatus = (status) => String(status || '').trim().toLowerCase().replace(/_/g, '-');
const isHubspotSynced = (log) => {
    const status = normalizeHubspotSyncStatus(log?.hubspot_sync_status);
    if (['success', 'synced', 'completed', 'ok'].includes(status)) return true;
    if (String(log?.hubspot_task_object_id || '').trim()) return true;
    if (String(log?.hubspot_call_object_id || '').trim()) return true;
    return false;
};

export default function CallLogsPage() {
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('');
    const [selected, setSelected] = useState(null);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [syncing, setSyncing] = useState(false);
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
            const { data } = await api.post(`/call-logs/${id}/trigger_transcription/`);
            if (data?.queued === false) {
                toast.error(data?.error || 'Transcription queue unavailable');
            } else {
                toast.success('Transcription started');
            }
            fetchLogs();
        } catch (e) { toast.error(e?.response?.data?.error || 'Failed'); }
    };

    const syncFromExotel = async () => {
        setSyncing(true);
        try {
            const { data } = await api.post('/call-logs/sync/exotel/', { limit: 100, only_open: false });
            const updated = Number(data?.updated || 0);
            const failed = Number(data?.failed_count || 0);
            toast.success(`Exotel sync complete. Updated: ${updated}${failed ? `, Failed: ${failed}` : ''}`);
            fetchLogs();
        } catch (e) {
            toast.error(e.response?.data?.error || 'Exotel sync failed');
        } finally {
            setSyncing(false);
        }
    };

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Call Logs</Typography>
                    <Typography color="text.secondary" variant="body2">Complete history of all dialer calls</Typography>
                </Box>
                <Button
                    variant="outlined"
                    startIcon={<Sync />}
                    onClick={syncFromExotel}
                    disabled={syncing}
                    sx={{ borderColor: 'rgba(1,66,162,0.4)', color: '#1a5bc4' }}
                >
                    {syncing ? 'Syncing...' : 'Sync Exotel'}
                </Button>
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
                        {['answered', 'sdr-cut', 'no-answer', 'busy', 'failed', 'completed', 'cancelled'].map(s => (
                            <MenuItem key={s} value={s}>{formatCallStatus(s)}</MenuItem>
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
                                <TableCell>SDR</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Duration</TableCell>
                                <TableCell>HubSpot Sync</TableCell>
                                <TableCell>Recording</TableCell>
                                <TableCell>Transcript</TableCell>
                                <TableCell>Date/Time</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {loading ? Array.from({ length: 5 }).map((_, i) => (
                                <TableRow key={i}>
                                    {Array.from({ length: 10 }).map((_, j) => (
                                        <TableCell key={j}><Skeleton /></TableCell>
                                    ))}
                                </TableRow>
                            )) : logs.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={10} align="center" sx={{ py: 4, color: '#64748b' }}>
                                        No call logs found
                                    </TableCell>
                                </TableRow>
                            ) : null}
                            {!loading && logs.map(log => {
                                const statusKey = normalizeCallStatus(log.status);
                                const hubspotSynced = isHubspotSynced(log);
                                return (
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
                                        <Chip label={formatCallStatus(log.status)} size="small"
                                            sx={{ bgcolor: `${CALL_COLORS[statusKey] || '#64748b'}25`, color: CALL_COLORS[statusKey] || '#94a3b8', fontSize: '0.7rem' }} />
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem" fontFamily="monospace">{log.duration_formatted}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Chip
                                            label={hubspotSynced ? 'Yes' : 'No'}
                                            size="small"
                                            sx={{
                                                bgcolor: hubspotSynced ? '#10b98125' : '#ef444425',
                                                color: hubspotSynced ? '#10b981' : '#ef4444',
                                                fontSize: '0.7rem',
                                                fontWeight: 600,
                                            }}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        {log.recording_url ? (
                                            <Button
                                                size="small"
                                                variant="text"
                                                onClick={e => {
                                                    e.stopPropagation();
                                                    window.open(log.recording_url, '_blank', 'noopener,noreferrer');
                                                }}
                                                sx={{ textTransform: 'none', fontWeight: 700, minWidth: 0, px: 1, color: '#0142a2' }}
                                            >
                                                Recording
                                            </Button>
                                        ) : <Typography fontSize="0.75rem" color="text.disabled">—</Typography>}
                                    </TableCell>
                                    <TableCell>
                                        {log.transcript_status === 'completed' ? (
                                            <Chip label="Done" size="small"
                                                sx={{ bgcolor: '#10b98120', color: '#10b981', fontSize: '0.65rem' }} />
                                        ) : log.transcript_status === 'failed' ? (
                                            <Tooltip title={log.transcript_error || 'Transcription failed'}>
                                                <Chip label="Failed" size="small"
                                                    sx={{ bgcolor: '#ef444420', color: '#ef4444', fontSize: '0.65rem' }} />
                                            </Tooltip>
                                        ) : log.recording_url && log.transcript_status !== 'processing' ? (
                                            <Tooltip title="Run Transcription">
                                                <IconButton size="small" onClick={e => { e.stopPropagation(); triggerTranscription(log.id); }}
                                                    sx={{ color: '#0142a2' }}>
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
                            )})}
                        </TableBody>
                    </Table>
                </TableContainer>
                {totalPages > 1 && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                        <Pagination count={totalPages} page={page} onChange={(_, v) => setPage(v)}
                            sx={{ '& .MuiPaginationItem-root': { color: '#94a3b8' }, '& .Mui-selected': { bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' } }} />
                    </Box>
                )}
            </Card>

            <CallDetailDialog
                call={selected}
                onClose={() => setSelected(null)}
                extraFields={selected ? [
                    { label: 'Campaign', value: selected.campaign_name || '-' },
                    { label: 'Outcome', value: selected.call_outcome || '-' },
                    { label: 'Deal ID', value: selected.deal_id || '-' },
                    { label: 'Deal Name', value: selected.deal_name || '-' },
                    { label: 'HubSpot Sync', value: isHubspotSynced(selected) ? 'Yes' : 'No' },
                    { label: 'HubSpot Sync Status', value: selected.hubspot_sync_status || '-' },
                    { label: 'HubSpot Task ID', value: selected.hubspot_task_object_id || '-' },
                ] : undefined}
            />
        </Box>
    );
}
