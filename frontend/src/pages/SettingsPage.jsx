import React, { useEffect, useState } from 'react';
import {
    Avatar, Box, Card, CardContent, Typography, Grid, TextField, Button,
    Divider, Alert, Chip, IconButton, Tooltip
} from '@mui/material';
import { CloudUpload, DeleteOutline, GraphicEq, MusicNote, Phone, Refresh, Settings } from '@mui/icons-material';
import toast from 'react-hot-toast';
import api from '../services/api';
import { relativeTime } from '../lib/formatDate';
import { resolveMediaUrl } from '../lib/mediaUrl';
import useConfirm from '../lib/useConfirm';

export default function SettingsPage() {
    const [waitAudio, setWaitAudio] = useState({ wait_url: '', file_name: '', uploaded_at: '', source: 'none' });
    const [audioFile, setAudioFile] = useState(null);
    const [audioLoading, setAudioLoading] = useState(false);
    const [audioUploading, setAudioUploading] = useState(false);
    const [audioClearing, setAudioClearing] = useState(false);
    const [confirm, ConfirmEl] = useConfirm();

    const loadWaitAudio = async ({ silent = false } = {}) => {
        if (!silent) setAudioLoading(true);
        try {
            const { data } = await api.get('/settings/exotel/wait-audio/');
            setWaitAudio({ wait_url: data?.wait_url || '', file_name: data?.file_name || '', uploaded_at: data?.uploaded_at || '', source: data?.source || 'none' });
        } catch (error) {
            if (!silent) toast.error(error?.response?.data?.error || 'Failed to load wait audio');
        } finally {
            if (!silent) setAudioLoading(false);
        }
    };

    useEffect(() => { loadWaitAudio(); }, []);

    const handleAudioUpload = async () => {
        if (!audioFile) { toast.error('Select an audio file first'); return; }
        const formData = new FormData();
        formData.append('file', audioFile);
        setAudioUploading(true);
        try {
            const { data } = await api.post('/settings/exotel/wait-audio/upload/', formData, { headers: { 'Content-Type': 'multipart/form-data' } });
            setWaitAudio({ wait_url: data?.wait_url || '', file_name: data?.file_name || '', uploaded_at: data?.uploaded_at || '', source: data?.source || 'uploaded' });
            setAudioFile(null);
            toast.success('Wait audio uploaded');
        } catch (error) {
            toast.error(error?.response?.data?.message || error?.response?.data?.error || 'Upload failed');
        } finally { setAudioUploading(false); }
    };

    const handleClearWaitAudio = async () => {
        const ok = await confirm({ title: 'Clear Wait Audio', body: 'The current wait audio will be removed. Exotel will use its default hold music.', confirmLabel: 'Clear', confirmColor: 'error' });
        if (!ok) return;
        setAudioClearing(true);
        try {
            const { data } = await api.post('/settings/exotel/wait-audio/clear/');
            setWaitAudio({ wait_url: data?.wait_url || '', file_name: data?.file_name || '', uploaded_at: data?.uploaded_at || '', source: data?.source || 'none' });
            toast.success('Wait audio cleared');
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to clear');
        } finally { setAudioClearing(false); }
    };

    const hasAudio = Boolean(waitAudio.wait_url);

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Settings</Typography>
                    <Typography color="text.secondary" variant="body2">Configure call settings and preferences</Typography>
                </Box>
                <Tooltip title="Refresh settings">
                    <IconButton onClick={() => loadWaitAudio()} disabled={audioLoading} sx={{ color: '#64748b' }}>
                        <Refresh />
                    </IconButton>
                </Tooltip>
            </Box>

            <Grid container spacing={3}>
                {/* Wait Audio Section */}
                <Grid item xs={12} md={8}>
                    <Card>
                        <CardContent>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
                                <Avatar sx={{ width: 40, height: 40, bgcolor: '#0142a215' }}>
                                    <MusicNote sx={{ color: '#0142a2', fontSize: 20 }} />
                                </Avatar>
                                <Box>
                                    <Typography fontWeight={700}>Exotel Wait Audio</Typography>
                                    <Typography variant="caption" color="text.secondary">Custom hold music played while connecting calls</Typography>
                                </Box>
                            </Box>

                            <Alert severity="info" sx={{ mb: 2, borderRadius: 2 }}>
                                Upload audio here. The app generates and uses a WaitUrl for Exotel automatically.
                            </Alert>

                            <Grid container spacing={2} sx={{ mb: 2 }}>
                                <Grid item xs={12} sm={6}>
                                    <TextField fullWidth size="small" type="file"
                                        inputProps={{ accept: '.mp3,.wav,.ogg,.m4a,audio/*' }}
                                        onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
                                        helperText="Supported: mp3, wav, ogg, m4a" />
                                </Grid>
                                <Grid item xs={12} sm={6}>
                                    <Box sx={{ display: 'flex', gap: 1, height: '100%', alignItems: 'flex-start' }}>
                                        <Button variant="contained" startIcon={<CloudUpload />}
                                            onClick={handleAudioUpload} disabled={!audioFile || audioUploading}
                                            sx={{ bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' } }}>
                                            {audioUploading ? 'Uploading...' : 'Upload'}
                                        </Button>
                                        <Tooltip title="Remove current audio. Exotel will use default hold music.">
                                            <span>
                                                <Button variant="outlined" color="error" startIcon={<DeleteOutline />}
                                                    onClick={handleClearWaitAudio} disabled={audioClearing || !hasAudio}>
                                                    {audioClearing ? 'Clearing...' : 'Clear'}
                                                </Button>
                                            </span>
                                        </Tooltip>
                                    </Box>
                                </Grid>
                            </Grid>

                            {!hasAudio && !audioFile && (
                                <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                                    Select an audio file and click Upload to set custom hold music for callers.
                                </Typography>
                            )}

                            {/* Current audio display */}
                            {hasAudio && (
                                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.04)', border: '1px solid rgba(1,66,162,0.08)' }}>
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
                                        <GraphicEq sx={{ color: '#10b981', fontSize: 18 }} />
                                        <Typography fontWeight={600} fontSize="0.85rem">{waitAudio.file_name || 'Wait Audio'}</Typography>
                                        <Chip size="small" label={waitAudio.source}
                                            sx={{ bgcolor: '#10b98115', color: '#10b981', fontSize: '0.65rem', fontWeight: 600 }} />
                                        {waitAudio.uploaded_at && (
                                            <Typography variant="caption" color="text.secondary">
                                                Uploaded {relativeTime(waitAudio.uploaded_at)}
                                            </Typography>
                                        )}
                                    </Box>
                                    <audio controls src={resolveMediaUrl(waitAudio.wait_url)} style={{ width: '100%', height: 36 }} />
                                </Box>
                            )}

                            {!hasAudio && !audioLoading && (
                                <Box sx={{ textAlign: 'center', py: 3 }}>
                                    <MusicNote sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                    <Typography color="text.secondary" fontSize="0.85rem">No custom wait audio configured. Exotel uses default hold music.</Typography>
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                {/* Quick info sidebar */}
                <Grid item xs={12} md={4}>
                    <Card sx={{ bgcolor: 'rgba(1,66,162,0.03)' }}>
                        <CardContent>
                            <Typography fontWeight={700} fontSize="0.85rem" sx={{ mb: 1.5 }}>About Wait Audio</Typography>
                            <Box sx={{ display: 'grid', gap: 1.5 }}>
                                {[
                                    { q: 'When is it played?', a: 'While the customer waits for the SDR to pick up after the call is bridged.' },
                                    { q: 'What format?', a: 'MP3, WAV, OGG, or M4A. Keep it under 5MB for best performance.' },
                                    { q: 'What happens if cleared?', a: 'Exotel plays its default hold music instead.' },
                                ].map((item) => (
                                    <Box key={item.q}>
                                        <Typography variant="caption" fontWeight={600} color="text.secondary">{item.q}</Typography>
                                        <Typography variant="body2" fontSize="0.8rem">{item.a}</Typography>
                                    </Box>
                                ))}
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
            {ConfirmEl}
        </Box>
    );
}
