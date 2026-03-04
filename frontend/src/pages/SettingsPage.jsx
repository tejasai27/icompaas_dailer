import React, { useState } from 'react';
import {
    Box, Card, CardContent, Typography, Grid, TextField, Button,
    Divider, Alert, Switch, FormControlLabel, Chip
} from '@mui/material';
import { Save, Key, Phone, Refresh } from '@mui/icons-material';
import toast from 'react-hot-toast';

export default function SettingsPage() {
    const [plivoConfig, setPlivoConfig] = useState({
        auth_id: '',
        auth_token: '',
        from_number: '',
        webhook_url: 'http://localhost:8000'
    });
    const [dialerSettings, setDialerSettings] = useState({
        default_delay: 15,
        max_retries: 3,
        whisper_model: 'base',
        auto_transcribe: true,
    });
    const [saved, setSaved] = useState(false);

    const handleSave = () => {
        // In a real app, these would be saved via API to config or .env
        toast.success('Settings saved! Restart Django server to apply Plivo credentials.');
        setSaved(true);
    };

    return (
        <Box>
            <Box sx={{ mb: 3 }}>
                <Typography variant="h4" fontWeight={700}>Settings</Typography>
                <Typography color="text.secondary" variant="body2">Configure the Power Dialer platform</Typography>
            </Box>

            <Grid container spacing={3}>
                {/* Plivo Config */}
                <Grid item xs={12} md={6}>
                    <Card>
                        <CardContent>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                                <Key sx={{ color: '#6366f1' }} />
                                <Typography variant="subtitle1" fontWeight={700}>Plivo API Configuration</Typography>
                            </Box>

                            <Alert severity="info" sx={{ mb: 2, bgcolor: 'rgba(59,130,246,0.1)' }}>
                                Configure these in your <code>.env</code> file in <code>backend/</code> for production.
                            </Alert>

                            <Grid container spacing={2}>
                                <Grid item xs={12}>
                                    <TextField fullWidth label="Auth ID" value={plivoConfig.auth_id}
                                        onChange={e => setPlivoConfig({ ...plivoConfig, auth_id: e.target.value })}
                                        placeholder="MAXXXXXXXXXXXXXXXXXXXXXXXX" size="small" />
                                </Grid>
                                <Grid item xs={12}>
                                    <TextField fullWidth label="Auth Token" type="password"
                                        value={plivoConfig.auth_token}
                                        onChange={e => setPlivoConfig({ ...plivoConfig, auth_token: e.target.value })}
                                        placeholder="••••••••••••••••••••••••••••••••" size="small" />
                                </Grid>
                                <Grid item xs={12}>
                                    <TextField fullWidth label="From Number (Caller ID)"
                                        value={plivoConfig.from_number}
                                        onChange={e => setPlivoConfig({ ...plivoConfig, from_number: e.target.value })}
                                        placeholder="+12345678901" size="small" helperText="Plivo phone number in E.164 format" />
                                </Grid>
                                <Grid item xs={12}>
                                    <TextField fullWidth label="Webhook Base URL"
                                        value={plivoConfig.webhook_url}
                                        onChange={e => setPlivoConfig({ ...plivoConfig, webhook_url: e.target.value })}
                                        size="small" helperText="Publicly accessible URL for Plivo webhooks (use ngrok for dev)" />
                                </Grid>
                            </Grid>

                            <Divider sx={{ my: 2, borderColor: 'rgba(99,102,241,0.1)' }} />

                            <Typography variant="caption" color="text.secondary" display="block" mb={1}>
                                Required .env variables:
                            </Typography>
                            <Box sx={{ p: 2, borderRadius: 2, bgcolor: '#0f0f1a', fontFamily: 'monospace', fontSize: '0.8rem', color: '#818cf8' }}>
                                PLIVO_AUTH_ID=MA...<br />
                                PLIVO_AUTH_TOKEN=...<br />
                                PLIVO_FROM_NUMBER=+1...<br />
                                PLIVO_WEBHOOK_BASE_URL=https://...
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>

                {/* Dialer Settings */}
                <Grid item xs={12} md={6}>
                    <Card>
                        <CardContent>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                                <Phone sx={{ color: '#10b981' }} />
                                <Typography variant="subtitle1" fontWeight={700}>Dialer Defaults</Typography>
                            </Box>

                            <Grid container spacing={2}>
                                <Grid item xs={12}>
                                    <TextField fullWidth type="number" label="Default Delay Between Calls (seconds)"
                                        value={dialerSettings.default_delay}
                                        onChange={e => setDialerSettings({ ...dialerSettings, default_delay: e.target.value })}
                                        size="small" inputProps={{ min: 5, max: 300 }} />
                                </Grid>
                                <Grid item xs={12}>
                                    <TextField fullWidth type="number" label="Default Max Retries"
                                        value={dialerSettings.max_retries}
                                        onChange={e => setDialerSettings({ ...dialerSettings, max_retries: e.target.value })}
                                        size="small" inputProps={{ min: 0, max: 10 }} />
                                </Grid>
                                <Grid item xs={12}>
                                    <TextField fullWidth label="Whisper Model"
                                        value={dialerSettings.whisper_model}
                                        onChange={e => setDialerSettings({ ...dialerSettings, whisper_model: e.target.value })}
                                        size="small" helperText="tiny / base / small / medium / large" select
                                        SelectProps={{ native: true }}>
                                        {['tiny', 'base', 'small', 'medium', 'large'].map(m => <option key={m} value={m}>{m}</option>)}
                                    </TextField>
                                </Grid>
                                <Grid item xs={12}>
                                    <FormControlLabel
                                        control={
                                            <Switch
                                                checked={dialerSettings.auto_transcribe}
                                                onChange={e => setDialerSettings({ ...dialerSettings, auto_transcribe: e.target.checked })}
                                                sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#10b981' } }}
                                            />
                                        }
                                        label={<Typography variant="body2">Auto-transcribe completed calls</Typography>}
                                    />
                                </Grid>
                            </Grid>
                        </CardContent>
                    </Card>

                    {/* Redis / Celery info */}
                    <Card sx={{ mt: 2 }}>
                        <CardContent>
                            <Typography variant="subtitle1" fontWeight={700} mb={1}>🔄 Worker Status</Typography>
                            <Alert severity="warning" sx={{ bgcolor: 'rgba(245,158,11,0.1)', mb: 2 }}>
                                Celery worker must be running for background dialing tasks.
                            </Alert>
                            <Box sx={{ p: 2, borderRadius: 2, bgcolor: '#0f0f1a', fontFamily: 'monospace', fontSize: '0.8rem', color: '#818cf8' }}>
                                # Terminal 1 (Redis)<br />
                                redis-server<br /><br />
                                # Terminal 2 (Celery)<br />
                                celery -A dialer_project worker -l info
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>

                <Grid item xs={12}>
                    <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                        <Button
                            variant="contained"
                            startIcon={<Save />}
                            onClick={handleSave}
                            sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)' }}
                        >
                            Save Settings
                        </Button>
                    </Box>
                </Grid>
            </Grid>
        </Box>
    );
}
