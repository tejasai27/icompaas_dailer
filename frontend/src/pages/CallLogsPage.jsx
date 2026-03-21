import React, { useEffect, useState } from 'react';
import {
    Avatar, Box, Card, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Chip, IconButton, Tooltip,
    Button, TextField, Select, MenuItem, FormControl, InputLabel,
    Pagination, InputAdornment, Skeleton
} from '@mui/material';
import { Search, Mic, Sync, Phone, PlayArrow } from '@mui/icons-material';
import api from '../services/api';
import toast from 'react-hot-toast';
import { CALL_STATUS_COLORS as CALL_COLORS, normalizeCallStatus, formatCallStatus } from '../lib/callStatus';
import { shortDateTime, relativeTime } from '../lib/formatDate';
import { resolveMediaUrl } from '../lib/mediaUrl';
import useDebounce from '../lib/useDebounce';
import CallDetailDialog from '../components/CallDetailDialog';

const normalizeHubspotSyncStatus = (status) => String(status || '').trim().toLowerCase().replace(/_/g, '-');
const isHubspotSynced = (log) => {
    const status = normalizeHubspotSyncStatus(log?.hubspot_sync_status);
    if (['success', 'synced', 'completed', 'ok'].includes(status)) return true;
    if (String(log?.hubspot_task_object_id || '').trim()) return true;
    if (String(log?.hubspot_call_object_id || '').trim()) return true;
    return false;
};

const STATUS_FILTERS = ['answered', 'sdr-cut', 'no-answer', 'busy', 'failed', 'completed', 'cancelled'];
const PAGE_SIZE = 20;

export default function CallLogsPage() {
    const [logs, setLogs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const debouncedSearch = useDebounce(search, 300);
    const [statusFilter, setStatusFilter] = useState('');
    const [selected, setSelected] = useState(null);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [totalCount, setTotalCount] = useState(0);
    const [syncing, setSyncing] = useState(false);

    const fetchLogs = async () => {
        setLoading(true);
        try {
            let url = `/call-logs/?ordering=-initiated_at&page=${page}`;
            if (statusFilter) url += `&status=${statusFilter}`;
            if (debouncedSearch) url += `&search=${debouncedSearch}`;
            const { data } = await api.get(url);
            setLogs(data.results || data);
            const cnt = data.count || (data.results || data).length;
            setTotalCount(cnt);
            setTotalPages(Math.ceil(cnt / PAGE_SIZE));
        } catch (e) {
            toast.error('Failed to load call logs');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchLogs(); }, [page, statusFilter, debouncedSearch]);

    const triggerTranscription = async (id) => {
        try {
            const { data } = await api.post(`/call-logs/${id}/trigger_transcription/`);
            if (data?.queued === false) toast.error(data?.error || 'Transcription unavailable');
            else toast.success('Transcription started');
            fetchLogs();
        } catch (e) { toast.error(e?.response?.data?.error || 'Failed'); }
    };

    const syncFromExotel = async () => {
        setSyncing(true);
        try {
            const { data } = await api.post('/call-logs/sync/exotel/', { limit: 100, only_open: false });
            toast.success(`Sync complete. Updated: ${data?.updated || 0}`);
            fetchLogs();
        } catch (e) { toast.error(e.response?.data?.error || 'Sync failed'); }
        finally { setSyncing(false); }
    };

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Call Logs</Typography>
                    <Typography color="text.secondary" variant="body2">
                        {totalCount.toLocaleString()} calls · Complete dialer history
                    </Typography>
                </Box>
                <Tooltip title="Fetch latest call status and recordings from Exotel">
                    <span>
                        <Button variant="outlined" startIcon={<Sync />} onClick={syncFromExotel} disabled={syncing}
                            sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}>
                            {syncing ? 'Syncing...' : 'Sync Exotel'}
                        </Button>
                    </span>
                </Tooltip>
            </Box>

            {/* Filters */}
            <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                <TextField
                    placeholder="Search contacts, phones, campaigns..."
                    value={search}
                    onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                    size="small"
                    InputProps={{ startAdornment: <InputAdornment position="start"><Search sx={{ color: '#94a3b8', fontSize: 18 }} /></InputAdornment> }}
                    sx={{ width: 300 }}
                />
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                    <Chip label="All" onClick={() => { setStatusFilter(''); setPage(1); }}
                        sx={{ fontWeight: !statusFilter ? 700 : 500, bgcolor: !statusFilter ? 'rgba(1,66,162,0.15)' : 'transparent', color: !statusFilter ? '#1a5bc4' : '#94a3b8', border: `1px solid ${!statusFilter ? '#0142a2' : 'rgba(1,66,162,0.15)'}`, cursor: 'pointer' }} />
                    {STATUS_FILTERS.map((s) => {
                        const isActive = statusFilter === s;
                        const color = CALL_COLORS[s] || '#64748b';
                        return (
                            <Chip key={s} label={formatCallStatus(s)} onClick={() => { setStatusFilter(isActive ? '' : s); setPage(1); }}
                                sx={{ fontWeight: isActive ? 700 : 500, bgcolor: isActive ? `${color}15` : 'transparent', color: isActive ? color : '#94a3b8', border: `1px solid ${isActive ? color : 'rgba(1,66,162,0.1)'}`, cursor: 'pointer', '&:hover': { bgcolor: `${color}08` } }} />
                        );
                    })}
                </Box>
            </Box>

            {/* Table */}
            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Contact</TableCell>
                                <TableCell>Campaign</TableCell>
                                <TableCell>SDR</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Duration</TableCell>
                                <TableCell>HubSpot</TableCell>
                                <TableCell>Recording</TableCell>
                                <TableCell>Transcript</TableCell>
                                <TableCell>Time</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {loading ? Array.from({ length: 8 }).map((_, i) => (
                                <TableRow key={i}>{Array.from({ length: 9 }).map((_, j) => <TableCell key={j}><Skeleton /></TableCell>)}</TableRow>
                            )) : logs.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={9} align="center" sx={{ py: 6 }}>
                                        <Phone sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                        <Typography color="text.secondary">
                                            {debouncedSearch || statusFilter ? 'No calls match your filters. Try adjusting your search or status filter.' : 'No call logs yet'}
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            ) : null}
                            {!loading && logs.map((log) => {
                                const statusKey = normalizeCallStatus(log.status);
                                const statusColor = CALL_COLORS[statusKey] || '#64748b';
                                const hubspotSynced = isHubspotSynced(log);
                                return (
                                    <TableRow key={log.id} hover onClick={() => setSelected(log)}
                                        sx={{ cursor: 'pointer', borderLeft: `3px solid ${statusColor}`, transition: 'background 0.1s' }}>
                                        <TableCell>
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                <Avatar sx={{ width: 28, height: 28, fontSize: '0.7rem', bgcolor: `${statusColor}20`, color: statusColor }}>
                                                    {(log.contact_name || '?')[0]}
                                                </Avatar>
                                                <Box>
                                                    <Typography fontWeight={600} fontSize="0.85rem">{log.contact_name}</Typography>
                                                    <Typography fontSize="0.72rem" color="text.secondary" fontFamily="monospace">{log.contact_phone}</Typography>
                                                </Box>
                                            </Box>
                                        </TableCell>
                                        <TableCell><Typography fontSize="0.85rem" noWrap maxWidth={120}>{log.campaign_name}</Typography></TableCell>
                                        <TableCell><Typography fontSize="0.85rem">{log.agent_name}</Typography></TableCell>
                                        <TableCell>
                                            <Chip label={formatCallStatus(log.status)} size="small"
                                                sx={{ bgcolor: `${statusColor}15`, color: statusColor, fontSize: '0.65rem', fontWeight: 600 }} />
                                        </TableCell>
                                        <TableCell><Typography fontSize="0.85rem" fontFamily="monospace">{log.duration_formatted}</Typography></TableCell>
                                        <TableCell>
                                            <Chip
                                                label={hubspotSynced ? 'Synced' : 'Not Synced'}
                                                size="small"
                                                sx={{
                                                    bgcolor: hubspotSynced ? '#10b98115' : '#ef444415',
                                                    color: hubspotSynced ? '#10b981' : '#ef4444',
                                                    fontSize: '0.6rem',
                                                    fontWeight: 600,
                                                    height: 20,
                                                }}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            {log.recording_url ? (
                                                <Tooltip title="Play recording">
                                                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); window.open(resolveMediaUrl(log.recording_url), '_blank', 'noopener,noreferrer'); }}
                                                        sx={{ color: '#0142a2' }}>
                                                        <PlayArrow sx={{ fontSize: 18 }} />
                                                    </IconButton>
                                                </Tooltip>
                                            ) : <Typography fontSize="0.72rem" color="text.disabled">—</Typography>}
                                        </TableCell>
                                        <TableCell>
                                            {log.transcript_status === 'completed' ? (
                                                <Chip label="Done" size="small" sx={{ bgcolor: '#10b98115', color: '#10b981', fontSize: '0.6rem', fontWeight: 600 }} />
                                            ) : log.transcript_status === 'failed' ? (
                                                <Tooltip title={log.transcript_error || 'Failed'}>
                                                    <Chip label="Failed" size="small" sx={{ bgcolor: '#ef444415', color: '#ef4444', fontSize: '0.6rem' }} />
                                                </Tooltip>
                                            ) : log.recording_url && log.transcript_status !== 'processing' ? (
                                                <Tooltip title="Generate transcript from recording">
                                                    <Button size="small" variant="text"
                                                        startIcon={<Mic sx={{ fontSize: 14 }} />}
                                                        onClick={(e) => { e.stopPropagation(); triggerTranscription(log.id); }}
                                                        sx={{ textTransform: 'none', fontSize: '0.7rem', color: '#0142a2', minWidth: 0, px: 0.75 }}>
                                                        Transcribe
                                                    </Button>
                                                </Tooltip>
                                            ) : log.transcript_status === 'processing' ? (
                                                <Chip label="Processing" size="small" sx={{ bgcolor: '#f59e0b15', color: '#f59e0b', fontSize: '0.6rem' }} />
                                            ) : <Typography fontSize="0.72rem" color="text.disabled">—</Typography>}
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.72rem" color="text.secondary">{relativeTime(log.initiated_at)}</Typography>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </TableContainer>
                {totalPages > 1 && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 2, p: 2 }}>
                        <Typography variant="caption" color="text.secondary">
                            Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, totalCount)} of {totalCount}
                        </Typography>
                        <Pagination count={totalPages} page={page} onChange={(_, v) => setPage(v)}
                            sx={{ '& .MuiPaginationItem-root': { color: '#94a3b8' }, '& .Mui-selected': { bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' } }} />
                    </Box>
                )}
            </Card>

            <CallDetailDialog
                call={selected} onClose={() => setSelected(null)}
                extraFields={selected ? [
                    { label: 'Campaign', value: selected.campaign_name || '-' },
                    { label: 'Outcome', value: selected.call_outcome || '-' },
                    { label: 'Deal ID', value: selected.deal_id || '-' },
                    { label: 'Deal Name', value: selected.deal_name || '-' },
                    { label: 'HubSpot Sync', value: isHubspotSynced(selected) ? 'Yes' : 'No' },
                    { label: 'HubSpot Status', value: selected.hubspot_sync_status || '-' },
                    { label: 'HubSpot Task ID', value: selected.hubspot_task_object_id || '-' },
                ] : undefined}
            />
        </Box>
    );
}
