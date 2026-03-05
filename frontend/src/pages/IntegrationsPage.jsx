import React, { useEffect, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    FormControl,
    FormControlLabel,
    Grid,
    InputLabel,
    MenuItem,
    Select,
    Stack,
    Switch,
    TextField,
    Typography,
} from '@mui/material';
import { Hub, Refresh } from '@mui/icons-material';
import toast from 'react-hot-toast';
import api from '../services/api';

const DEFAULT_FORM = {
    enabled: false,
    deal_association_mode: 'deal_id',
    default_deal_id: '',
    default_deal_name: '',
    auto_sync_terminal_calls: true,
    auto_sync_on_disposition: true,
};

export default function IntegrationsPage() {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [clearingToken, setClearingToken] = useState(false);
    const [form, setForm] = useState(DEFAULT_FORM);
    const [tokenInput, setTokenInput] = useState('');
    const [settingsMeta, setSettingsMeta] = useState({
        access_token_configured: false,
        access_token_masked: '',
        access_token_source: 'none',
        updated_at: '',
    });

    const loadSettings = async ({ silent = false } = {}) => {
        if (!silent) setLoading(true);
        try {
            const { data } = await api.get('/integrations/hubspot/settings/');
            const settings = data?.settings || {};
            setForm({
                enabled: Boolean(settings.enabled),
                deal_association_mode: settings.deal_association_mode || 'deal_id',
                default_deal_id: settings.default_deal_id || '',
                default_deal_name: settings.default_deal_name || '',
                auto_sync_terminal_calls: settings.auto_sync_terminal_calls !== false,
                auto_sync_on_disposition: settings.auto_sync_on_disposition !== false,
            });
            setSettingsMeta({
                access_token_configured: Boolean(settings.access_token_configured),
                access_token_masked: settings.access_token_masked || '',
                access_token_source: settings.access_token_source || 'none',
                updated_at: settings.updated_at || '',
            });
            setTokenInput('');
        } catch (error) {
            if (!silent) {
                toast.error(error?.response?.data?.error || 'Failed to load HubSpot settings');
            }
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
                deal_association_mode: form.deal_association_mode,
                default_deal_id: form.default_deal_id,
                default_deal_name: form.default_deal_name,
                auto_sync_terminal_calls: form.auto_sync_terminal_calls,
                auto_sync_on_disposition: form.auto_sync_on_disposition,
            };
            if (tokenInput.trim()) {
                payload.access_token = tokenInput.trim();
            }
            const { data } = await api.post('/integrations/hubspot/settings/', payload);
            const settings = data?.settings || {};
            setSettingsMeta({
                access_token_configured: Boolean(settings.access_token_configured),
                access_token_masked: settings.access_token_masked || '',
                access_token_source: settings.access_token_source || 'none',
                updated_at: settings.updated_at || '',
            });
            setTokenInput('');
            toast.success('HubSpot settings saved');
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to save HubSpot settings');
        } finally {
            setSaving(false);
        }
    };

    const handleTest = async () => {
        setTesting(true);
        try {
            const payload = {};
            if (tokenInput.trim()) {
                payload.access_token = tokenInput.trim();
            }
            const { data } = await api.post('/integrations/hubspot/test/', payload);
            const sampleName = data?.sample_deal?.name ? ` Sample deal: ${data.sample_deal.name}` : '';
            toast.success(`HubSpot connection successful.${sampleName}`);
        } catch (error) {
            toast.error(error?.response?.data?.error || 'HubSpot connection failed');
        } finally {
            setTesting(false);
        }
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
            setTokenInput('');
            toast.success('HubSpot token cleared from DB settings');
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to clear token');
        } finally {
            setClearingToken(false);
        }
    };

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
                            label={settingsMeta.access_token_configured ? 'Token Configured' : 'Token Missing'}
                            sx={{
                                bgcolor: settingsMeta.access_token_configured ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)',
                                color: settingsMeta.access_token_configured ? '#10b981' : '#ef4444',
                            }}
                        />
                    </Stack>

                    <Alert severity="info" sx={{ mb: 2 }}>
                        Calls are synced to HubSpot as Call activities. Association can use Deal ID or Deal Name.
                    </Alert>

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
                        <Grid item xs={12} md={6}>
                            <FormControl fullWidth size="small">
                                <InputLabel>Deal Association Mode</InputLabel>
                                <Select
                                    label="Deal Association Mode"
                                    value={form.deal_association_mode}
                                    onChange={(event) =>
                                        setForm((prev) => ({ ...prev, deal_association_mode: event.target.value }))
                                    }
                                >
                                    <MenuItem value="deal_id">Deal ID</MenuItem>
                                    <MenuItem value="deal_name">Deal Name</MenuItem>
                                </Select>
                            </FormControl>
                        </Grid>
                        <Grid item xs={12} md={6}>
                            <TextField
                                fullWidth
                                size="small"
                                label="Default Deal ID (Optional)"
                                value={form.default_deal_id}
                                onChange={(event) => setForm((prev) => ({ ...prev, default_deal_id: event.target.value }))}
                            />
                        </Grid>
                        <Grid item xs={12} md={6}>
                            <TextField
                                fullWidth
                                size="small"
                                label="Default Deal Name (Optional)"
                                value={form.default_deal_name}
                                onChange={(event) => setForm((prev) => ({ ...prev, default_deal_name: event.target.value }))}
                            />
                        </Grid>
                        <Grid item xs={12}>
                            <TextField
                                fullWidth
                                size="small"
                                type="password"
                                label="HubSpot Private App Access Token"
                                value={tokenInput}
                                onChange={(event) => setTokenInput(event.target.value)}
                                helperText={
                                    settingsMeta.access_token_configured
                                        ? `Configured (${settingsMeta.access_token_source}): ${settingsMeta.access_token_masked}`
                                        : 'No token configured yet'
                                }
                                placeholder="Paste token only when updating"
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
