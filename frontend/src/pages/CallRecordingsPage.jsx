import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    FormControl,
    Grid,
    InputAdornment,
    InputLabel,
    LinearProgress,
    MenuItem,
    Pagination,
    Select,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from '@mui/material';
import { CloudUpload, Search, Sync } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';

const PAGE_SIZE = 20;

function formatDate(value) {
    if (!value) return '-';
    try {
        return new Date(value).toLocaleString();
    } catch (_error) {
        return '-';
    }
}

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

export default function CallRecordingsPage() {
    const navigate = useNavigate();
    const [loading, setLoading] = useState(true);
    const [syncing, setSyncing] = useState(false);
    const [uploading, setUploading] = useState(false);
    const [rows, setRows] = useState([]);
    const [count, setCount] = useState(0);
    const [page, setPage] = useState(1);
    const [search, setSearch] = useState('');
    const [sourceFilter, setSourceFilter] = useState('');
    const [audioFile, setAudioFile] = useState(null);
    const [uploadTitle, setUploadTitle] = useState('');
    const totalPages = useMemo(() => Math.max(1, Math.ceil((count || 0) / PAGE_SIZE)), [count]);

    const fetchRecordings = async ({ syncExotel = false, silent = false } = {}) => {
        if (!silent) setLoading(true);
        if (syncExotel) setSyncing(true);
        try {
            let url = `/recordings/?page=${page}&page_size=${PAGE_SIZE}&sync_exotel=${syncExotel ? 1 : 0}`;
            if (search.trim()) url += `&search=${encodeURIComponent(search.trim())}`;
            if (sourceFilter) url += `&source=${encodeURIComponent(sourceFilter)}`;
            const { data } = await api.get(url);
            setRows(Array.isArray(data?.results) ? data.results : []);
            setCount(Number(data?.count || 0));
            if (syncExotel) {
                const processed = Number(data?.sync?.processed_calls || 0);
                toast.success(`Exotel recordings refreshed (${processed} calls checked)`);
            }
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to load recordings');
        } finally {
            if (!silent) setLoading(false);
            if (syncExotel) setSyncing(false);
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchRecordings({ syncExotel: false });
        }, 350);
        return () => clearTimeout(timer);
    }, [page, sourceFilter, search]);

    useEffect(() => {
        if (!rows.some((row) => String(row?.transcript_status || '').toLowerCase() === 'processing')) {
            return undefined;
        }
        const interval = setInterval(() => {
            fetchRecordings({ syncExotel: false, silent: true });
        }, 5000);
        return () => clearInterval(interval);
    }, [rows]);

    const handleUpload = async () => {
        if (!audioFile) {
            toast.error('Select an audio file first');
            return;
        }
        const formData = new FormData();
        formData.append('file', audioFile);
        if (uploadTitle.trim()) {
            formData.append('title', uploadTitle.trim());
        }
        setUploading(true);
        try {
            const { data } = await api.post('/recordings/upload/', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            if (data?.queued === false) {
                toast.error('Uploaded, but transcription queue failed');
            } else {
                toast.success('Recording uploaded and transcription started');
            }
            setAudioFile(null);
            setUploadTitle('');
            setPage(1);
            fetchRecordings({ syncExotel: false, silent: true });
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Upload failed');
        } finally {
            setUploading(false);
        }
    };

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Call Recordings</Typography>
                    <Typography color="text.secondary" variant="body2">
                        Exotel recordings plus uploaded audio library
                    </Typography>
                </Box>
                <Button
                    variant="outlined"
                    startIcon={<Sync />}
                    onClick={() => fetchRecordings({ syncExotel: true })}
                    disabled={syncing}
                >
                    {syncing ? 'Fetching...' : 'Fetch From Exotel'}
                </Button>
            </Box>

            <Card sx={{ mb: 2 }}>
                <CardContent>
                    <Typography variant="subtitle1" fontWeight={700} sx={{ mb: 1 }}>Upload Recording</Typography>
                    <Grid container spacing={2}>
                        <Grid item xs={12} md={4}>
                            <TextField
                                fullWidth
                                size="small"
                                label="Title (optional)"
                                value={uploadTitle}
                                onChange={(event) => setUploadTitle(event.target.value)}
                                placeholder="Demo discovery call"
                            />
                        </Grid>
                        <Grid item xs={12} md={5}>
                            <TextField
                                fullWidth
                                size="small"
                                type="file"
                                inputProps={{ accept: '.mp3,.wav,.ogg,.m4a,audio/*' }}
                                onChange={(event) => setAudioFile(event.target.files?.[0] || null)}
                            />
                        </Grid>
                        <Grid item xs={12} md={3}>
                            <Button
                                fullWidth
                                variant="contained"
                                startIcon={<CloudUpload />}
                                onClick={handleUpload}
                                disabled={uploading || !audioFile}
                            >
                                {uploading ? 'Uploading...' : 'Upload Audio'}
                            </Button>
                        </Grid>
                    </Grid>
                    <Alert severity="info" sx={{ mt: 2 }}>
                        Transcription runs automatically when recording audio is available. Use Transcript to open the synced view.
                    </Alert>
                </CardContent>
            </Card>

            <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
                <TextField
                    size="small"
                    placeholder="Search recording/contact/uuid"
                    value={search}
                    onChange={(event) => {
                        setSearch(event.target.value);
                        setPage(1);
                    }}
                    sx={{ width: 300 }}
                    InputProps={{
                        startAdornment: (
                            <InputAdornment position="start">
                                <Search sx={{ color: '#64748b', fontSize: 18 }} />
                            </InputAdornment>
                        ),
                    }}
                />
                <FormControl size="small" sx={{ width: 180 }}>
                    <InputLabel>Source</InputLabel>
                    <Select value={sourceFilter} label="Source" onChange={(event) => { setSourceFilter(event.target.value); setPage(1); }}>
                        <MenuItem value="">All</MenuItem>
                        <MenuItem value="exotel">Exotel</MenuItem>
                        <MenuItem value="upload">Upload</MenuItem>
                    </Select>
                </FormControl>
            </Box>

            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Title</TableCell>
                                <TableCell>Source</TableCell>
                                <TableCell>Contact</TableCell>
                                <TableCell>Duration</TableCell>
                                <TableCell>Transcript</TableCell>
                                <TableCell>Created</TableCell>
                                <TableCell>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {rows.map((row) => (
                                <TableRow key={row.public_id} hover>
                                    <TableCell>
                                        <Typography fontWeight={600} fontSize="0.875rem">{row.title}</Typography>
                                        <Typography fontSize="0.75rem" color="text.secondary" sx={{ wordBreak: 'break-all' }}>
                                            {row.provider_call_uuid || row.public_id}
                                        </Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Chip
                                            size="small"
                                            label={row.source}
                                            sx={{
                                                bgcolor: row.source === 'upload' ? 'rgba(16,185,129,0.2)' : 'rgba(1,66,162,0.2)',
                                                color: row.source === 'upload' ? '#10b981' : '#1a5bc4',
                                            }}
                                        />
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.85rem">{row.contact_name || '—'}</Typography>
                                        <Typography fontSize="0.75rem" color="text.secondary">{row.contact_phone || ''}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.85rem">{row.duration_formatted || '-'}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Chip
                                            size="small"
                                            label={row.transcript_status || 'none'}
                                            sx={{
                                                bgcolor: row.transcript_status === 'completed'
                                                    ? 'rgba(16,185,129,0.2)'
                                                    : row.transcript_status === 'failed'
                                                        ? 'rgba(239,68,68,0.2)'
                                                        : 'rgba(100,116,139,0.2)',
                                                color: row.transcript_status === 'completed'
                                                    ? '#10b981'
                                                    : row.transcript_status === 'failed'
                                                        ? '#ef4444'
                                                        : '#94a3b8',
                                            }}
                                        />
                                        {(String(row.transcript_status || '').toLowerCase() === 'processing'
                                            || String(row.transcript_status || '').toLowerCase() === 'completed') ? (
                                            <Box sx={{ minWidth: 120, mt: 0.75 }}>
                                                <LinearProgress
                                                    variant="determinate"
                                                    value={recordingProgressPercent(row)}
                                                    color={String(row.transcript_status || '').toLowerCase() === 'completed' ? 'success' : 'primary'}
                                                    sx={{ height: 6, borderRadius: 8 }}
                                                />
                                                <Typography fontSize="0.68rem" color="text.secondary" sx={{ mt: 0.25 }}>
                                                    {recordingProgressPercent(row)}%
                                                    {formatProgressStage(row.transcript_progress_stage)
                                                        ? ` · ${formatProgressStage(row.transcript_progress_stage)}`
                                                        : ''}
                                                </Typography>
                                            </Box>
                                        ) : null}
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.8rem">{formatDate(row.created_at)}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                            {row.audio_url ? (
                                                <audio controls preload="none" src={row.audio_url} style={{ width: 170 }} />
                                            ) : (
                                                <Typography fontSize="0.75rem" color="text.secondary">No audio</Typography>
                                            )}
                                            <Button
                                                size="small"
                                                variant="text"
                                                onClick={() => navigate(`/recordings/${row.public_id}/transcript`)}
                                                sx={{ textTransform: 'none', fontWeight: 700, minWidth: 0, px: 1 }}
                                            >
                                                Transcript
                                            </Button>
                                        </Box>
                                    </TableCell>
                                </TableRow>
                            ))}
                            {!loading && rows.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={7}>
                                        <Typography color="text.secondary" sx={{ py: 2, textAlign: 'center' }}>
                                            No recordings found.
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            ) : null}
                        </TableBody>
                    </Table>
                </TableContainer>
                {totalPages > 1 && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                        <Pagination count={totalPages} page={page} onChange={(_, value) => setPage(value)} />
                    </Box>
                )}
            </Card>
        </Box>
    );
}
