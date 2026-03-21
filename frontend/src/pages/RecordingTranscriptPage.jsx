import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert, Avatar, Box, Button, Card, CardContent, Chip, CircularProgress,
    Divider, Grid, IconButton, InputAdornment, LinearProgress, TextField,
    Tooltip, Typography,
} from '@mui/material';
import {
    ArrowBack, FastForward, FastRewind, GraphicEq, Mic, Person,
    Search, Speed,
} from '@mui/icons-material';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import { resolveMediaUrl } from '../lib/mediaUrl';
import { formatSeconds as formatTime } from '../lib/callStatus';
import { shortDateTime } from '../lib/formatDate';

function formatTranscriptStage(stage) {
    const value = String(stage || '').trim().toLowerCase().replace(/_/g, ' ');
    if (!value) return '';
    return value.charAt(0).toUpperCase() + value.slice(1);
}

const PLAYBACK_SPEEDS = [0.75, 1, 1.25, 1.5, 2];

export default function RecordingTranscriptPage() {
    const navigate = useNavigate();
    const { recordingPublicId } = useParams();
    const audioRef = useRef(null);
    const activeSegmentRef = useRef(null);

    const [loading, setLoading] = useState(true);
    const [transcribing, setTranscribing] = useState(false);
    const [trackUntilComplete, setTrackUntilComplete] = useState(false);
    const [recording, setRecording] = useState(null);
    const [currentTime, setCurrentTime] = useState(0);
    const [currentSegmentIndex, setCurrentSegmentIndex] = useState(-1);
    const [playbackSpeed, setPlaybackSpeed] = useState(1);
    const [transcriptSearch, setTranscriptSearch] = useState('');
    const pollErrorCount = useRef(0);

    const segments = useMemo(() => {
        const raw = recording?.transcript_segments;
        return Array.isArray(raw) ? raw : [];
    }, [recording?.transcript_segments]);

    const hasTranscript = Boolean((recording?.transcript_text || '').trim());
    const transcriptStatus = String(recording?.transcript_status || '').toLowerCase();
    const transcriptProgressPercent = Math.max(0, Math.min(100, Number(recording?.transcript_progress_percent ?? (transcriptStatus === 'completed' ? 100 : 0))));
    const transcriptProgressStage = formatTranscriptStage(recording?.transcript_progress_stage || transcriptStatus);

    const filteredSegments = useMemo(() => {
        if (!transcriptSearch.trim()) return segments;
        const q = transcriptSearch.toLowerCase();
        return segments.filter((s) => String(s.text || '').toLowerCase().includes(q));
    }, [segments, transcriptSearch]);

    const loadRecording = async ({ silent = false } = {}) => {
        if (!recordingPublicId) return;
        if (!silent) setLoading(true);
        try {
            const { data } = await api.get(`/recordings/${recordingPublicId}/`);
            setRecording(data?.recording || null);
            pollErrorCount.current = 0;
        } catch (error) {
            pollErrorCount.current += 1;
            if (!silent) toast.error(error?.response?.data?.error || 'Failed to load recording');
        } finally {
            if (!silent) setLoading(false);
        }
    };

    useEffect(() => { loadRecording(); }, [recordingPublicId]);

    useEffect(() => {
        if (!recordingPublicId || transcriptStatus !== 'processing') return undefined;
        const interval = setInterval(() => {
            if (pollErrorCount.current >= 5) { clearInterval(interval); return; }
            loadRecording({ silent: true });
        }, 5000);
        return () => clearInterval(interval);
    }, [recordingPublicId, transcriptStatus]);

    useEffect(() => {
        if (!transcribing || !trackUntilComplete) return;
        if (transcriptStatus && transcriptStatus !== 'processing') {
            setTranscribing(false);
            setTrackUntilComplete(false);
        }
    }, [transcriptStatus, transcribing, trackUntilComplete]);

    useEffect(() => {
        if (!segments.length) { setCurrentSegmentIndex(-1); return; }
        const index = segments.findIndex((s) => currentTime >= Number(s?.start || 0) && currentTime < Number(s?.end ?? Number(s?.start || 0) + 1));
        setCurrentSegmentIndex(index);
    }, [currentTime, segments]);

    // Auto-scroll to active segment
    useEffect(() => {
        if (activeSegmentRef.current) {
            activeSegmentRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }, [currentSegmentIndex]);

    // Playback speed
    useEffect(() => {
        if (audioRef.current) audioRef.current.playbackRate = playbackSpeed;
    }, [playbackSpeed]);

    const runTranscription = async () => {
        if (!recordingPublicId) return;
        setTranscribing(true);
        setTrackUntilComplete(false);
        try {
            const { data } = await api.post(`/recordings/${recordingPublicId}/transcribe/`, { language: 'auto' });
            setRecording(data?.recording || null);
            const nextStatus = String(data?.recording?.transcript_status || '').toLowerCase();
            if (data?.queued || nextStatus === 'processing') { toast.success('Transcription started'); setTrackUntilComplete(true); }
            else { toast.success('Transcription completed'); setTranscribing(false); }
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Transcription failed');
            setTranscribing(false);
        }
    };

    const seekToSegment = (segment) => {
        if (!audioRef.current) return;
        audioRef.current.currentTime = Number(segment?.start || 0);
        setCurrentTime(Number(segment?.start || 0));
        audioRef.current.play().catch(() => {});
    };

    const skipAudio = (seconds) => {
        if (!audioRef.current) return;
        audioRef.current.currentTime = Math.max(0, audioRef.current.currentTime + seconds);
    };

    const cycleSpeed = () => {
        const idx = PLAYBACK_SPEEDS.indexOf(playbackSpeed);
        setPlaybackSpeed(PLAYBACK_SPEEDS[(idx + 1) % PLAYBACK_SPEEDS.length]);
    };

    if (loading) return <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}><CircularProgress /></Box>;
    if (!recording) return <Alert severity="error">Recording not found</Alert>;

    const totalDuration = recording.duration_seconds || 0;

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                <IconButton onClick={() => navigate('/recordings')} sx={{ color: '#64748b' }}><ArrowBack /></IconButton>
                <Box sx={{ flex: 1 }}>
                    <Typography variant="h5" fontWeight={800}>{recording.title}</Typography>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mt: 0.5 }}>
                        {recording.contact_name && (
                            <Chip icon={<Person sx={{ fontSize: 14 }} />} label={recording.contact_name} size="small" sx={{ bgcolor: 'rgba(1,66,162,0.08)' }} />
                        )}
                        {recording.contact_phone && (
                            <Typography variant="caption" color="text.secondary" fontFamily="monospace">{recording.contact_phone}</Typography>
                        )}
                        <Chip size="small" label={recording.source}
                            sx={{ bgcolor: recording.source === 'upload' ? '#10b98115' : '#1a5bc415', color: recording.source === 'upload' ? '#10b981' : '#1a5bc4', fontWeight: 600 }} />
                        <Chip size="small" label={recording.duration_formatted || '-'} variant="outlined" sx={{ borderColor: 'rgba(1,66,162,0.2)' }} />
                        {recording.created_at && <Typography variant="caption" color="text.secondary">{shortDateTime(recording.created_at)}</Typography>}
                    </Box>
                </Box>
                <Button variant="contained" startIcon={transcribing ? <CircularProgress size={16} color="inherit" /> : <Mic />}
                    onClick={runTranscription} disabled={transcribing}
                    sx={{ bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' } }}>
                    {transcribing ? 'Transcribing...' : hasTranscript ? 'Re-generate Transcript' : 'Generate Transcript'}
                </Button>
            </Box>

            {/* Alerts */}
            {recording.transcript_error && <Alert severity="error" sx={{ mb: 1.5, borderRadius: 2 }}>{recording.transcript_error}</Alert>}
            {transcriptStatus === 'processing' && <Alert severity="info" sx={{ mb: 1.5, borderRadius: 2 }}>Transcription in progress — this page auto-refreshes.</Alert>}

            {/* Progress bar */}
            {(transcriptStatus === 'processing' || transcriptStatus === 'failed') && (
                <Box sx={{ mb: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="caption" color="text.secondary">{transcriptProgressStage || 'Processing'}</Typography>
                        <Typography variant="caption" fontWeight={700}>{transcriptProgressPercent}%</Typography>
                    </Box>
                    <LinearProgress variant="determinate" value={transcriptProgressPercent}
                        color={transcriptStatus === 'failed' ? 'error' : 'primary'}
                        sx={{ height: 6, borderRadius: 4 }} />
                </Box>
            )}

            <Grid container spacing={2}>
                {/* Audio Player + Controls (top-spanning) */}
                <Grid item xs={12}>
                    <Card sx={{ border: '1px solid rgba(1,66,162,0.08)' }}>
                        <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                                {/* Skip back */}
                                <Tooltip title="Back 15s">
                                    <IconButton size="small" onClick={() => skipAudio(-15)} sx={{ color: '#64748b' }}>
                                        <FastRewind sx={{ fontSize: 20 }} />
                                    </IconButton>
                                </Tooltip>

                                {/* Audio player */}
                                <Box sx={{ flex: 1 }}>
                                    {recording.audio_url ? (
                                        <audio ref={audioRef} controls src={resolveMediaUrl(recording.audio_url)}
                                            style={{ width: '100%', height: 36 }}
                                            onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime || 0)}
                                            onSeeked={(e) => setCurrentTime(e.currentTarget.currentTime || 0)} />
                                    ) : (
                                        <Typography color="text.secondary" fontSize="0.85rem">Audio unavailable</Typography>
                                    )}
                                </Box>

                                {/* Skip forward */}
                                <Tooltip title="Forward 15s">
                                    <IconButton size="small" onClick={() => skipAudio(15)} sx={{ color: '#64748b' }}>
                                        <FastForward sx={{ fontSize: 20 }} />
                                    </IconButton>
                                </Tooltip>

                                {/* Playback speed */}
                                <Tooltip title="Playback speed">
                                    <Button size="small" variant="outlined" onClick={cycleSpeed}
                                        sx={{ minWidth: 50, fontSize: '0.75rem', fontWeight: 700, borderColor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' }}>
                                        {playbackSpeed}x
                                    </Button>
                                </Tooltip>

                                {/* Time display */}
                                <Typography variant="caption" fontFamily="monospace" color="text.secondary" sx={{ minWidth: 90, textAlign: 'right' }}>
                                    {formatTime(currentTime)} / {formatTime(totalDuration)}
                                </Typography>
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>

                {/* Transcript panel */}
                <Grid item xs={12}>
                    <Card>
                        <CardContent>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                                <Typography variant="subtitle2" fontWeight={700} sx={{ textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                    Transcript {segments.length > 0 && `(${segments.length} segments)`}
                                </Typography>
                                {segments.length > 0 && (
                                    <TextField size="small" placeholder="Search transcript..."
                                        value={transcriptSearch} onChange={(e) => setTranscriptSearch(e.target.value)}
                                        InputProps={{ startAdornment: <InputAdornment position="start"><Search sx={{ color: '#94a3b8', fontSize: 16 }} /></InputAdornment> }}
                                        sx={{ width: 220, '& .MuiInputBase-input': { fontSize: '0.8rem' } }} />
                                )}
                            </Box>

                            {filteredSegments.length > 0 ? (
                                <Box sx={{ maxHeight: 480, overflowY: 'auto', display: 'grid', gap: 0.5 }}>
                                    {filteredSegments.map((segment, index) => {
                                        const realIndex = segments.indexOf(segment);
                                        const active = realIndex === currentSegmentIndex;
                                        const highlightText = transcriptSearch.trim()
                                            ? String(segment.text || '').replace(
                                                new RegExp(`(${transcriptSearch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'),
                                                '<mark style="background:#fef08a;border-radius:2px;padding:0 1px">$1</mark>'
                                            )
                                            : null;

                                        return (
                                            <Box key={`${realIndex}-${segment.start}`}
                                                ref={active ? activeSegmentRef : null}
                                                onClick={() => seekToSegment(segment)}
                                                sx={{
                                                    p: 1.25, borderRadius: 2, cursor: 'pointer',
                                                    bgcolor: active ? 'rgba(16,185,129,0.12)' : 'rgba(1,66,162,0.03)',
                                                    borderLeft: active ? '3px solid #10b981' : '3px solid transparent',
                                                    transition: 'all 0.15s',
                                                    '&:hover': { bgcolor: active ? 'rgba(16,185,129,0.15)' : 'rgba(1,66,162,0.06)' },
                                                    display: 'flex', alignItems: 'flex-start', gap: 1,
                                                }}>
                                                <Typography variant="caption" sx={{
                                                    minWidth: 48, fontFamily: 'monospace', fontWeight: 600,
                                                    color: active ? '#10b981' : '#94a3b8', mt: 0.2,
                                                }}>
                                                    {formatTime(segment.start)}
                                                </Typography>
                                                {highlightText ? (
                                                    <Typography variant="body2" sx={{ flex: 1, lineHeight: 1.6 }}
                                                        dangerouslySetInnerHTML={{ __html: highlightText }} />
                                                ) : (
                                                    <Typography variant="body2" sx={{ flex: 1, lineHeight: 1.6, color: active ? '#0f172a' : 'text.primary' }}>
                                                        {segment.text}
                                                    </Typography>
                                                )}
                                                {active && <GraphicEq sx={{ color: '#10b981', fontSize: 16, mt: 0.3, flexShrink: 0 }} />}
                                            </Box>
                                        );
                                    })}
                                </Box>
                            ) : hasTranscript && !segments.length ? (
                                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.04)' }}>
                                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                                        {recording.transcript_text}
                                    </Typography>
                                </Box>
                            ) : transcriptSearch && segments.length > 0 ? (
                                <Typography color="text.secondary" sx={{ py: 3, textAlign: 'center' }}>
                                    No segments match "{transcriptSearch}"
                                </Typography>
                            ) : (
                                <Box sx={{ textAlign: 'center', py: 4 }}>
                                    <GraphicEq sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                    <Typography color="text.secondary">No transcript yet. Click "Generate Transcript" to start.</Typography>
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
