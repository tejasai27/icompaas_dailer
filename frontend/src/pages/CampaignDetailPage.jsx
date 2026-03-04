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
    Edit, Refresh, Download
} from '@mui/icons-material';
import { useParams, useNavigate } from 'react-router-dom';
import { PieChart, Pie, Cell, BarChart as ReBarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip as ReTooltip, ResponsiveContainer } from 'recharts';
import api from '../services/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
    active: '#10b981', paused: '#f59e0b', completed: '#6366f1', draft: '#64748b',
};
const CALL_STATUS_COLORS = {
    answered: '#10b981', 'no-answer': '#f59e0b', busy: '#ef4444', failed: '#ef4444', completed: '#6366f1', initiated: '#3b82f6',
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
    const [tab, setTab] = useState(0);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [selectedCall, setSelectedCall] = useState(null);

    const fetchData = async () => {
        try {
            const [campRes, analyticsRes, contactsRes, logsRes] = await Promise.all([
                api.get(`/campaigns/${id}/`),
                api.get(`/campaigns/${id}/analytics/`),
                api.get(`/contacts/?campaign=${id}`),
                api.get(`/call-logs/?campaign=${id}`),
            ]);
            setCampaign(campRes.data);
            setAnalytics(analyticsRes.data);
            setContacts(contactsRes.data.results || contactsRes.data);
            setCallLogs(logsRes.data.results || logsRes.data);
        } catch (e) {
            toast.error('Failed to load campaign');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchData(); }, [id]);

    // Auto-refresh when active
    useEffect(() => {
        if (campaign?.status === 'active') {
            const interval = setInterval(fetchData, 10000);
            return () => clearInterval(interval);
        }
    }, [campaign?.status]);

    const handleAction = async (action) => {
        setActionLoading(true);
        try {
            await api.post(`/campaigns/${id}/${action}/`);
            toast.success(`Campaign ${action}ed`);
            fetchData();
        } catch (e) {
            toast.error(e.response?.data?.error || `Failed to ${action}`);
        } finally {
            setActionLoading(false);
        }
    };

    const pieData = analytics ? [
        { name: 'Answered', value: analytics.answered_calls, color: '#10b981' },
        { name: 'Failed', value: analytics.failed_calls, color: '#ef4444' },
        { name: 'No Answer', value: Math.max(0, analytics.total_calls - analytics.answered_calls - analytics.failed_calls), color: '#f59e0b' },
    ].filter(d => d.value > 0) : [];

    if (loading) return (
        <Box sx={{ p: 4, textAlign: 'center' }}>
            <CircularProgress sx={{ color: '#6366f1' }} />
        </Box>
    );

    if (!campaign) return (
        <Alert severity="error">Campaign not found</Alert>
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
                            sx={{ borderColor: 'rgba(99,102,241,0.3)', color: '#818cf8' }}
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
                    <StatBadge label="Total Contacts" value={campaign.total_contacts} color="#6366f1" />
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
                        borderBottom: '1px solid rgba(99,102,241,0.1)',
                        '& .MuiTab-root': { textTransform: 'none', fontWeight: 500, color: '#64748b' },
                        '& .Mui-selected': { color: '#6366f1' },
                        '& .MuiTabs-indicator': { bgcolor: '#6366f1' },
                    }}
                >
                    <Tab label={`Contacts (${contacts.length})`} />
                    <Tab label={`Call Logs (${callLogs.length})`} />
                    <Tab label="Analytics" />
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
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}

                {/* Call Logs tab */}
                {tab === 1 && (
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
                                                    sx={{ color: '#6366f1' }} onClick={e => e.stopPropagation()}>
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
                                                <ReTooltip contentStyle={{ background: '#1a1a2e', border: 'none', borderRadius: 8 }} />
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
                                        { label: 'Total Calls', value: analytics.total_calls, color: '#6366f1' },
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
            </Card>

            {/* Call detail dialog */}
            {selectedCall && (
                <Dialog open={Boolean(selectedCall)} onClose={() => setSelectedCall(null)} maxWidth="md" fullWidth
                    PaperProps={{ sx: { bgcolor: '#1a1a2e', border: '1px solid rgba(99,102,241,0.2)' } }}>
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
                                <Box sx={{ p: 2, borderRadius: 2, bgcolor: 'rgba(99,102,241,0.05)', border: '1px solid rgba(99,102,241,0.1)' }}>
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
