import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Divider,
    LinearProgress,
    Typography,
} from '@mui/material';
import { ArrowBack, GraphicEq, Mic } from '@mui/icons-material';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import { resolveMediaUrl } from '../lib/mediaUrl';

function formatTime(seconds) {
    const total = Math.max(0, Number(seconds || 0));
    const minutes = Math.floor(total / 60);
    const rem = total % 60;
    return `${String(minutes).padStart(2, '0')}:${String(Math.floor(rem)).padStart(2, '0')}`;
}

function formatTranscriptStage(stage) {
    const value = String(stage || '').trim().toLowerCase().replace(/_/g, ' ');
    if (!value) return '';
    if (value === 'queued') return 'Queued';
    if (value === 'preparing audio') return 'Preparing audio';
    if (value === 'downloading audio') return 'Downloading audio';
    if (value === 'uploading audio') return 'Uploading audio';
    if (value === 'transcribing') return 'Transcribing';
    if (value === 'saving') return 'Saving transcript';
    if (value === 'finalizing') return 'Finalizing';
    if (value === 'completed') return 'Completed';
    if (value === 'failed') return 'Failed';
    return value.charAt(0).toUpperCase() + value.slice(1);
}

export default function RecordingTranscriptPage() {
    const navigate = useNavigate();
    const { recordingPublicId } = useParams();
    const audioRef = useRef(null);

    const [loading, setLoading] = useState(true);
    const [transcribing, setTranscribing] = useState(false);
    const [trackUntilComplete, setTrackUntilComplete] = useState(false);
    const [recording, setRecording] = useState(null);
    const [currentTime, setCurrentTime] = useState(0);
    const [currentSegmentIndex, setCurrentSegmentIndex] = useState(-1);

    const segments = useMemo(() => {
        const raw = recording?.transcript_segments;
        return Array.isArray(raw) ? raw : [];
    }, [recording?.transcript_segments]);

    const hasTranscript = Boolean((recording?.transcript_text || '').trim());
    const transcriptStatus = String(recording?.transcript_status || '').toLowerCase();
    const transcriptProgressPercent = Math.max(
        0,
        Math.min(100, Number(recording?.transcript_progress_percent ?? (transcriptStatus === 'completed' ? 100 : 0))),
    );
    const transcriptProgressStage = formatTranscriptStage(recording?.transcript_progress_stage || transcriptStatus);

    const loadRecording = async ({ silent = false } = {}) => {
        if (!recordingPublicId) return;
        if (!silent) {
            setLoading(true);
        }
        try {
            const { data } = await api.get(`/recordings/${recordingPublicId}/`);
            setRecording(data?.recording || null);
        } catch (error) {
            if (!silent) {
                toast.error(error?.response?.data?.error || 'Failed to load recording');
            }
        } finally {
            if (!silent) {
                setLoading(false);
            }
        }
    };

    useEffect(() => {
        loadRecording();
    }, [recordingPublicId]);

    useEffect(() => {
        if (!recordingPublicId) return undefined;
        if (String(recording?.transcript_status || '').toLowerCase() !== 'processing') return undefined;
        const interval = setInterval(() => {
            loadRecording({ silent: true });
        }, 5000);
        return () => clearInterval(interval);
    }, [recordingPublicId, recording?.transcript_status]);

    useEffect(() => {
        if (!transcribing || !trackUntilComplete) return;
        const status = String(recording?.transcript_status || '').toLowerCase();
        if (status && status !== 'processing') {
            setTranscribing(false);
            setTrackUntilComplete(false);
        }
    }, [recording?.transcript_status, transcribing, trackUntilComplete]);

    useEffect(() => {
        if (!segments.length) {
            setCurrentSegmentIndex(-1);
            return;
        }
        const index = segments.findIndex((segment) => {
            const start = Number(segment?.start || 0);
            const end = Number(segment?.end ?? start + 1);
            return currentTime >= start && currentTime < end;
        });
        setCurrentSegmentIndex(index);
    }, [currentTime, segments]);

    const runTranscription = async () => {
        if (!recordingPublicId) return;
        setTranscribing(true);
        setTrackUntilComplete(false);
        try {
            const { data } = await api.post(`/recordings/${recordingPublicId}/transcribe/`, { language: 'auto' });
            const nextRecording = data?.recording || null;
            setRecording(nextRecording);
            const nextStatus = String(nextRecording?.transcript_status || '').toLowerCase();
            if (data?.queued || nextStatus === 'processing') {
                toast.success('Transcription started');
                setTrackUntilComplete(true);
            } else {
                toast.success('Transcription completed');
                setTranscribing(false);
                setTrackUntilComplete(false);
            }
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Transcription failed');
            setTranscribing(false);
            setTrackUntilComplete(false);
        }
    };

    const seekToSegment = (segment) => {
        if (!audioRef.current) return;
        const start = Number(segment?.start || 0);
        audioRef.current.currentTime = start;
        setCurrentTime(start);
        audioRef.current.play().catch(() => { });
    };

    if (loading) {
        return (
            <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}>
                <CircularProgress />
            </Box>
        );
    }

    if (!recording) {
        return (
            <Alert severity="error">Recording not found</Alert>
        );
    }

    return (
        <Box>
            <Button startIcon={<ArrowBack />} onClick={() => navigate('/recordings')} sx={{ mb: 2 }}>
                Back to Recordings
            </Button>

            <Card sx={{ mb: 2 }}>
                <CardContent>
                    <Typography variant="h5" fontWeight={700} sx={{ mb: 0.5 }}>
                        {recording.title}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                        {recording.contact_name || 'Uploaded Recording'} {recording.contact_phone ? `· ${recording.contact_phone}` : ''}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', mb: 1 }}>
                        <Chip size="small" label={recording.source} />
                        <Chip size="small" label={`Transcript: ${recording.transcript_status || 'none'}`} />
                        <Chip size="small" label={`Duration: ${recording.duration_formatted || '-'}`} />
                    </Box>
                    {!hasTranscript ? (
                        <Alert severity="info" sx={{ mb: 2 }}>
                            Transcript is generated automatically when recording is available. You can use "Generate Transcript" to retry manually.
                        </Alert>
                    ) : null}
                    {recording.transcript_error ? (
                        <Alert severity="error" sx={{ mb: 2 }}>
                            {recording.transcript_error}
                        </Alert>
                    ) : null}
                    {transcriptStatus === 'processing' ? (
                        <Alert severity="info" sx={{ mb: 2 }}>
                            Large recordings can take a few minutes. This page refreshes transcript status automatically.
                        </Alert>
                    ) : null}
                    {(transcriptStatus === 'processing' || transcriptStatus === 'completed' || transcriptStatus === 'failed') ? (
                        <Box sx={{ mb: 2 }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.75 }}>
                                <Typography variant="caption" color="text.secondary">
                                    Transcription Progress
                                </Typography>
                                <Typography variant="caption" fontWeight={700}>
                                    {transcriptProgressPercent}%
                                </Typography>
                            </Box>
                            <LinearProgress
                                variant="determinate"
                                value={transcriptProgressPercent}
                                color={transcriptStatus === 'failed' ? 'error' : transcriptStatus === 'completed' ? 'success' : 'primary'}
                                sx={{ height: 8, borderRadius: 10 }}
                            />
                            {transcriptProgressStage ? (
                                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
                                    {transcriptProgressStage}
                                </Typography>
                            ) : null}
                        </Box>
                    ) : null}
                    <Button
                        variant="contained"
                        startIcon={transcribing ? <CircularProgress size={16} color="inherit" /> : <Mic />}
                        onClick={runTranscription}
                        disabled={transcribing}
                        sx={{ mr: 1, mb: { xs: 1, sm: 0 } }}
                    >
                        {transcribing ? 'Transcribing...' : 'Generate Transcript'}
                    </Button>
                    <Chip size="small" label="English Only" sx={{ mt: { xs: 0.25, sm: 0 } }} />
                </CardContent>
            </Card>

            <Card sx={{ mb: 2 }}>
                <CardContent>
                    <Typography variant="h6" fontWeight={700} sx={{ mb: 1 }}>
                        Transcript
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                        Current playback: {formatTime(currentTime)}
                    </Typography>
                    <Divider sx={{ mb: 1.5 }} />
                    {segments.length ? (
                        <Box sx={{ maxHeight: 360, overflowY: 'auto', display: 'grid', gap: 0.75 }}>
                            {segments.map((segment, index) => {
                                const active = index === currentSegmentIndex;
                                return (
                                    <Box
                                        key={`${index}-${segment.start}-${segment.end}`}
                                        onClick={() => seekToSegment(segment)}
                                        sx={{
                                            p: 1.2,
                                            borderRadius: 1.5,
                                            cursor: 'pointer',
                                            bgcolor: active ? 'rgba(16,185,129,0.2)' : 'rgba(1,66,162,0.08)',
                                            border: active ? '1px solid rgba(16,185,129,0.5)' : '1px solid transparent',
                                            transition: 'all 0.15s ease',
                                            display: 'flex',
                                            alignItems: 'flex-start',
                                            gap: 1,
                                        }}
                                    >
                                        <Typography variant="caption" sx={{ minWidth: 52, color: active ? '#10b981' : '#94a3b8' }}>
                                            {formatTime(segment.start)}
                                        </Typography>
                                        <Typography variant="body2" sx={{ color: active ? '#212322ff' : 'text.primary' }}>
                                            {segment.text}
                                        </Typography>
                                        {active ? <GraphicEq sx={{ color: '#10b981', fontSize: 18, ml: 'auto' }} /> : null}
                                    </Box>
                                );
                            })}
                        </Box>
                    ) : hasTranscript ? (
                        <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.08)' }}>
                            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                                {recording.transcript_text}
                            </Typography>
                        </Box>
                    ) : (
                        <Typography color="text.secondary">No transcript yet.</Typography>
                    )}
                </CardContent>
            </Card>

            <Card>
                <CardContent>
                    <Typography variant="h6" fontWeight={700} sx={{ mb: 1.5 }}>
                        Recording
                    </Typography>
                    {recording.audio_url ? (
                        <audio
                            ref={audioRef}
                            controls
                            src={resolveMediaUrl(recording.audio_url)}
                            style={{ width: '100%' }}
                            onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime || 0)}
                            onSeeked={(event) => setCurrentTime(event.currentTarget.currentTime || 0)}
                        />
                    ) : (
                        <Typography color="text.secondary">Audio source unavailable.</Typography>
                    )}
                </CardContent>
            </Card>
        </Box>
    );
}
