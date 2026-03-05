import React, { useEffect, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    FormControlLabel,
    Grid,
    Stack,
    Switch,
    Typography,
} from '@mui/material';
import { Hub, Refresh } from '@mui/icons-material';
import toast from 'react-hot-toast';
import api from '../services/api';

const DEFAULT_FORM = {
    enabled: false,
    auto_sync_terminal_calls: true,
    auto_sync_on_disposition: true,
};

export default function IntegrationsPage() {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [clearingToken, setClearingToken] = useState(false);
    const [form, setForm] = useState(DEFAULT_FORM);
    const [settingsMeta, setSettingsMeta] = useState({
        access_token_configured: false,
        access_token_masked: '',
        access_token_source: 'none',
        updated_at: '',
    });
    const [connectionStatus, setConnectionStatus] = useState({
        state: 'unknown',
        message: 'Not checked yet',
        checked_at: '',
    });
    const [settingsWarning, setSettingsWarning] = useState('');

    const runConnectionCheck = async ({ silent = false } = {}) => {
        const hasToken = Boolean(settingsMeta.access_token_configured);

        if (!hasToken) {
            setConnectionStatus({
                state: 'disconnected',
                message: 'No HubSpot token configured',
                checked_at: '',
            });
            if (!silent) {
                toast.error('HubSpot token missing');
            }
            return false;
        }

        setConnectionStatus({
            state: 'checking',
            message: 'Checking HubSpot connectivity...',
            checked_at: '',
        });
        setTesting(true);
        try {
            const { data } = await api.post('/integrations/hubspot/test/', {});
            const sampleName = data?.sample_deal?.name ? ` Sample deal: ${data.sample_deal.name}` : '';
            setConnectionStatus({
                state: 'connected',
                message: `Connected to HubSpot.${sampleName}`.trim(),
                checked_at: new Date().toISOString(),
            });
            if (!silent) {
                toast.success(`HubSpot connection successful.${sampleName}`);
            }
            return true;
        } catch (error) {
            const detailsError = error?.response?.data?.details?.error;
            const statusError = error?.response?.data?.error;
            const errorText = detailsError || statusError || 'HubSpot connection failed';
            setConnectionStatus({
                state: 'disconnected',
                message: errorText,
                checked_at: new Date().toISOString(),
            });
            if (!silent) {
                toast.error(errorText);
            }
            return false;
        } finally {
            setTesting(false);
        }
    };

    const loadSettings = async ({ silent = false } = {}) => {
        if (!silent) setLoading(true);
        try {
            const { data } = await api.get('/integrations/hubspot/settings/');
            const settings = data?.settings || {};
            setSettingsWarning(String(data?.warning || '').trim());
            setForm({
                enabled: Boolean(settings.enabled),
                auto_sync_terminal_calls: settings.auto_sync_terminal_calls !== false,
                auto_sync_on_disposition: settings.auto_sync_on_disposition !== false,
            });
            setSettingsMeta({
                access_token_configured: Boolean(settings.access_token_configured),
                access_token_masked: settings.access_token_masked || '',
                access_token_source: settings.access_token_source || 'none',
                updated_at: settings.updated_at || '',
            });
            if (settings.access_token_configured) {
                void runConnectionCheck({ silent: true });
            } else {
                setConnectionStatus({
                    state: 'disconnected',
                    message: 'No HubSpot token configured',
                    checked_at: '',
                });
            }
        } catch (error) {
            if (!silent) {
                toast.error(error?.response?.data?.error || 'Failed to load HubSpot settings');
            }
            setSettingsWarning('');
            setConnectionStatus({
                state: 'unknown',
                message: 'Unable to read HubSpot settings',
                checked_at: '',
            });
        } finally {
            if (!silent) setLoading(false);
        }
    };

    useEffect(() => {
        loadSettings();
    }, []);

    const handleSave = async () => {
        setSaving(true);
        try {
            const payload = {
                enabled: form.enabled,
                auto_sync_terminal_calls: form.auto_sync_terminal_calls,
                auto_sync_on_disposition: form.auto_sync_on_disposition,
            };
            const { data } = await api.post('/integrations/hubspot/settings/', payload);
            const settings = data?.settings || {};
            setSettingsMeta({
                access_token_configured: Boolean(settings.access_token_configured),
                access_token_masked: settings.access_token_masked || '',
                access_token_source: settings.access_token_source || 'none',
                updated_at: settings.updated_at || '',
            });
            toast.success('HubSpot settings saved');
            if (settings.access_token_configured) {
                await runConnectionCheck({ silent: true });
            } else {
                setConnectionStatus({
                    state: 'disconnected',
                    message: 'No HubSpot token configured',
                    checked_at: '',
                });
            }
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to save HubSpot settings');
        } finally {
            setSaving(false);
        }
    };

    const handleTest = async () => {
        await runConnectionCheck({ silent: false });
    };

    const handleClearToken = async () => {
        setClearingToken(true);
        try {
            const { data } = await api.post('/integrations/hubspot/settings/', { clear_access_token: true });
            const settings = data?.settings || {};
            setSettingsMeta({
                access_token_configured: Boolean(settings.access_token_configured),
                access_token_masked: settings.access_token_masked || '',
                access_token_source: settings.access_token_source || 'none',
                updated_at: settings.updated_at || '',
            });
            toast.success('HubSpot token cleared from DB settings');
            setConnectionStatus({
                state: 'disconnected',
                message: 'No HubSpot token configured',
                checked_at: '',
            });
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to clear token');
        } finally {
            setClearingToken(false);
        }
    };

    const connectionChipConfig = (() => {
        if (connectionStatus.state === 'connected') {
            return {
                label: 'Connected',
                sx: { bgcolor: 'rgba(16,185,129,0.15)', color: '#10b981' },
            };
        }
        if (connectionStatus.state === 'checking') {
            return {
                label: 'Checking...',
                sx: { bgcolor: 'rgba(59,130,246,0.15)', color: '#3b82f6' },
            };
        }
        if (connectionStatus.state === 'unknown') {
            return {
                label: 'Unknown',
                sx: { bgcolor: 'rgba(245,158,11,0.15)', color: '#f59e0b' },
            };
        }
        return {
            label: 'Disconnected',
            sx: { bgcolor: 'rgba(239,68,68,0.15)', color: '#ef4444' },
        };
    })();

    return (
        <Box>
            <Box sx={{ mb: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Integrations</Typography>
                    <Typography color="text.secondary" variant="body2">
                        Configure third-party integrations used by the dialer
                    </Typography>
                </Box>
                <Button
                    variant="outlined"
                    startIcon={<Refresh />}
                    onClick={() => loadSettings()}
                    disabled={loading || saving || testing || clearingToken}
                >
                    Refresh
                </Button>
            </Box>

            <Card>
                <CardContent>
                    <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
                        <Hub sx={{ color: '#f59e0b' }} />
                        <Typography variant="h6" fontWeight={700}>HubSpot</Typography>
                        <Chip
                            size="small"
                            label={connectionChipConfig.label}
                            sx={connectionChipConfig.sx}
                        />
                        <Chip
                            size="small"
                            label={form.enabled ? 'Integration Enabled' : 'Integration Disabled'}
                            sx={{
                                bgcolor: form.enabled ? 'rgba(16,185,129,0.15)' : 'rgba(100,116,139,0.2)',
                                color: form.enabled ? '#10b981' : '#94a3b8',
                            }}
                        />
                        <Chip
                            size="small"
                            label={settingsMeta.access_token_configured ? 'Token Configured' : 'Token Missing'}
                            sx={{
                                bgcolor: settingsMeta.access_token_configured ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
                                color: settingsMeta.access_token_configured ? '#10b981' : '#ef4444',
                            }}
                        />
                    </Stack>

                    <Alert severity="info" sx={{ mb: 2 }}>
                        Calls are synced to HubSpot as Call activities.
                    </Alert>
                    {settingsWarning ? (
                        <Alert severity="warning" sx={{ mb: 2 }}>
                            {settingsWarning}
                        </Alert>
                    ) : null}
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                        Connection status: {connectionStatus.message}
                        {connectionStatus.checked_at ? ` (checked at ${new Date(connectionStatus.checked_at).toLocaleString()})` : ''}
                    </Typography>

                    <Grid container spacing={2}>
                        <Grid item xs={12} md={6}>
                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={form.enabled}
                                        onChange={(event) => setForm((prev) => ({ ...prev, enabled: event.target.checked }))}
                                    />
                                }
                                label="Enable HubSpot integration"
                            />
                        </Grid>
                        <Grid item xs={12} md={6}>
                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={form.auto_sync_terminal_calls}
                                        onChange={(event) =>
                                            setForm((prev) => ({ ...prev, auto_sync_terminal_calls: event.target.checked }))
                                        }
                                    />
                                }
                                label="Auto sync on call terminal"
                            />
                        </Grid>
                        <Grid item xs={12} md={6}>
                            <FormControlLabel
                                control={
                                    <Switch
                                        checked={form.auto_sync_on_disposition}
                                        onChange={(event) =>
                                            setForm((prev) => ({ ...prev, auto_sync_on_disposition: event.target.checked }))
                                        }
                                    />
                                }
                                label="Auto sync when notes/outcome saved"
                            />
                        </Grid>
                    </Grid>

                    <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap' }}>
                        <Button
                            variant="contained"
                            onClick={handleSave}
                            disabled={loading || saving || testing || clearingToken}
                        >
                            {saving ? 'Saving...' : 'Save Settings'}
                        </Button>
                        <Button
                            variant="outlined"
                            onClick={handleTest}
                            disabled={loading || saving || testing || clearingToken}
                        >
                            {testing ? 'Testing...' : 'Test Connection'}
                        </Button>
                        <Button
                            variant="outlined"
                            color="error"
                            onClick={handleClearToken}
                            disabled={loading || saving || testing || clearingToken || !settingsMeta.access_token_configured}
                        >
                            {clearingToken ? 'Clearing...' : 'Clear Token'}
                        </Button>
                    </Stack>

                    {settingsMeta.updated_at ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
                            Last updated: {new Date(settingsMeta.updated_at).toLocaleString()}
                        </Typography>
                    ) : null}
                </CardContent>
            </Card>
        </Box>
    );
}
