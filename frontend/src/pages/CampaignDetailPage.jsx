import React, { useEffect, useState } from 'react';
import {
    Box, Card, CardContent, Typography, Grid, Chip, Button,
    LinearProgress, Tab, Tabs, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, IconButton, Tooltip,
    Dialog, DialogTitle, DialogContent, DialogActions, TextField,
    Select, MenuItem, FormControl, InputLabel, CircularProgress,
    Alert
} from '@mui/material';
import {
    ArrowBack, PlayArrow, Pause, Stop, BarChart, Phone,
    Person, CheckCircle, Cancel, Timer, History, Mic,
    Edit, Refresh, Download, Dialpad, Delete, RestartAlt
} from '@mui/icons-material';
import { useParams, useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, BarChart as ReBarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer } from 'recharts';
import api from '../services/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
    active: '#10b981', paused: '#f59e0b', completed: '#0142a2', draft: '#64748b',
};
const CALL_STATUS_COLORS = {
    answered: '#10b981', 'no-answer': '#f59e0b', busy: '#ef4444', failed: '#ef4444', completed: '#0142a2', initiated: '#3b82f6',
};

function StatBadge({ label, value, color }) {
    return (
        <Box sx={{ textAlign: 'center', p: 2, borderRadius: 2, bgcolor: `${color}15`, border: `1px solid ${color}30` }}>
            <Typography variant="h4" fontWeight={700} color={color}>{value}</Typography>
            <Typography variant="caption" color="text.secondary">{label}</Typography>
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
    const [timeline, setTimeline] = useState([]);
    const [tab, setTab] = useState(0);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [selectedCall, setSelectedCall] = useState(null);
    const [deletingContactId, setDeletingContactId] = useState(null);
    const [cooldownSeconds, setCooldownSeconds] = useState(0);
    const [campaignLoadError, setCampaignLoadError] = useState('');
    const [clearingTimeline, setClearingTimeline] = useState(false);
    const [syncingLogs, setSyncingLogs] = useState(false);

    const fetchData = async ({ silent = false } = {}) => {
        if (!silent) {
            setLoading(true);
        }
        try {
            const campRes = await api.get(`/campaigns/${id}/`);
            setCampaign(campRes.data);
            setCampaignLoadError('');

            const [analyticsRes, contactsRes, logsRes, timelineRes] = await Promise.allSettled([
                api.get(`/campaigns/${id}/analytics/`),
                api.get(`/contacts/?campaign=${id}`),
                api.get(`/call-logs/?campaign=${id}`),
                api.get(`/campaigns/${id}/timeline/?limit=250`),
            ]);

            if (analyticsRes.status === 'fulfilled') {
                setAnalytics(analyticsRes.value.data);
            } else {
                setAnalytics(null);
            }

            if (contactsRes.status === 'fulfilled') {
                setContacts(contactsRes.value.data.results || contactsRes.value.data || []);
            } else {
                setContacts([]);
            }

            if (logsRes.status === 'fulfilled') {
                setCallLogs(logsRes.value.data.results || logsRes.value.data || []);
            } else {
                setCallLogs([]);
            }

            if (timelineRes.status === 'fulfilled') {
                setTimeline(timelineRes.value.data.results || []);
            } else {
                setTimeline([]);
            }
        } catch (e) {
            const status = e?.response?.status;
            if (status === 404) {
                setCampaign(null);
                setCampaignLoadError('Campaign not found');
            } else {
                if (!silent) {
                    setCampaignLoadError('Failed to load campaign');
                    toast.error(e?.response?.data?.error || 'Failed to load campaign');
                }
            }
        } finally {
            if (!silent) {
                setLoading(false);
            }
        }
    };

    useEffect(() => { fetchData(); }, [id]);

    useEffect(() => {
        if (!campaign?.next_dispatch_at) {
            setCooldownSeconds(Number(campaign?.cooldown_remaining_seconds || 0));
            return undefined;
        }

        const computeRemaining = () => {
            const ms = new Date(campaign.next_dispatch_at).getTime() - Date.now();
            return ms > 0 ? Math.ceil(ms / 1000) : 0;
        };

        setCooldownSeconds(computeRemaining());
        const timer = setInterval(() => {
            setCooldownSeconds(computeRemaining());
        }, 1000);

        return () => clearInterval(timer);
    }, [campaign?.next_dispatch_at, campaign?.cooldown_remaining_seconds]);

    // Auto-refresh while campaign is active or has in-progress queue state.
    useEffect(() => {
        if (campaign && (campaign.status === 'active' || Number(campaign.in_progress_contacts || 0) > 0)) {
            const interval = setInterval(async () => {
                try {
                    await api.post(`/campaigns/${id}/tick/`);
                } catch (_error) {
                    // Ignore intermittent tick failures; fetch still runs to refresh UI.
                }
                fetchData({ silent: true });
            }, 5000);
            return () => clearInterval(interval);
        }
    }, [campaign?.status, campaign?.in_progress_contacts, id]);

    const handleAction = async (action) => {
        setActionLoading(true);
        try {
            await api.post(`/campaigns/${id}/${action}/`);
            const actionLabel = {
                start: 'started',
                resume: 'resumed',
                pause: 'paused',
                stop: 'stopped',
            }[action] || 'updated';
            toast.success(`Campaign ${actionLabel}`);
            fetchData({ silent: true });
        } catch (e) {
            toast.error(e.response?.data?.error || `Failed to ${action}`);
        } finally {
            setActionLoading(false);
        }
    };

    const handleStartFromFirst = async () => {
        const ok = window.confirm('Start again from first contact? This resets current campaign queue progress.');
        if (!ok) return;

        setActionLoading(true);
        try {
            await api.post(`/campaigns/${id}/restart-from-first/`, { start_now: true });
            toast.success('Campaign restarted from first contact');
            fetchData({ silent: true });
        } catch (e) {
            toast.error(e?.response?.data?.error || 'Failed to restart campaign from first contact');
        } finally {
            setActionLoading(false);
        }
    };

    const handleRemoveContact = async (contact) => {
        const contactName = contact?.name || contact?.full_name || `Contact #${contact?.id || ''}`;
        const ok = window.confirm(`Delete "${contactName}" from this campaign?`);
        if (!ok) return;

        setDeletingContactId(contact.id);
        try {
            await api.post(`/campaigns/${id}/contacts/${contact.id}/remove/`);
            toast.success('Contact removed from campaign');
            fetchData({ silent: true });
        } catch (e) {
            const errorCode = e?.response?.data?.error;
            if (errorCode === 'contact_call_in_progress') {
                toast.error('This contact has an active call. Try again after call ends.');
            } else {
                toast.error(errorCode || 'Failed to remove contact');
            }
        } finally {
            setDeletingContactId(null);
        }
    };

    const handleClearTimeline = async () => {
        const ok = window.confirm('Clear all timeline events for this campaign?');
        if (!ok) return;

        setClearingTimeline(true);
        try {
            const { data } = await api.post(`/campaigns/${id}/timeline/clear/`);
            const clearedCount = Number(data?.cleared || 0);
            toast.success(`Cleared ${clearedCount} timeline event${clearedCount === 1 ? '' : 's'}`);
            setTimeline([]);
            fetchData({ silent: true });
        } catch (e) {
            toast.error(e?.response?.data?.error || 'Failed to clear timeline');
        } finally {
            setClearingTimeline(false);
        }
    };

    const handleSyncExotelLogs = async () => {
        setSyncingLogs(true);
        try {
            const { data } = await api.post('/call-logs/sync/exotel/', {
                campaign_id: Number(id),
                limit: 100,
                only_open: false,
            });
            const updated = Number(data?.updated || 0);
            const failed = Number(data?.failed_count || 0);
            toast.success(`Exotel sync complete. Updated: ${updated}${failed ? `, Failed: ${failed}` : ''}`);
            fetchData({ silent: true });
        } catch (e) {
            toast.error(e?.response?.data?.error || 'Exotel sync failed');
        } finally {
            setSyncingLogs(false);
        }
    };

    const pieData = analytics ? [
        { name: 'Answered', value: analytics.answered_calls, color: '#10b981' },
        { name: 'Failed', value: analytics.failed_calls, color: '#ef4444' },
        { name: 'No Answer', value: Math.max(0, analytics.total_calls - analytics.answered_calls - analytics.failed_calls), color: '#f59e0b' },
    ].filter(d => d.value > 0) : [];

    const formatSeconds = (total) => {
        const value = Math.max(0, Number(total || 0));
        const minutes = Math.floor(value / 60);
        const seconds = value % 60;
        return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    };
    const activeCall = campaign?.active_call || null;
    const waitingForPickup = activeCall?.stage === 'waiting_for_pickup';
    const pickupLeftSeconds = Number(activeCall?.pickup_seconds_left || 0);
    const lastCallStatus = String(campaign?.last_call_result?.display_status || '').toLowerCase();

    if (loading) return (
        <Box sx={{ p: 4, textAlign: 'center' }}>
            <CircularProgress sx={{ color: '#0142a2' }} />
        </Box>
    );

    if (!campaign) return (
        <Alert severity="error">{campaignLoadError || 'Campaign not found'}</Alert>
    );

    const statusColor = STATUS_COLORS[campaign.status] || '#64748b';

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                <IconButton onClick={() => navigate('/campaigns')} sx={{ color: '#64748b' }}>
                    <ArrowBack />
                </IconButton>
                <Box sx={{ flex: 1 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Typography variant="h4" fontWeight={700}>{campaign.name}</Typography>
                        <Chip
                            label={campaign.status}
                            size="small"
                            sx={{ bgcolor: `${statusColor}25`, color: statusColor, fontWeight: 600 }}
                        />
                        <Chip
                            label={campaign.dialing_mode + ' dialer'}
                            size="small"
                            variant="outlined"
                            sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}
                        />
                    </Box>
                    <Typography color="text.secondary" variant="body2">
                        {campaign.description || 'No description'} · Agent: {campaign.assigned_agent_details?.full_name || 'Unassigned'}
                    </Typography>
                </Box>

                {/* Action buttons */}
                <Box sx={{ display: 'flex', gap: 1 }}>
                    <Tooltip title="Refresh">
                        <IconButton onClick={fetchData} sx={{ color: '#64748b' }}>
                            <Refresh />
                        </IconButton>
                    </Tooltip>
                    <Button
                        variant="outlined"
                        startIcon={<Dialpad />}
                        onClick={() => navigate(`/dial?campaign_id=${id}`)}
                        sx={{ borderColor: 'rgba(1,66,162,0.4)', color: '#1a5bc4' }}
                    >
                        Open Dialer
                    </Button>
                    <Button
                        variant="outlined"
                        startIcon={<RestartAlt />}
                        onClick={handleStartFromFirst}
                        disabled={actionLoading || !campaign?.total_contacts}
                        sx={{ borderColor: 'rgba(59,130,246,0.4)', color: '#60a5fa' }}
                    >
                        Start From First
                    </Button>
                    {campaign.status === 'draft' && (
                        <Button
                            variant="contained"
                            startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <PlayArrow />}
                            onClick={() => handleAction('start')}
                            disabled={actionLoading}
                            sx={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
                        >
                            Start
                        </Button>
                    )}
                    {campaign.status === 'active' && (
                        <Button
                            variant="outlined"
                            startIcon={<Pause />}
                            onClick={() => handleAction('pause')}
                            disabled={actionLoading}
                            sx={{ borderColor: '#f59e0b', color: '#f59e0b' }}
                        >
                            Pause
                        </Button>
                    )}
                    {campaign.status === 'paused' && (
                        <Button
                            variant="contained"
                            startIcon={<PlayArrow />}
                            onClick={() => handleAction('resume')}
                            disabled={actionLoading}
                            sx={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
                        >
                            Resume
                        </Button>
                    )}
                </Box>
            </Box>

            {/* Progress bar (when active) */}
            {campaign.status === 'active' && (
                <Box sx={{ mb: 3, p: 2, borderRadius: 2, bgcolor: 'rgba(16,185,129,0.08)', border: '1px solid rgba(16,185,129,0.2)' }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                        <Typography variant="body2" fontWeight={600} color="#10b981">
                            🟢 Campaign Running
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                            {campaign.dialed_contacts}/{campaign.total_contacts} contacts dialed
                        </Typography>
                    </Box>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                        {campaign.active_call_in_progress
                            ? waitingForPickup
                                ? `Customer not picking yet. Waiting ${formatSeconds(pickupLeftSeconds)} before marking no-answer.`
                                : `Agent is in call${activeCall?.contact_name ? ` with ${activeCall.contact_name}` : ''}.`
                            : cooldownSeconds > 0
                                ? (lastCallStatus === 'no-answer'
                                    ? `Customer did not pick the call. Next call in ${formatSeconds(cooldownSeconds)}`
                                    : `Next call in ${formatSeconds(cooldownSeconds)}`)
                                : 'Waiting to dispatch next contact...'}
                    </Typography>
                    <LinearProgress
                        value={campaign.progress_percentage}
                        variant="determinate"
                        sx={{ height: 8, borderRadius: 4, bgcolor: 'rgba(16,185,129,0.1)', '& .MuiLinearProgress-bar': { bgcolor: '#10b981', borderRadius: 4 } }}
                    />
                </Box>
            )}

            {/* Stats row */}
            <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={6} sm={3}>
                    <StatBadge label="Total Contacts" value={campaign.total_contacts} color="#0142a2" />
                </Grid>
                <Grid item xs={6} sm={3}>
                    <StatBadge label="Dialed" value={campaign.dialed_contacts} color="#3b82f6" />
                </Grid>
                <Grid item xs={6} sm={3}>
                    <StatBadge label="Connected" value={campaign.connected_calls} color="#10b981" />
                </Grid>
                <Grid item xs={6} sm={3}>
                    <StatBadge label="Connect Rate" value={`${campaign.connect_rate}%`} color="#f59e0b" />
                </Grid>
            </Grid>

            {/* Tabs */}
            <Card>
                <Tabs
                    value={tab}
                    onChange={(_, v) => setTab(v)}
                    sx={{
                        borderBottom: '1px solid rgba(1,66,162,0.1)',
                        '& .MuiTab-root': { textTransform: 'none', fontWeight: 500, color: '#64748b' },
                        '& .Mui-selected': { color: '#0142a2' },
                        '& .MuiTabs-indicator': { bgcolor: '#0142a2' },
                    }}
                >
                    <Tab label={`Contacts (${contacts.length})`} />
                    <Tab label={`Call Logs (${callLogs.length})`} />
                    <Tab label="Analytics" />
                    <Tab label={`Timeline (${timeline.length})`} />
                </Tabs>

                {/* Contacts tab */}
                {tab === 0 && (
                    <TableContainer>
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    <TableCell>#</TableCell>
                                    <TableCell>Name</TableCell>
                                    <TableCell>Phone</TableCell>
                                    <TableCell>Company</TableCell>
                                    <TableCell>Status</TableCell>
                                    <TableCell>Retries</TableCell>
                                    <TableCell>Last Called</TableCell>
                                    <TableCell align="right">Action</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {contacts.map((c, i) => (
                                    <TableRow key={c.id} hover>
                                        <TableCell sx={{ color: '#64748b', fontSize: '0.8rem' }}>{i + 1}</TableCell>
                                        <TableCell>
                                            <Typography fontWeight={500} fontSize="0.875rem">{c.name}</Typography>
                                        </TableCell>
                                        <TableCell><Typography fontSize="0.875rem">{c.phone}</Typography></TableCell>
                                        <TableCell><Typography fontSize="0.875rem" color="text.secondary">{c.company || '—'}</Typography></TableCell>
                                        <TableCell>
                                            <Chip
                                                label={c.status}
                                                size="small"
                                                sx={{
                                                    bgcolor: `${CALL_STATUS_COLORS[c.status] || '#64748b'}20`,
                                                    color: CALL_STATUS_COLORS[c.status] || '#94a3b8',
                                                }}
                                            />
                                        </TableCell>
                                        <TableCell><Typography fontSize="0.875rem">{c.retry_count}</Typography></TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.75rem" color="text.secondary">
                                                {c.last_called_at ? new Date(c.last_called_at).toLocaleString() : '—'}
                                            </Typography>
                                        </TableCell>
                                        <TableCell align="right">
                                            <Tooltip title="Remove from campaign">
                                                <span>
                                                    <IconButton
                                                        size="small"
                                                        onClick={() => handleRemoveContact(c)}
                                                        disabled={deletingContactId === c.id}
                                                        sx={{ color: '#ef4444' }}
                                                    >
                                                        <Delete fontSize="small" />
                                                    </IconButton>
                                                </span>
                                            </Tooltip>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}

                {/* Call Logs tab */}
                {tab === 1 && (
                    <Box>
                        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1.5 }}>
                            <Button
                                variant="outlined"
                                startIcon={syncingLogs ? <CircularProgress size={14} color="inherit" /> : <Refresh />}
                                onClick={handleSyncExotelLogs}
                                disabled={syncingLogs}
                                sx={{ borderColor: 'rgba(1,66,162,0.4)', color: '#1a5bc4' }}
                            >
                                {syncingLogs ? 'Syncing...' : 'Sync Exotel'}
                            </Button>
                        </Box>
                        <TableContainer>
                            <Table size="small">
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Contact</TableCell>
                                        <TableCell>Agent</TableCell>
                                        <TableCell>Status</TableCell>
                                        <TableCell>Duration</TableCell>
                                        <TableCell>Recording</TableCell>
                                        <TableCell>Transcript</TableCell>
                                        <TableCell>Time</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {callLogs.length === 0 ? (
                                        <TableRow>
                                            <TableCell colSpan={7} align="center" sx={{ py: 4, color: '#64748b' }}>
                                                No calls yet. Start the campaign to begin dialing.
                                            </TableCell>
                                        </TableRow>
                                    ) : callLogs.map(log => (
                                        <TableRow key={log.id} hover
                                            onClick={() => setSelectedCall(log)}
                                            sx={{ cursor: 'pointer' }}>
                                            <TableCell>
                                                <Box>
                                                    <Typography fontWeight={500} fontSize="0.875rem">{log.contact_name}</Typography>
                                                    <Typography fontSize="0.75rem" color="text.secondary">{log.contact_phone}</Typography>
                                                </Box>
                                            </TableCell>
                                            <TableCell><Typography fontSize="0.875rem">{log.agent_name}</Typography></TableCell>
                                            <TableCell>
                                                <Chip label={log.status} size="small"
                                                    sx={{ bgcolor: `${CALL_STATUS_COLORS[log.status] || '#64748b'}20`, color: CALL_STATUS_COLORS[log.status] || '#94a3b8' }} />
                                            </TableCell>
                                            <TableCell><Typography fontSize="0.875rem">{log.duration_formatted}</Typography></TableCell>
                                            <TableCell>
                                                {log.recording_url ? (
                                                    <IconButton size="small" href={log.recording_url} target="_blank"
                                                        sx={{ color: '#0142a2' }} onClick={e => e.stopPropagation()}>
                                                        <Download fontSize="small" />
                                                    </IconButton>
                                                ) : <Typography fontSize="0.8rem" color="text.disabled">—</Typography>}
                                            </TableCell>
                                            <TableCell>
                                                {log.transcript_status === 'completed' ? (
                                                    <Chip label="Available" size="small" sx={{ bgcolor: '#10b98125', color: '#10b981', fontSize: '0.7rem' }} />
                                                ) : log.transcript_status === 'processing' ? (
                                                    <Chip label="Processing" size="small" sx={{ bgcolor: '#f59e0b25', color: '#f59e0b', fontSize: '0.7rem' }} />
                                                ) : <Typography fontSize="0.8rem" color="text.disabled">—</Typography>}
                                            </TableCell>
                                            <TableCell>
                                                <Typography fontSize="0.75rem" color="text.secondary">
                                                    {new Date(log.initiated_at).toLocaleString()}
                                                </Typography>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    </Box>
                )}

                {/* Analytics tab */}
                {tab === 2 && analytics && (
                    <CardContent>
                        <Grid container spacing={3}>
                            <Grid item xs={12} md={5}>
                                <Typography variant="subtitle1" fontWeight={600} mb={2}>Call Outcomes</Typography>
                                {pieData.length > 0 ? (
                                    <Box>
                                        <ResponsiveContainer width="100%" height={220}>
                                            <PieChart>
                                                <Pie data={pieData} cx="50%" cy="50%" innerRadius={60} outerRadius={90}
                                                    paddingAngle={3} dataKey="value">
                                                    {pieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                                                </Pie>
                                                <ReTooltip contentStyle={{ background: '#ffffff', border: 'none', borderRadius: 8 }} />
                                            </PieChart>
                                        </ResponsiveContainer>
                                        <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap' }}>
                                            {pieData.map(d => (
                                                <Box key={d.name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                    <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: d.color }} />
                                                    <Typography variant="caption">{d.name}: {d.value}</Typography>
                                                </Box>
                                            ))}
                                        </Box>
                                    </Box>
                                ) : (
                                    <Box sx={{ textAlign: 'center', py: 6, color: '#64748b' }}>No call data yet</Box>
                                )}
                            </Grid>
                            <Grid item xs={12} md={7}>
                                <Typography variant="subtitle1" fontWeight={600} mb={2}>Summary Statistics</Typography>
                                <Grid container spacing={2}>
                                    {[
                                        { label: 'Total Calls', value: analytics.total_calls, color: '#0142a2' },
                                        { label: 'Answered', value: analytics.answered_calls, color: '#10b981' },
                                        { label: 'Connect Rate', value: `${analytics.connect_rate}%`, color: '#f59e0b' },
                                        { label: 'Avg Duration', value: `${analytics.avg_duration_seconds}s`, color: '#3b82f6' },
                                    ].map(stat => (
                                        <Grid item xs={6} key={stat.label}>
                                            <Box sx={{ p: 2, borderRadius: 2, bgcolor: `${stat.color}10`, border: `1px solid ${stat.color}20` }}>
                                                <Typography variant="h5" fontWeight={700} color={stat.color}>{stat.value}</Typography>
                                                <Typography variant="caption" color="text.secondary">{stat.label}</Typography>
                                            </Box>
                                        </Grid>
                                    ))}
                                </Grid>
                            </Grid>
                        </Grid>
                    </CardContent>
                )}

                {tab === 3 && (
                    <CardContent>
                        <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1.5 }}>
                            <Button
                                variant="outlined"
                                color="error"
                                startIcon={clearingTimeline ? <CircularProgress size={14} color="inherit" /> : <Delete />}
                                onClick={handleClearTimeline}
                                disabled={clearingTimeline || timeline.length === 0}
                                sx={{ borderColor: 'rgba(239,68,68,0.45)', color: '#f87171' }}
                            >
                                Clear Timeline
                            </Button>
                        </Box>
                        {timeline.length === 0 ? (
                            <Typography color="text.secondary">No timeline events yet.</Typography>
                        ) : (
                            <Box sx={{ display: 'grid', gap: 1 }}>
                                {timeline.map((event, index) => (
                                    <Box
                                        key={`${event.at}-${event.type}-${index}`}
                                        sx={{
                                            p: 1.5,
                                            borderRadius: 1.5,
                                            bgcolor: 'rgba(1,66,162,0.08)',
                                            border: '1px solid rgba(1,66,162,0.12)',
                                        }}
                                    >
                                        <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2 }}>
                                            <Typography fontWeight={600} fontSize="0.85rem">
                                                {event.type}
                                            </Typography>
                                            <Typography color="text.secondary" fontSize="0.75rem">
                                                {event.at ? new Date(event.at).toLocaleString() : '-'}
                                            </Typography>
                                        </Box>
                                        <Typography fontSize="0.8rem" sx={{ mt: 0.25 }}>
                                            {event.message || '-'}
                                        </Typography>
                                        {event.details && Object.keys(event.details).length > 0 ? (
                                            <Typography
                                                fontSize="0.72rem"
                                                color="text.secondary"
                                                sx={{ mt: 0.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
                                            >
                                                {JSON.stringify(event.details, null, 2)}
                                            </Typography>
                                        ) : null}
                                    </Box>
                                ))}
                            </Box>
                        )}
                    </CardContent>
                )}
            </Card>

            {/* Call detail dialog */}
            {selectedCall && (
                <Dialog open={Boolean(selectedCall)} onClose={() => setSelectedCall(null)} maxWidth="md" fullWidth
                    PaperProps={{ sx: { bgcolor: '#f0f4f9', border: '1px solid rgba(1,66,162,0.2)' } }}>
                    <DialogTitle>
                        Call with {selectedCall.contact_name}
                        <Chip label={selectedCall.status} size="small" sx={{ ml: 2 }} />
                    </DialogTitle>
                    <DialogContent>
                        <Grid container spacing={2} sx={{ mb: 2 }}>
                            {[
                                { label: 'Phone', value: selectedCall.contact_phone },
                                { label: 'Agent', value: selectedCall.agent_name },
                                { label: 'Duration', value: selectedCall.duration_formatted },
                                { label: 'Time', value: new Date(selectedCall.initiated_at).toLocaleString() },
                            ].map(({ label, value }) => (
                                <Grid item xs={6} key={label}>
                                    <Typography variant="caption" color="text.secondary">{label}</Typography>
                                    <Typography fontWeight={500}>{value}</Typography>
                                </Grid>
                            ))}
                        </Grid>

                        {selectedCall.transcript && (
                            <Box sx={{ mt: 2 }}>
                                <Typography variant="subtitle2" fontWeight={600} mb={1}>📝 Transcript</Typography>
                                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.05)', border: '1px solid rgba(1,66,162,0.1)' }}>
                                    <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
                                        {selectedCall.transcript}
                                    </Typography>
                                </Box>
                            </Box>
                        )}

                        {selectedCall.agent_notes && (
                            <Box sx={{ mt: 2 }}>
                                <Typography variant="subtitle2" fontWeight={600} mb={1}>📋 Agent Notes</Typography>
                                <Typography variant="body2" color="text.secondary">{selectedCall.agent_notes}</Typography>
                            </Box>
                        )}
                    </DialogContent>
                    <DialogActions>
                        <Button onClick={() => setSelectedCall(null)}>Close</Button>
                    </DialogActions>
                </Dialog>
            )}
        </Box>
    );
}
