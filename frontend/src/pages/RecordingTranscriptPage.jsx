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

export default function RecordingTranscriptPage() {
    const navigate = useNavigate();
    const { recordingPublicId } = useParams();
    const audioRef = useRef(null);

    const [loading, setLoading] = useState(true);
    const [transcribing, setTranscribing] = useState(false);
    const [recording, setRecording] = useState(null);
    const [currentTime, setCurrentTime] = useState(0);
    const [currentSegmentIndex, setCurrentSegmentIndex] = useState(-1);

    const segments = useMemo(() => {
        const raw = recording?.transcript_segments;
        return Array.isArray(raw) ? raw : [];
    }, [recording?.transcript_segments]);

    const hasTranscript = Boolean((recording?.transcript_text || '').trim());

    const loadRecording = async () => {
        if (!recordingPublicId) return;
        setLoading(true);
        try {
            const { data } = await api.get(`/recordings/${recordingPublicId}/`);
            setRecording(data?.recording || null);
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to load recording');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadRecording();
    }, [recordingPublicId]);

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
        try {
            const { data } = await api.post(`/recordings/${recordingPublicId}/transcribe/`);
            setRecording(data?.recording || null);
            toast.success('Transcription completed');
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Transcription failed');
        } finally {
            setTranscribing(false);
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
                    <Button
                        variant="contained"
                        startIcon={transcribing ? <CircularProgress size={16} color="inherit" /> : <Mic />}
                        onClick={runTranscription}
                        disabled={transcribing}
                    >
                        {transcribing ? 'Transcribing...' : 'Generate Transcript'}
                    </Button>
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
