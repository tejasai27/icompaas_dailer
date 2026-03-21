import React, { useEffect, useState } from 'react';
import {
    Alert, Avatar, Box, Button, Card, CardContent, Chip,
    Divider, FormControlLabel, Grid, IconButton, Switch, Tooltip, Typography,
} from '@mui/material';
import { Hub, Link as LinkIcon, LinkOff, Refresh, Settings } from '@mui/icons-material';
import toast from 'react-hot-toast';
import api from '../services/api';
import { relativeTime } from '../lib/formatDate';
import useConfirm from '../lib/useConfirm';

const DEFAULT_FORM = { enabled: false, auto_sync_terminal_calls: true, auto_sync_on_disposition: true };

export default function IntegrationsPage() {
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [testing, setTesting] = useState(false);
    const [clearingToken, setClearingToken] = useState(false);
    const [form, setForm] = useState(DEFAULT_FORM);
    const [settingsMeta, setSettingsMeta] = useState({ access_token_configured: false, access_token_masked: '', access_token_source: 'none', updated_at: '' });
    const [connectionStatus, setConnectionStatus] = useState({ state: 'unknown', message: 'Not checked yet', checked_at: '' });
    const [settingsWarning, setSettingsWarning] = useState('');
    const [confirm, ConfirmEl] = useConfirm();

    const runConnectionCheck = async ({ silent = false, hasTokenOverride } = {}) => {
        const hasToken = typeof hasTokenOverride === 'boolean' ? hasTokenOverride : Boolean(settingsMeta.access_token_configured);
        if (!hasToken) { setConnectionStatus({ state: 'disconnected', message: 'No HubSpot token configured', checked_at: '' }); if (!silent) toast.error('HubSpot token missing'); return false; }
        setConnectionStatus({ state: 'checking', message: 'Checking...', checked_at: '' });
        setTesting(true);
        try {
            const { data } = await api.post('/integrations/hubspot/test/', {});
            const sample = data?.sample_deal?.name ? ` · Sample deal: ${data.sample_deal.name}` : '';
            setConnectionStatus({ state: 'connected', message: `Connected${sample}`, checked_at: new Date().toISOString() });
            if (!silent) toast.success('HubSpot connected');
            return true;
        } catch (error) {
            const msg = error?.response?.data?.details?.error || error?.response?.data?.error || 'Connection failed';
            setConnectionStatus({ state: 'disconnected', message: msg, checked_at: new Date().toISOString() });
            if (!silent) toast.error(msg);
            return false;
        } finally { setTesting(false); }
    };

    const loadSettings = async ({ silent = false } = {}) => {
        if (!silent) setLoading(true);
        try {
            const { data } = await api.get('/integrations/hubspot/settings/');
            const s = data?.settings || {};
            setSettingsWarning(String(data?.warning || '').trim());
            setForm({ enabled: Boolean(s.enabled), auto_sync_terminal_calls: s.auto_sync_terminal_calls !== false, auto_sync_on_disposition: s.auto_sync_on_disposition !== false });
            setSettingsMeta({ access_token_configured: Boolean(s.access_token_configured), access_token_masked: s.access_token_masked || '', access_token_source: s.access_token_source || 'none', updated_at: s.updated_at || '' });
            if (s.access_token_configured) void runConnectionCheck({ silent: true, hasTokenOverride: true });
            else setConnectionStatus({ state: 'disconnected', message: 'No token configured', checked_at: '' });
        } catch (error) {
            if (!silent) toast.error(error?.response?.data?.error || 'Failed to load settings');
        } finally { if (!silent) setLoading(false); }
    };

    useEffect(() => { loadSettings(); }, []);

    const handleSave = async () => {
        setSaving(true);
        try {
            const { data } = await api.post('/integrations/hubspot/settings/', form);
            const s = data?.settings || {};
            setSettingsMeta({ access_token_configured: Boolean(s.access_token_configured), access_token_masked: s.access_token_masked || '', access_token_source: s.access_token_source || 'none', updated_at: s.updated_at || '' });
            toast.success('Settings saved');
            if (s.access_token_configured) await runConnectionCheck({ silent: true, hasTokenOverride: true });
        } catch (error) { toast.error(error?.response?.data?.error || 'Save failed'); }
        finally { setSaving(false); }
    };

    const handleClearToken = async () => {
        const ok = await confirm({ title: 'Clear HubSpot Token', body: 'This will disconnect HubSpot. Calls will no longer sync until a new token is configured.', confirmLabel: 'Clear Token', confirmColor: 'error' });
        if (!ok) return;
        setClearingToken(true);
        try {
            const { data } = await api.post('/integrations/hubspot/settings/', { clear_access_token: true });
            const s = data?.settings || {};
            setSettingsMeta({ access_token_configured: Boolean(s.access_token_configured), access_token_masked: s.access_token_masked || '', access_token_source: s.access_token_source || 'none', updated_at: s.updated_at || '' });
            toast.success('Token cleared');
            setConnectionStatus({ state: 'disconnected', message: 'No token configured', checked_at: '' });
        } catch (error) { toast.error(error?.response?.data?.error || 'Failed to clear'); }
        finally { setClearingToken(false); }
    };

    const connColor = connectionStatus.state === 'connected' ? '#10b981' : connectionStatus.state === 'checking' ? '#3b82f6' : connectionStatus.state === 'unknown' ? '#f59e0b' : '#ef4444';
    const connLabel = connectionStatus.state === 'connected' ? 'Connected' : connectionStatus.state === 'checking' ? 'Checking...' : connectionStatus.state === 'unknown' ? 'Unknown' : 'Disconnected';
    const isBusy = loading || saving || testing || clearingToken;

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Integrations</Typography>
                    <Typography color="text.secondary" variant="body2">Connect third-party services to your dialer</Typography>
                </Box>
                <Tooltip title="Refresh settings">
                    <IconButton onClick={() => loadSettings()} disabled={isBusy} sx={{ color: '#64748b' }}>
                        <Refresh />
                    </IconButton>
                </Tooltip>
            </Box>

            {/* Integration card grid (marketplace style) */}
            <Grid container spacing={2}>
                {/* HubSpot card */}
                <Grid item xs={12} md={8}>
                    <Card>
                        <CardContent>
                            {/* Card header */}
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                                <Avatar sx={{ width: 48, height: 48, bgcolor: '#f59e0b15' }}>
                                    <Hub sx={{ color: '#f59e0b', fontSize: 26 }} />
                                </Avatar>
                                <Box sx={{ flex: 1 }}>
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Typography variant="h6" fontWeight={700}>HubSpot</Typography>
                                        <Chip size="small" label={connLabel} sx={{ bgcolor: `${connColor}15`, color: connColor, fontWeight: 600, fontSize: '0.65rem' }} />
                                    </Box>
                                    <Typography variant="caption" color="text.secondary">Sync calls as activities to HubSpot CRM</Typography>
                                </Box>
                                <Box sx={{ display: 'flex', gap: 0.5 }}>
                                    <Chip size="small" label={form.enabled ? 'Enabled' : 'Disabled'}
                                        sx={{ bgcolor: form.enabled ? '#10b98115' : '#94a3b820', color: form.enabled ? '#10b981' : '#94a3b8', fontWeight: 600, fontSize: '0.65rem' }} />
                                    <Chip size="small" label={settingsMeta.access_token_configured ? 'Token Set' : 'No Token'}
                                        icon={settingsMeta.access_token_configured ? <LinkIcon sx={{ fontSize: 14 }} /> : <LinkOff sx={{ fontSize: 14 }} />}
                                        sx={{ bgcolor: settingsMeta.access_token_configured ? '#10b98115' : '#ef444415', color: settingsMeta.access_token_configured ? '#10b981' : '#ef4444', fontWeight: 600, fontSize: '0.65rem', '& .MuiChip-icon': { color: 'inherit' } }} />
                                </Box>
                            </Box>

                            {settingsWarning && <Alert severity="warning" sx={{ mb: 2, borderRadius: 2 }}>{settingsWarning}</Alert>}

                            {/* Connection status */}
                            <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: `${connColor}08`, border: `1px solid ${connColor}20`, mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: connColor }} />
                                <Typography variant="body2" fontSize="0.85rem">
                                    {connectionStatus.message}
                                    {connectionStatus.checked_at ? <Typography component="span" variant="caption" color="text.secondary"> · checked {relativeTime(connectionStatus.checked_at)}</Typography> : null}
                                </Typography>
                            </Box>

                            <Divider sx={{ my: 2, borderColor: 'rgba(1,66,162,0.06)' }} />

                            {/* Settings toggles */}
                            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1.5, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                Sync Settings
                            </Typography>
                            <Grid container spacing={1}>
                                {[
                                    { key: 'enabled', label: 'Enable HubSpot integration', desc: 'Master toggle for all HubSpot sync' },
                                    { key: 'auto_sync_terminal_calls', label: 'Auto sync on call end', desc: 'Sync call data when a call completes' },
                                    { key: 'auto_sync_on_disposition', label: 'Auto sync on disposition', desc: 'Sync when notes or outcome are saved' },
                                ].map((toggle) => (
                                    <Grid item xs={12} key={toggle.key}>
                                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', py: 0.75, px: 1, borderRadius: 1.5, '&:hover': { bgcolor: 'rgba(1,66,162,0.03)' } }}>
                                            <Box>
                                                <Typography fontWeight={600} fontSize="0.85rem">{toggle.label}</Typography>
                                                <Typography variant="caption" color="text.secondary">{toggle.desc}</Typography>
                                            </Box>
                                            <Switch checked={form[toggle.key]} onChange={(e) => setForm((prev) => ({ ...prev, [toggle.key]: e.target.checked }))}
                                                sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#10b981' }, '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: '#10b98150' } }} />
                                        </Box>
                                    </Grid>
                                ))}
                            </Grid>

                            <Divider sx={{ my: 2, borderColor: 'rgba(1,66,162,0.06)' }} />

                            {/* Actions */}
                            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                                <Button variant="contained" onClick={handleSave} disabled={isBusy}
                                    sx={{ bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' } }}>
                                    {saving ? 'Saving...' : 'Save Settings'}
                                </Button>
                                <Button variant="outlined" onClick={() => runConnectionCheck({ silent: false })} disabled={isBusy}
                                    sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}>
                                    {testing ? 'Testing...' : 'Test Connection'}
                                </Button>
                                <Tooltip title="Remove token. Calls will stop syncing until reconfigured."><span>
                                    <Button variant="outlined" color="error" onClick={handleClearToken}
                                        disabled={isBusy || !settingsMeta.access_token_configured}>
                                        {clearingToken ? 'Clearing...' : 'Clear Token'}
                                    </Button>
                                </span></Tooltip>
                            </Box>

                            {settingsMeta.updated_at && (
                                <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 2 }}>
                                    Last updated: {relativeTime(settingsMeta.updated_at)}
                                </Typography>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                {/* Coming soon cards */}
                <Grid item xs={12} md={4}>
                    <Box sx={{ display: 'grid', gap: 2 }}>
                        {[
                            { name: 'Salesforce', color: '#0176d3', desc: 'Sync calls and contacts with Salesforce CRM' },
                            { name: 'Slack', color: '#4a154b', desc: 'Get call notifications in Slack channels' },
                        ].map((integration) => (
                            <Card key={integration.name} sx={{ opacity: 0.6, border: '1px dashed rgba(1,66,162,0.15)' }}>
                                <CardContent sx={{ py: 2, '&:last-child': { pb: 2 } }}>
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                                        <Avatar sx={{ width: 36, height: 36, bgcolor: `${integration.color}15`, fontSize: '0.8rem', fontWeight: 700, color: integration.color }}>
                                            {integration.name[0]}
                                        </Avatar>
                                        <Box>
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                                                <Typography fontWeight={700} fontSize="0.85rem">{integration.name}</Typography>
                                                <Chip label="Coming Soon" size="small" sx={{ height: 18, fontSize: '0.6rem', bgcolor: '#f59e0b15', color: '#f59e0b' }} />
                                            </Box>
                                            <Typography variant="caption" color="text.secondary">{integration.desc}</Typography>
                                        </Box>
                                    </Box>
                                </CardContent>
                            </Card>
                        ))}
                    </Box>
                </Grid>
            </Grid>
            {ConfirmEl}
        </Box>
    );
}
