import React, { useEffect, useState } from 'react';
import {
    Box, Card, CardContent, Typography, Grid, TextField, Button,
    Divider, Alert, Chip
} from '@mui/material';
import { Phone, Refresh, CloudUpload, DeleteOutline } from '@mui/icons-material';
import toast from 'react-hot-toast';
import api from '../services/api';

export default function SettingsPage() {
    const [waitAudio, setWaitAudio] = useState({
        wait_url: '',
        file_name: '',
        uploaded_at: '',
        source: 'none',
    });
    const [audioFile, setAudioFile] = useState(null);
    const [audioLoading, setAudioLoading] = useState(false);
    const [audioUploading, setAudioUploading] = useState(false);
    const [audioClearing, setAudioClearing] = useState(false);

    const loadWaitAudio = async ({ silent = false } = {}) => {
        if (!silent) setAudioLoading(true);
        try {
            const { data } = await api.get('/settings/exotel/wait-audio/');
            setWaitAudio({
                wait_url: data?.wait_url || '',
                file_name: data?.file_name || '',
                uploaded_at: data?.uploaded_at || '',
                source: data?.source || 'none',
            });
        } catch (error) {
            if (!silent) {
                toast.error(error?.response?.data?.error || 'Failed to load wait audio');
            }
        } finally {
            if (!silent) setAudioLoading(false);
        }
    };

    useEffect(() => {
        loadWaitAudio();
    }, []);

    const handleAudioUpload = async () => {
        if (!audioFile) {
            toast.error('Select an audio file first');
            return;
        }

        const formData = new FormData();
        formData.append('file', audioFile);

        setAudioUploading(true);
        try {
            const { data } = await api.post('/settings/exotel/wait-audio/upload/', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            setWaitAudio({
                wait_url: data?.wait_url || '',
                file_name: data?.file_name || '',
                uploaded_at: data?.uploaded_at || '',
                source: data?.source || 'uploaded',
            });
            setAudioFile(null);
            toast.success('Wait audio uploaded');
        } catch (error) {
            toast.error(error?.response?.data?.message || error?.response?.data?.error || 'Upload failed');
        } finally {
            setAudioUploading(false);
        }
    };

    const handleClearWaitAudio = async () => {
        setAudioClearing(true);
        try {
            const { data } = await api.post('/settings/exotel/wait-audio/clear/');
            setWaitAudio({
                wait_url: data?.wait_url || '',
                file_name: data?.file_name || '',
                uploaded_at: data?.uploaded_at || '',
                source: data?.source || 'none',
            });
            toast.success('Uploaded wait audio cleared');
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to clear wait audio');
        } finally {
            setAudioClearing(false);
        }
    };

    return (
        <Box>
            <Box sx={{ mb: 3 }}>
                <Typography variant="h4" fontWeight={700}>Settings</Typography>
                <Typography color="text.secondary" variant="body2">Configure Exotel call wait audio</Typography>
            </Box>

            <Grid container spacing={3}>
                <Grid item xs={12}>
                    <Card>
                        <CardContent>
                            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 2 }}>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <Phone sx={{ color: '#6366f1' }} />
                                    <Typography variant="subtitle1" fontWeight={700}>Exotel Wait Audio</Typography>
                                </Box>
                                <Button
                                    variant="outlined"
                                    size="small"
                                    startIcon={<Refresh />}
                                    onClick={() => loadWaitAudio()}
                                    disabled={audioLoading || audioUploading || audioClearing}
                                >
                                    Refresh
                                </Button>
                            </Box>

                            <Alert severity="info" sx={{ mb: 2, bgcolor: 'rgba(59,130,246,0.1)' }}>
                                Upload audio directly here. The app automatically generates and uses a WaitUrl for Exotel.
                            </Alert>

                            <Grid container spacing={2}>
                                <Grid item xs={12}>
                                    <TextField
                                        fullWidth
                                        size="small"
                                        type="file"
                                        inputProps={{ accept: '.mp3,.wav,.ogg,.m4a,audio/*' }}
                                        onChange={(e) => setAudioFile(e.target.files?.[0] || null)}
                                        helperText="Supported: mp3, wav, ogg, m4a"
                                    />
                                </Grid>
                                <Grid item xs={12}>
                                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                                        <Button
                                            variant="contained"
                                            startIcon={<CloudUpload />}
                                            onClick={handleAudioUpload}
                                            disabled={!audioFile || audioUploading || audioLoading || audioClearing}
                                        >
                                            {audioUploading ? 'Uploading...' : 'Upload Audio'}
                                        </Button>
                                        <Button
                                            variant="outlined"
                                            color="error"
                                            startIcon={<DeleteOutline />}
                                            onClick={handleClearWaitAudio}
                                            disabled={audioClearing || audioUploading || audioLoading}
                                        >
                                            {audioClearing ? 'Clearing...' : 'Clear Uploaded Audio'}
                                        </Button>
                                    </Box>
                                </Grid>
                            </Grid>

                            <Divider sx={{ my: 2, borderColor: 'rgba(99,102,241,0.1)' }} />

                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                                <Typography variant="body2" color="text.secondary">Current source:</Typography>
                                <Chip
                                    size="small"
                                    label={waitAudio.source || 'none'}
                                    sx={{
                                        bgcolor: waitAudio.wait_url ? 'rgba(16,185,129,0.15)' : 'rgba(148,163,184,0.15)',
                                        color: waitAudio.wait_url ? '#10b981' : '#64748b',
                                    }}
                                />
                            </Box>
                            <Typography variant="body2" sx={{ wordBreak: 'break-all', mb: 1 }}>
                                {waitAudio.wait_url || 'No wait audio configured'}
                            </Typography>
                            {waitAudio.file_name ? (
                                <Typography variant="caption" color="text.secondary" display="block" mb={1}>
                                    File: {waitAudio.file_name}
                                </Typography>
                            ) : null}
                            {waitAudio.uploaded_at ? (
                                <Typography variant="caption" color="text.secondary" display="block" mb={1}>
                                    Uploaded: {new Date(waitAudio.uploaded_at).toLocaleString()}
                                </Typography>
                            ) : null}

                            {waitAudio.wait_url ? (
                                <Box sx={{ mt: 1 }}>
                                    <audio controls src={waitAudio.wait_url} style={{ width: '100%' }} />
                                </Box>
                            ) : null}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
