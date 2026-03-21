import React, { useEffect, useState } from 'react';
import {
    Avatar, Box, Card, CardContent, Typography, Grid, Chip, Button,
    InputAdornment, LinearProgress, Tab, Tabs, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, IconButton, TextField, Tooltip,
    CircularProgress, Alert
} from '@mui/material';
import {
    ArrowBack, PlayArrow, Pause, Refresh, Download, Dialpad, Delete, RestartAlt,
    People, Phone, CheckCircle, Search, TrendingUp
} from '@mui/icons-material';
import { useParams, useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, Tooltip as ReTooltip, ResponsiveContainer } from 'recharts';
import api from '../services/api';
import toast from 'react-hot-toast';
import { CALL_STATUS_COLORS, normalizeCallStatus, formatCallStatus, formatSeconds } from '../lib/callStatus';
import { shortDateTime } from '../lib/formatDate';
import { resolveMediaUrl } from '../lib/mediaUrl';
import CallDetailDialog from '../components/CallDetailDialog';
import useConfirm from '../lib/useConfirm';
import useVisibleInterval from '../lib/useVisibleInterval';

const STATUS_COLORS = {
    active: { color: '#10b981', bg: '#10b98115', label: 'Active' },
    paused: { color: '#f59e0b', bg: '#f59e0b15', label: 'Paused' },
    completed: { color: '#0142a2', bg: '#0142a215', label: 'Completed' },
    draft: { color: '#64748b', bg: '#64748b15', label: 'Draft' },
};

/* ── Stat card with icon ── */
function StatCard({ label, value, color, icon }) {
    return (
        <Box sx={{
            p: 2, borderRadius: 2, bgcolor: `${color}08`,
            border: `1px solid ${color}20`, display: 'flex', alignItems: 'center', gap: 1.5,
        }}>
            <Box sx={{ width: 40, height: 40, borderRadius: 2, bgcolor: `${color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                {React.cloneElement(icon, { sx: { color, fontSize: 20 } })}
            </Box>
            <Box>
                <Typography variant="h5" fontWeight={800} color={color} sx={{ lineHeight: 1.2 }}>{value}</Typography>
                <Typography variant="caption" color="text.secondary">{label}</Typography>
            </Box>
        </Box>
    );
}

export default function CampaignDetailPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [campaign, setCampaign] = useState(null);
    const [analytics, setAnalytics] = useState(null);
    const [contacts, setContacts] = useState([]);
    const [callLogs, setCallLogs] = useState([]);
    const [tab, setTab] = useState(0);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [selectedCall, setSelectedCall] = useState(null);
    const [deletingContactId, setDeletingContactId] = useState(null);
    const [cooldownSeconds, setCooldownSeconds] = useState(0);
    const [campaignLoadError, setCampaignLoadError] = useState('');
    const [syncingLogs, setSyncingLogs] = useState(false);
    const [confirm, ConfirmEl] = useConfirm();
    const [contactSearch, setContactSearch] = useState('');

    const fetchData = async ({ silent = false } = {}) => {
        if (!silent) setLoading(true);
        try {
            const campRes = await api.get(`/campaigns/${id}/`);
            setCampaign(campRes.data);
            setCampaignLoadError('');
            const [analyticsRes, contactsRes, logsRes] = await Promise.allSettled([
                api.get(`/campaigns/${id}/analytics/`),
                api.get(`/contacts/?campaign=${id}`),
                api.get(`/call-logs/?campaign=${id}`),
            ]);
            setAnalytics(analyticsRes.status === 'fulfilled' ? analyticsRes.value.data : null);
            setContacts(contactsRes.status === 'fulfilled' ? (contactsRes.value.data.results || contactsRes.value.data || []) : []);
            setCallLogs(logsRes.status === 'fulfilled' ? (logsRes.value.data.results || logsRes.value.data || []) : []);
        } catch (e) {
            if (e?.response?.status === 404) { setCampaign(null); setCampaignLoadError('Campaign not found'); }
            else if (!silent) { setCampaignLoadError('Failed to load campaign'); toast.error(e?.response?.data?.error || 'Failed to load campaign'); }
        } finally {
            if (!silent) setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, [id]);

    useEffect(() => {
        if (!campaign?.next_dispatch_at) { setCooldownSeconds(Number(campaign?.cooldown_remaining_seconds || 0)); return undefined; }
        const computeRemaining = () => { const ms = new Date(campaign.next_dispatch_at).getTime() - Date.now(); return ms > 0 ? Math.ceil(ms / 1000) : 0; };
        setCooldownSeconds(computeRemaining());
        const timer = setInterval(() => setCooldownSeconds(computeRemaining()), 1000);
        return () => clearInterval(timer);
    }, [campaign?.next_dispatch_at, campaign?.cooldown_remaining_seconds]);

    const shouldPoll = campaign && (campaign.status === 'active' || Number(campaign.in_progress_contacts || 0) > 0);
    useVisibleInterval(async () => {
        try { await api.post(`/campaigns/${id}/tick/`); } catch {}
        fetchData({ silent: true });
    }, shouldPoll ? 5000 : null);

    const handleAction = async (action) => {
        setActionLoading(true);
        try {
            await api.post(`/campaigns/${id}/${action}/`);
            toast.success(`Campaign ${({ start: 'started', resume: 'resumed', pause: 'paused', stop: 'stopped' })[action] || 'updated'}`);
            fetchData({ silent: true });
        } catch (e) { toast.error(e.response?.data?.error || `Failed to ${action}`); }
        finally { setActionLoading(false); }
    };

    const handleStartFromFirst = async () => {
        const ok = await confirm({ title: 'Restart Campaign', body: 'This will reset current queue progress and start dialing from the first contact.', confirmLabel: 'Restart', confirmColor: 'warning' });
        if (!ok) return;
        setActionLoading(true);
        try { await api.post(`/campaigns/${id}/restart-from-first/`, { start_now: true }); toast.success('Campaign restarted'); fetchData({ silent: true }); }
        catch (e) { toast.error(e?.response?.data?.error || 'Failed to restart'); }
        finally { setActionLoading(false); }
    };

    const handleRemoveContact = async (contact) => {
        const contactName = contact?.name || contact?.full_name || `Contact #${contact?.id || ''}`;
        const ok = await confirm({ title: 'Remove Contact', body: `"${contactName}" will be removed from this campaign.`, confirmLabel: 'Remove' });
        if (!ok) return;
        setDeletingContactId(contact.id);
        try { await api.post(`/campaigns/${id}/contacts/${contact.id}/remove/`); toast.success('Contact removed'); fetchData({ silent: true }); }
        catch (e) { toast.error(e?.response?.data?.error === 'contact_call_in_progress' ? 'Active call — try later.' : (e?.response?.data?.error || 'Failed to remove')); }
        finally { setDeletingContactId(null); }
    };

    const handleSyncExotelLogs = async () => {
        setSyncingLogs(true);
        try {
            const { data } = await api.post('/call-logs/sync/exotel/', { campaign_id: Number(id), limit: 100, only_open: false });
            toast.success(`Sync complete. Updated: ${data?.updated || 0}`);
            fetchData({ silent: true });
        } catch (e) { toast.error(e?.response?.data?.error || 'Sync failed'); }
        finally { setSyncingLogs(false); }
    };

    const pieData = analytics ? [
        { name: 'Answered', value: analytics.answered_calls, color: '#10b981' },
        { name: 'Failed', value: analytics.failed_calls, color: '#ef4444' },
        { name: 'No Answer', value: Math.max(0, analytics.total_calls - analytics.answered_calls - analytics.failed_calls), color: '#f59e0b' },
    ].filter((d) => d.value > 0) : [];

    const activeCall = campaign?.active_call || null;
    const activeCallDisplayStatus = normalizeCallStatus(activeCall?.display_status || activeCall?.status);
    const waitingForPickup = activeCall?.stage === 'waiting_for_pickup' && !activeCall?.answered_at
        && !['answered', 'completed', 'sdr-cut', 'bridged', 'human-detected'].includes(activeCallDisplayStatus);
    const pickupLeftSeconds = Number(activeCall?.pickup_seconds_left || 0);
    const lastCallStatus = normalizeCallStatus(campaign?.last_call_result?.display_status);

    if (loading) return <Box sx={{ p: 4, textAlign: 'center' }}><CircularProgress sx={{ color: '#0142a2' }} /></Box>;
    if (!campaign) return <Alert severity="error">{campaignLoadError || 'Campaign not found'}</Alert>;

    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                <IconButton onClick={() => navigate('/campaigns')} sx={{ color: '#64748b' }}><ArrowBack /></IconButton>
                <Box sx={{ flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
                        <Typography variant="h4" fontWeight={800}>{campaign.name}</Typography>
                        <Chip label={statusCfg.label} size="small" sx={{ bgcolor: statusCfg.bg, color: statusCfg.color, fontWeight: 700 }} />
                        <Chip label={`${campaign.dialing_mode} dialer`} size="small" variant="outlined" sx={{ borderColor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' }} />
                    </Box>
                    <Typography color="text.secondary" variant="body2">
                        {campaign.description || 'No description'} · SDR: {campaign.assigned_agent_details?.full_name || 'Unassigned'}
                    </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1, flexShrink: 0 }}>
                    <Tooltip title="Refresh"><IconButton onClick={fetchData} sx={{ color: '#64748b' }}><Refresh /></IconButton></Tooltip>
                    <Button variant="outlined" startIcon={<Dialpad />} onClick={() => navigate(`/dial?campaign_id=${id}`)} sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}>Dialer</Button>
                    <Button variant="outlined" startIcon={<RestartAlt />} onClick={handleStartFromFirst} disabled={actionLoading || !campaign?.total_contacts} sx={{ borderColor: 'rgba(59,130,246,0.3)', color: '#60a5fa' }}>Restart</Button>
                    {campaign.status === 'draft' && <Button variant="contained" startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <PlayArrow />} onClick={() => handleAction('start')} disabled={actionLoading} sx={{ bgcolor: '#10b981', '&:hover': { bgcolor: '#059669' } }}>Start</Button>}
                    {campaign.status === 'active' && <Button variant="outlined" startIcon={<Pause />} onClick={() => handleAction('pause')} disabled={actionLoading} sx={{ borderColor: '#f59e0b', color: '#f59e0b' }}>Pause</Button>}
                    {campaign.status === 'paused' && <Button variant="contained" startIcon={<PlayArrow />} onClick={() => handleAction('resume')} disabled={actionLoading} sx={{ bgcolor: '#10b981', '&:hover': { bgcolor: '#059669' } }}>Resume</Button>}
                </Box>
            </Box>

            {/* Active campaign live strip */}
            {campaign.status === 'active' && (
                <Box sx={{ mb: 2, p: 2, borderRadius: 2, bgcolor: 'rgba(16,185,129,0.06)', border: '1px solid rgba(16,185,129,0.2)' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Chip label="LIVE" size="small" sx={{ bgcolor: '#10b98120', color: '#10b981', fontWeight: 800, letterSpacing: '0.05em' }} />
                        <Typography variant="body2" color="text.secondary">
                            {campaign.dialed_contacts}/{campaign.total_contacts} dialed · {campaign.progress_percentage}%
                        </Typography>
                    </Box>
                    <LinearProgress value={campaign.progress_percentage} variant="determinate"
                        sx={{ height: 6, borderRadius: 4, bgcolor: 'rgba(16,185,129,0.1)', mb: 1, '& .MuiLinearProgress-bar': { bgcolor: '#10b981', borderRadius: 4 } }} />
                    <Typography variant="caption" color="text.secondary">
                        {campaign.active_call_in_progress
                            ? waitingForPickup ? `Waiting ${formatSeconds(pickupLeftSeconds)}...` : `In call${activeCall?.contact_name ? ` with ${activeCall.contact_name}` : ''}`
                            : cooldownSeconds > 0 ? `Cooldown: next call in ${formatSeconds(cooldownSeconds)}` : 'Dispatching next contact...'}
                    </Typography>
                </Box>
            )}

            {/* Stats row */}
            <Grid container spacing={1.5} sx={{ mb: 2 }}>
                <Grid item xs={6} sm={3}><StatCard label="Total Contacts" value={campaign.total_contacts} color="#0142a2" icon={<People />} /></Grid>
                <Grid item xs={6} sm={3}><StatCard label="Dialed" value={campaign.dialed_contacts} color="#3b82f6" icon={<Phone />} /></Grid>
                <Grid item xs={6} sm={3}><StatCard label="Connected" value={campaign.connected_calls} color="#10b981" icon={<CheckCircle />} /></Grid>
                <Grid item xs={6} sm={3}><StatCard label="Connect Rate" value={`${campaign.connect_rate}%`} color="#f59e0b" icon={<TrendingUp />} /></Grid>
            </Grid>

            {/* Tabs */}
            <Card>
                <Tabs value={tab} onChange={(_, v) => setTab(v)}
                    sx={{ borderBottom: '1px solid rgba(1,66,162,0.08)',
                        '& .MuiTab-root': { textTransform: 'none', fontWeight: 600, color: '#94a3b8', minHeight: 48 },
                        '& .Mui-selected': { color: '#0142a2' }, '& .MuiTabs-indicator': { bgcolor: '#0142a2', height: 3, borderRadius: '3px 3px 0 0' } }}>
                    <Tab label={`Contacts (${contacts.length})`} />
                    <Tab label={`Call Logs (${callLogs.length})`} />
                    <Tab label="Analytics" />
                </Tabs>

                {/* Contacts tab */}
                {tab === 0 && (() => {
                    const filteredContacts = contacts.filter((c) => !contactSearch.trim() || [c.name, c.phone, c.company].some((v) => (v || '').toLowerCase().includes(contactSearch.toLowerCase())));
                    return (
                    <Box>
                        <Box sx={{ p: 1.5, display: 'flex', justifyContent: 'flex-end' }}>
                            <TextField size="small" placeholder="Search contacts..."
                                value={contactSearch} onChange={(e) => setContactSearch(e.target.value)}
                                InputProps={{ startAdornment: <InputAdornment position="start"><Search sx={{ color: '#94a3b8', fontSize: 16 }} /></InputAdornment> }}
                                sx={{ width: 250 }} />
                        </Box>
                    <TableContainer>
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    <TableCell>#</TableCell><TableCell>Name</TableCell><TableCell>Phone</TableCell>
                                    <TableCell>Company</TableCell><TableCell>Status</TableCell><TableCell>Retries</TableCell>
                                    <TableCell>Last Called</TableCell><TableCell align="right">Action</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {filteredContacts.length === 0 ? (
                                    <TableRow><TableCell colSpan={8} align="center" sx={{ py: 4, color: '#94a3b8' }}>{contactSearch ? 'No contacts match your search' : 'No contacts added yet. Add contacts to start dialing.'}</TableCell></TableRow>
                                ) : filteredContacts.map((c, i) => {
                                    const statusKey = normalizeCallStatus(c.status);
                                    const statusColor = CALL_STATUS_COLORS[statusKey] || '#64748b';
                                    return (
                                        <TableRow key={c.id} hover sx={{ borderLeft: `3px solid ${statusColor}` }}>
                                            <TableCell sx={{ color: '#94a3b8', fontSize: '0.8rem' }}>{i + 1}</TableCell>
                                            <TableCell><Typography fontWeight={600} fontSize="0.85rem">{c.name}</Typography></TableCell>
                                            <TableCell><Typography fontSize="0.85rem" fontFamily="monospace">{c.phone}</Typography></TableCell>
                                            <TableCell><Typography fontSize="0.85rem" color="text.secondary">{c.company || '—'}</Typography></TableCell>
                                            <TableCell>
                                                <Chip label={formatCallStatus(c.status)} size="small"
                                                    sx={{ bgcolor: `${statusColor}15`, color: statusColor, fontWeight: 600, fontSize: '0.65rem' }} />
                                            </TableCell>
                                            <TableCell><Typography fontSize="0.85rem">{c.retry_count}</Typography></TableCell>
                                            <TableCell><Typography fontSize="0.75rem" color="text.secondary">{c.last_called_at ? shortDateTime(c.last_called_at) : '—'}</Typography></TableCell>
                                            <TableCell align="right">
                                                <Tooltip title="Remove from campaign"><span>
                                                    <IconButton size="small" onClick={() => handleRemoveContact(c)} disabled={deletingContactId === c.id} sx={{ color: '#ef4444' }}>
                                                        {deletingContactId === c.id ? <CircularProgress size={16} color="inherit" /> : <Delete fontSize="small" />}
                                                    </IconButton>
                                                </span></Tooltip>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    </TableContainer>
                    </Box>
                    );
                })()}

                {/* Call Logs tab */}
                {tab === 1 && (
                    <Box>
                        <Box sx={{ display: 'flex', justifyContent: 'flex-end', p: 1.5 }}>
                            <Tooltip title="Fetch latest call status and recordings from Exotel"><span>
                                <Button variant="outlined" size="small"
                                    startIcon={syncingLogs ? <CircularProgress size={14} color="inherit" /> : <Refresh />}
                                    onClick={handleSyncExotelLogs} disabled={syncingLogs}
                                    sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}>
                                    {syncingLogs ? 'Syncing...' : 'Sync Exotel'}
                                </Button>
                            </span></Tooltip>
                        </Box>
                        <TableContainer>
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Contact</TableCell><TableCell>SDR</TableCell><TableCell>Status</TableCell>
                                        <TableCell>Duration</TableCell><TableCell>Recording</TableCell><TableCell>Transcript</TableCell><TableCell>Time</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {callLogs.length === 0 ? (
                                        <TableRow><TableCell colSpan={7} align="center" sx={{ py: 4, color: '#94a3b8' }}>No calls yet. Start the campaign to begin dialing.</TableCell></TableRow>
                                    ) : callLogs.map((log) => {
                                        const statusKey = normalizeCallStatus(log.status);
                                        const statusColor = CALL_STATUS_COLORS[statusKey] || '#64748b';
                                        return (
                                            <TableRow key={log.id} hover onClick={() => setSelectedCall(log)}
                                                sx={{ cursor: 'pointer', borderLeft: `3px solid ${statusColor}` }}>
                                                <TableCell>
                                                    <Typography fontWeight={600} fontSize="0.85rem">{log.contact_name}</Typography>
                                                    <Typography fontSize="0.72rem" color="text.secondary">{log.contact_phone}</Typography>
                                                </TableCell>
                                                <TableCell><Typography fontSize="0.85rem">{log.agent_name}</Typography></TableCell>
                                                <TableCell><Chip label={formatCallStatus(log.status)} size="small" sx={{ bgcolor: `${statusColor}15`, color: statusColor, fontWeight: 600, fontSize: '0.65rem' }} /></TableCell>
                                                <TableCell><Typography fontSize="0.85rem" fontFamily="monospace">{log.duration_formatted}</Typography></TableCell>
                                                <TableCell>
                                                    {log.recording_url ? (
                                                        <IconButton size="small" href={resolveMediaUrl(log.recording_url)} target="_blank" sx={{ color: '#0142a2' }} onClick={(e) => e.stopPropagation()}>
                                                            <Download fontSize="small" />
                                                        </IconButton>
                                                    ) : <Typography fontSize="0.75rem" color="text.disabled">—</Typography>}
                                                </TableCell>
                                                <TableCell>
                                                    {log.transcript_status === 'completed' ? <Chip label="Done" size="small" sx={{ bgcolor: '#10b98115', color: '#10b981', fontSize: '0.65rem', fontWeight: 600 }} />
                                                        : log.transcript_status === 'processing' ? <Chip label="Processing" size="small" sx={{ bgcolor: '#f59e0b15', color: '#f59e0b', fontSize: '0.65rem' }} />
                                                            : <Typography fontSize="0.75rem" color="text.disabled">—</Typography>}
                                                </TableCell>
                                                <TableCell><Typography fontSize="0.72rem" color="text.secondary">{shortDateTime(log.initiated_at)}</Typography></TableCell>
                                            </TableRow>
                                        );
                                    })}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    </Box>
                )}

                {/* Analytics tab */}
                {tab === 2 && (
                    <CardContent>
                        {analytics ? (
                            <Grid container spacing={3}>
                                <Grid item xs={12} md={5}>
                                    <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                        Call Outcomes
                                    </Typography>
                                    {pieData.length > 0 ? (
                                        <Box>
                                            <ResponsiveContainer width="100%" height={200}>
                                                <PieChart>
                                                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={80} paddingAngle={3} dataKey="value" strokeWidth={0}>
                                                        {pieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                                                    </Pie>
                                                    <ReTooltip contentStyle={{ background: '#fff', border: 'none', borderRadius: 8, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                                                </PieChart>
                                            </ResponsiveContainer>
                                            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap', mt: 1 }}>
                                                {pieData.map((d) => (
                                                    <Box key={d.name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: d.color }} />
                                                        <Typography variant="caption">{d.name}: {d.value}</Typography>
                                                    </Box>
                                                ))}
                                            </Box>
                                        </Box>
                                    ) : (
                                        <Box sx={{ textAlign: 'center', py: 6, color: '#94a3b8' }}>No call data yet</Box>
                                    )}
                                </Grid>
                                <Grid item xs={12} md={7}>
                                    <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                        Summary
                                    </Typography>
                                    <Grid container spacing={1.5}>
                                        {[
                                            { label: 'Total Calls', value: analytics.total_calls, color: '#0142a2', icon: <Phone /> },
                                            { label: 'Answered', value: analytics.answered_calls, color: '#10b981', icon: <CheckCircle /> },
                                            { label: 'Connect Rate', value: `${analytics.connect_rate}%`, color: '#f59e0b', icon: <TrendingUp /> },
                                            { label: 'Avg Duration', value: `${analytics.avg_duration_seconds}s`, color: '#3b82f6', icon: <Phone /> },
                                        ].map((stat) => (
                                            <Grid item xs={6} key={stat.label}>
                                                <StatCard label={stat.label} value={stat.value} color={stat.color} icon={stat.icon} />
                                            </Grid>
                                        ))}
                                    </Grid>
                                </Grid>
                            </Grid>
                        ) : (
                            <Box sx={{ textAlign: 'center', py: 6, color: '#94a3b8' }}>Analytics data unavailable</Box>
                        )}
                    </CardContent>
                )}
            </Card>

            <CallDetailDialog call={selectedCall} onClose={() => setSelectedCall(null)} />
            {ConfirmEl}
        </Box>
    );
}
