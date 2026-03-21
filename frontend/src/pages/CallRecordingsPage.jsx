import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert, Avatar, Box, Button, Card, CardContent, Chip, Collapse,
    Grid, IconButton, InputAdornment, LinearProgress, Pagination,
    Skeleton, Table, TableBody, TableCell, TableContainer, TableHead,
    TableRow, TextField, Tooltip, Typography,
} from '@mui/material';
import { CloudUpload, ExpandLess, ExpandMore, GraphicEq, PlayArrow, Search, Sync } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import { shortDateTime, relativeTime } from '../lib/formatDate';
import { resolveMediaUrl } from '../lib/mediaUrl';
import useDebounce from '../lib/useDebounce';

const PAGE_SIZE = 20;

function recordingProgressPercent(row) {
    const status = String(row?.transcript_status || '').toLowerCase();
    const fallback = status === 'completed' ? 100 : 0;
    const parsed = Number(row?.transcript_progress_percent ?? fallback);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(0, Math.min(100, Math.round(parsed)));
}

function formatProgressStage(stage) {
    const value = String(stage || '').trim().toLowerCase().replace(/_/g, ' ');
    if (!value) return '';
    return value.charAt(0).toUpperCase() + value.slice(1);
}

const TRANSCRIPT_STATUS_CONFIG = {
    completed: { color: '#10b981', label: 'Done' },
    processing: { color: '#3b82f6', label: 'Processing' },
    failed: { color: '#ef4444', label: 'Failed' },
    none: { color: '#94a3b8', label: 'None' },
};

function TranscriptStatusCell({ row }) {
    const status = String(row?.transcript_status || '').toLowerCase();
    const cfg = TRANSCRIPT_STATUS_CONFIG[status] || TRANSCRIPT_STATUS_CONFIG.none;
    const pct = recordingProgressPercent(row);

    return (
        <Box>
            <Chip label={cfg.label} size="small"
                sx={{ bgcolor: `${cfg.color}15`, color: cfg.color, fontSize: '0.65rem', fontWeight: 600, mb: (status === 'processing' || status === 'completed') ? 0.5 : 0 }} />
            {(status === 'processing' || status === 'completed') && (
                <Box sx={{ minWidth: 100 }}>
                    <LinearProgress variant="determinate" value={pct}
                        sx={{ height: 4, borderRadius: 2, bgcolor: `${cfg.color}15`, '& .MuiLinearProgress-bar': { bgcolor: cfg.color, borderRadius: 2 } }} />
                    <Typography fontSize="0.62rem" color="text.secondary" sx={{ mt: 0.2 }}>
                        {pct}%{formatProgressStage(row.transcript_progress_stage) ? ` · ${formatProgressStage(row.transcript_progress_stage)}` : ''}
                    </Typography>
                </Box>
            )}
        </Box>
    );
}

export default function CallRecordingsPage() {
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [uploadOpen, setUploadOpen] = useState(false);
    const [rows, setRows] = useState([]);
    const [count, setCount] = useState(0);
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState('');
    const debouncedSearch = useDebounce(search, 300);
    const [sourceFilter, setSourceFilter] = useState('');
    const [audioFile, setAudioFile] = useState(null);
    const [uploadTitle, setUploadTitle] = useState('');
    const totalPages = useMemo(() => Math.max(1, Math.ceil((count || 0) / PAGE_SIZE)), [count]);
    const pollErrorCount = useRef(0);

    const fetchRecordings = async ({ syncExotel = false, silent = false } = {}) => {
        if (!silent) setLoading(true);
        if (syncExotel) setSyncing(true);
        try {
            let url = `/recordings/?page=${page}&page_size=${PAGE_SIZE}&sync_exotel=${syncExotel ? 1 : 0}`;
            if (debouncedSearch.trim()) url += `&search=${encodeURIComponent(debouncedSearch.trim())}`;
            if (sourceFilter) url += `&source=${encodeURIComponent(sourceFilter)}`;
            const { data } = await api.get(url);
            setRows(Array.isArray(data?.results) ? data.results : []);
            setCount(Number(data?.count || 0));
            pollErrorCount.current = 0;
            if (syncExotel) toast.success(`Exotel refreshed (${data?.sync?.processed_calls || 0} checked)`);
        } catch (error) {
            pollErrorCount.current += 1;
            if (!silent) toast.error(error?.response?.data?.error || 'Failed to load recordings');
        } finally {
            if (!silent) setLoading(false);
            if (syncExotel) setSyncing(false);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => fetchRecordings({ syncExotel: false }), 350);
        return () => clearTimeout(timer);
    }, [page, sourceFilter, debouncedSearch]);

    useEffect(() => {
        if (!rows.some((row) => String(row?.transcript_status || '').toLowerCase() === 'processing')) return undefined;
        const interval = setInterval(() => {
            if (pollErrorCount.current >= 5) { clearInterval(interval); return; }
            fetchRecordings({ syncExotel: false, silent: true });
        }, 5000);
        return () => clearInterval(interval);
    }, [rows]);

    const handleUpload = async () => {
        if (!audioFile) { toast.error('Select an audio file first'); return; }
        const formData = new FormData();
        formData.append('file', audioFile);
        if (uploadTitle.trim()) formData.append('title', uploadTitle.trim());
        setUploading(true);
        try {
            const { data } = await api.post('/recordings/upload/', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
            toast.success(data?.queued === false ? 'Uploaded (transcription queue failed)' : 'Recording uploaded — transcription started');
            setAudioFile(null);
            setUploadTitle('');
            setUploadOpen(false);
            setPage(1);
            fetchRecordings({ syncExotel: false, silent: true });
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Upload failed');
        } finally { setUploading(false); }
    };

    const sources = [
        { value: '', label: 'All Sources' },
        { value: 'exotel', label: 'Exotel' },
        { value: 'upload', label: 'Upload' },
    ];

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Recordings</Typography>
                    <Typography color="text.secondary" variant="body2">{count.toLocaleString()} recordings · Exotel + uploads</Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button variant="outlined" startIcon={<CloudUpload />} endIcon={uploadOpen ? <ExpandLess /> : <ExpandMore />}
                        onClick={() => setUploadOpen((v) => !v)} sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}>
                        Upload Recording
                    </Button>
                    <Tooltip title="Fetch latest recordings from Exotel"><span>
                        <Button variant="outlined" startIcon={<Sync />} onClick={() => fetchRecordings({ syncExotel: true })} disabled={syncing}
                            sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}>
                            {syncing ? 'Syncing...' : 'Sync Exotel'}
                        </Button>
                    </span></Tooltip>
                </Box>
            </Box>

            {/* Collapsible upload panel */}
            <Collapse in={uploadOpen}>
                <Card sx={{ mb: 2, border: '1px solid rgba(1,66,162,0.1)' }}>
                    <CardContent>
                        <Grid container spacing={2} alignItems="center">
                            <Grid item xs={12} md={4}>
                                <TextField fullWidth size="small" label="Title (optional)" value={uploadTitle}
                                    onChange={(e) => setUploadTitle(e.target.value)} placeholder="Demo discovery call" />
                            </Grid>
                            <Grid item xs={12} md={5}>
                                <TextField fullWidth size="small" type="file"
                                    inputProps={{ accept: '.mp3,.wav,.ogg,.m4a,audio/*' }}
                                    onChange={(e) => setAudioFile(e.target.files?.[0] || null)} />
                            </Grid>
                            <Grid item xs={12} md={3}>
                                <Button fullWidth variant="contained" startIcon={<CloudUpload />}
                                    onClick={handleUpload} disabled={uploading || !audioFile}
                                    sx={{ bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' } }}>
                                    {uploading ? 'Uploading...' : 'Upload'}
                                </Button>
                            </Grid>
                        </Grid>
                    </CardContent>
                </Card>
            </Collapse>

            {/* Filters */}
            <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                <TextField size="small" placeholder="Search recording, contact, UUID..."
                    value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                    InputProps={{ startAdornment: <InputAdornment position="start"><Search sx={{ color: '#94a3b8', fontSize: 18 }} /></InputAdornment> }}
                    sx={{ width: 300 }} />
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                    {sources.map((s) => {
                        const isActive = sourceFilter === s.value;
                        return (
                            <Chip key={s.value} label={s.label} onClick={() => { setSourceFilter(s.value); setPage(1); }}
                                sx={{ fontWeight: isActive ? 700 : 500, bgcolor: isActive ? 'rgba(1,66,162,0.15)' : 'transparent',
                                    color: isActive ? '#1a5bc4' : '#94a3b8', border: `1px solid ${isActive ? '#0142a2' : 'rgba(1,66,162,0.1)'}`, cursor: 'pointer' }} />
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
                                <TableCell>Recording</TableCell>
                                <TableCell>Source</TableCell>
                                <TableCell>Contact</TableCell>
                                <TableCell>Duration</TableCell>
                                <TableCell>Transcript</TableCell>
                                <TableCell>Created</TableCell>
                                <TableCell>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {loading ? Array.from({ length: 6 }).map((_, i) => (
                                <TableRow key={i}>{Array.from({ length: 7 }).map((_, j) => <TableCell key={j}><Skeleton /></TableCell>)}</TableRow>
                            )) : rows.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={7} align="center" sx={{ py: 6 }}>
                                        <GraphicEq sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                        <Typography color="text.secondary">
                                            {debouncedSearch || sourceFilter ? 'No recordings match your filters' : 'No recordings yet. Upload a recording or sync from Exotel to get started.'}
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            ) : null}
                            {!loading && rows.map((row) => {
                                const sourceColor = row.source === 'upload' ? '#10b981' : '#1a5bc4';
                                return (
                                    <TableRow key={row.public_id} hover sx={{ cursor: 'pointer', transition: 'background 0.1s' }}
                                        onClick={() => navigate(`/recordings/${row.public_id}/transcript`)}>
                                        <TableCell>
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                <Avatar sx={{ width: 32, height: 32, bgcolor: `${sourceColor}15`, color: sourceColor }}>
                                                    <GraphicEq sx={{ fontSize: 16 }} />
                                                </Avatar>
                                                <Box>
                                                    <Typography fontWeight={600} fontSize="0.85rem" noWrap maxWidth={200}>{row.title}</Typography>
                                                    <Typography fontSize="0.68rem" color="text.secondary" noWrap maxWidth={200}>
                                                        {row.provider_call_uuid || row.public_id}
                                                    </Typography>
                                                </Box>
                                            </Box>
                                        </TableCell>
                                        <TableCell>
                                            <Chip size="small" label={row.source}
                                                sx={{ bgcolor: `${sourceColor}15`, color: sourceColor, fontSize: '0.65rem', fontWeight: 600 }} />
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.85rem">{row.contact_name || '—'}</Typography>
                                            <Typography fontSize="0.7rem" color="text.secondary" fontFamily="monospace">{row.contact_phone || ''}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.85rem" fontFamily="monospace">{row.duration_formatted || '-'}</Typography>
                                        </TableCell>
                                        <TableCell><TranscriptStatusCell row={row} /></TableCell>
                                        <TableCell><Typography fontSize="0.72rem" color="text.secondary">{relativeTime(row.created_at)}</Typography></TableCell>
                                        <TableCell>
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }} onClick={(e) => e.stopPropagation()}>
                                                {row.audio_url ? (
                                                    <audio controls preload="none" src={resolveMediaUrl(row.audio_url)} style={{ width: 140, height: 28 }} />
                                                ) : (
                                                    <Typography fontSize="0.72rem" color="text.disabled">No audio</Typography>
                                                )}
                                                <Button size="small" variant="text"
                                                    onClick={() => navigate(`/recordings/${row.public_id}/transcript`)}
                                                    sx={{ textTransform: 'none', fontWeight: 700, minWidth: 0, px: 1, color: '#0142a2', fontSize: '0.75rem' }}>
                                                    View
                                                </Button>
                                            </Box>
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
                            Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, count)} of {count}
                        </Typography>
                        <Pagination count={totalPages} page={page} onChange={(_, v) => setPage(v)} />
                    </Box>
                )}
            </Card>
        </Box>
    );
}
