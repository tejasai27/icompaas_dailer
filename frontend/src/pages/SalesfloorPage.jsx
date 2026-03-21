import React, { useCallback, useEffect, useState } from 'react';
import {
    Avatar, Box, Card, CardContent, Typography, Grid, Chip,
    Button, Divider, LinearProgress, Switch, FormControlLabel, Skeleton
} from '@mui/material';
import {
    Phone, Headphones, Circle, PlayArrow, TrendingUp,
    People, PhoneInTalk, CheckCircle
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import useAuth from '../context/useAuth';
import toast from 'react-hot-toast';
import { normalizeCallStatus, formatCallStatus, CALL_STATUS_COLORS } from '../lib/callStatus';
import { relativeTime } from '../lib/formatDate';
import useVisibleInterval from '../lib/useVisibleInterval';

/* ── Live metrics strip ── */
function LiveMetricsStrip({ campaigns, recentCalls, agents, loading }) {
    const totalDialed = campaigns.reduce((s, c) => s + (c.dialed_contacts || 0), 0);
    const totalConnected = campaigns.reduce((s, c) => s + (c.connected_calls || 0), 0);
    const activeAgents = agents.filter((a) => a.status === 'available' || a.status === 'busy').length;

    const metrics = [
        { label: 'Active Campaigns', value: campaigns.length, icon: <PlayArrow sx={{ fontSize: 16 }} />, color: '#10b981' },
        { label: 'Agents Online', value: activeAgents, icon: <People sx={{ fontSize: 16 }} />, color: '#3b82f6' },
        { label: 'Calls Dialed', value: totalDialed, icon: <Phone sx={{ fontSize: 16 }} />, color: '#0142a2' },
        { label: 'Connected', value: totalConnected, icon: <CheckCircle sx={{ fontSize: 16 }} />, color: '#10b981' },
        { label: 'Connect Rate', value: totalDialed > 0 ? `${((totalConnected / totalDialed) * 100).toFixed(1)}%` : '0%', icon: <TrendingUp sx={{ fontSize: 16 }} />, color: '#f59e0b' },
    ];

    return (
        <Box sx={{
            display: 'flex', gap: 1.5, mb: 3, p: 2, borderRadius: 2.5,
            background: 'linear-gradient(135deg, rgba(1,66,162,0.06) 0%, rgba(13,148,136,0.06) 100%)',
            border: '1px solid rgba(1,66,162,0.08)',
            overflowX: 'auto',
        }}>
            {metrics.map((m) => (
                <Box key={m.label} sx={{
                    flex: '1 0 auto', display: 'flex', alignItems: 'center', gap: 1,
                    px: 2, py: 1, borderRadius: 2, bgcolor: 'white',
                    border: '1px solid rgba(1,66,162,0.06)', minWidth: 130,
                }}>
                    <Box sx={{ width: 32, height: 32, borderRadius: 1.5, bgcolor: `${m.color}15`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        {React.cloneElement(m.icon, { sx: { color: m.color, fontSize: 16 } })}
                    </Box>
                    <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.2 }}>{m.label}</Typography>
                        <Typography fontWeight={800} fontSize="1.1rem" color={m.color}>
                            {loading ? <Skeleton width={30} /> : m.value}
                        </Typography>
                    </Box>
                </Box>
            ))}
        </Box>
    );
}

/* ── Agent card for the grid ── */
function AgentCard({ agent }) {
    const statusColors = {
        available: { bg: '#10b98120', border: '#10b981', text: '#10b981', label: 'Available' },
        busy: { bg: '#f59e0b20', border: '#f59e0b', text: '#f59e0b', label: 'On Call' },
        ringing: { bg: '#3b82f620', border: '#3b82f6', text: '#3b82f6', label: 'Ringing' },
        wrap_up: { bg: '#8b5cf620', border: '#8b5cf6', text: '#8b5cf6', label: 'Wrap Up' },
        offline: { bg: '#64748b20', border: '#94a3b8', text: '#94a3b8', label: 'Offline' },
    };
    const cfg = statusColors[agent.status] || statusColors.offline;

    return (
        <Card sx={{
            border: `1px solid ${cfg.border}30`,
            transition: 'all 0.2s',
            '&:hover': { transform: 'translateY(-1px)', boxShadow: `0 4px 12px ${cfg.border}20` },
        }}>
            <CardContent sx={{ pb: '12px !important', pt: 1.5 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                    <Box sx={{ position: 'relative' }}>
                        <Avatar sx={{ width: 40, height: 40, bgcolor: '#0142a2', fontSize: '0.9rem', fontWeight: 700 }}>
                            {(agent.display_name || '?')[0].toUpperCase()}
                        </Avatar>
                        <Box sx={{
                            position: 'absolute', bottom: 0, right: 0,
                            width: 12, height: 12, borderRadius: '50%',
                            bgcolor: cfg.border, border: '2px solid white',
                        }} />
                    </Box>
                    <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography fontWeight={700} fontSize="0.85rem" noWrap>{agent.display_name}</Typography>
                        <Chip label={cfg.label} size="small"
                            sx={{ height: 20, fontSize: '0.65rem', fontWeight: 600, bgcolor: cfg.bg, color: cfg.text }} />
                    </Box>
                </Box>
            </CardContent>
        </Card>
    );
}

/* ── Campaign row ── */
function CampaignRow({ campaign }) {
    const navigate = useNavigate();
    const progress = campaign.total_contacts > 0
        ? Math.round((campaign.dialed_contacts / campaign.total_contacts) * 100) : 0;

    return (
        <Box sx={{
            p: 2, mb: 1, borderRadius: 2,
            bgcolor: 'rgba(16,185,129,0.04)', border: '1px solid rgba(16,185,129,0.15)',
            cursor: 'pointer', transition: 'all 0.15s',
            '&:hover': { bgcolor: 'rgba(16,185,129,0.08)' },
        }}
            onClick={() => navigate(`/campaigns/${campaign.id}`)}
        >
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography fontWeight={700} fontSize="0.9rem" noWrap sx={{ flex: 1 }}>{campaign.name}</Typography>
                <Chip label="LIVE" size="small"
                    sx={{ bgcolor: '#10b98120', color: '#10b981', fontSize: '0.6rem', fontWeight: 800, height: 20, letterSpacing: '0.05em' }} />
            </Box>

            <Box sx={{ mb: 1.5 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
                    <Typography variant="caption" color="text.secondary">{campaign.dialed_contacts}/{campaign.total_contacts} dialed</Typography>
                    <Typography variant="caption" fontWeight={600}>{progress}%</Typography>
                </Box>
                <LinearProgress value={progress} variant="determinate"
                    sx={{ height: 5, borderRadius: 3, bgcolor: 'rgba(16,185,129,0.1)', '& .MuiLinearProgress-bar': { bgcolor: '#10b981', borderRadius: 3 } }} />
            </Box>

            <Box sx={{ display: 'flex', gap: 2.5, flexWrap: 'wrap' }}>
                {[
                    { label: 'Connected', value: campaign.connected_calls, color: '#10b981' },
                    { label: 'Rate', value: `${campaign.connect_rate}%`, color: '#f59e0b' },
                    { label: 'SDR', value: campaign.assigned_agent_name || 'Unassigned', color: '#64748b' },
                ].map((m) => (
                    <Box key={m.label}>
                        <Typography variant="caption" color="text.secondary">{m.label}</Typography>
                        <Typography fontWeight={700} fontSize="0.85rem" color={m.color}>{m.value}</Typography>
                    </Box>
                ))}
            </Box>
        </Box>
    );
}

/* ── Live call feed item ── */
function LiveCallItem({ call }) {
    const statusKey = normalizeCallStatus(call.status);
    const color = CALL_STATUS_COLORS[statusKey] || '#64748b';

    return (
        <Box sx={{
            display: 'flex', alignItems: 'center', gap: 1.5, py: 1, px: 1,
            borderRadius: 1.5, mb: 0.5,
            borderLeft: `3px solid ${color}`,
            transition: 'background 0.15s',
            '&:hover': { bgcolor: 'rgba(1,66,162,0.03)' },
        }}>
            <Avatar sx={{ width: 30, height: 30, bgcolor: `${color}20`, color, fontSize: '0.7rem', fontWeight: 700 }}>
                {(call.contact_name || '?')[0]}
            </Avatar>
            <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography fontWeight={600} fontSize="0.8rem" noWrap>
                    {call.contact_name} <Typography component="span" fontSize="0.75rem" color="text.secondary">· {call.campaign_name}</Typography>
                </Typography>
            </Box>
            <Chip label={formatCallStatus(call.status)} size="small"
                sx={{ height: 20, fontSize: '0.6rem', fontWeight: 600, bgcolor: `${color}15`, color }} />
            <Typography fontSize="0.7rem" color="text.secondary" sx={{ minWidth: 50, textAlign: 'right' }}>
                {call.duration_formatted !== '-' ? call.duration_formatted : relativeTime(call.initiated_at)}
            </Typography>
        </Box>
    );
}

/* ── Main page ── */
export default function SalesfloorPage() {
    const [campaigns, setCampaigns] = useState([]);
    const [recentCalls, setRecentCalls] = useState([]);
    const [agents, setAgents] = useState([]);
    const [available, setAvailable] = useState(true);
    const [loading, setLoading] = useState(true);
    const { user } = useAuth();
    const navigate = useNavigate();

    const fetchData = useCallback(async () => {
        try {
            const [campaignsRes, callsRes, agentsRes] = await Promise.allSettled([
                api.get('/campaigns/?status=active'),
                api.get('/call-logs/?ordering=-initiated_at'),
                api.get('/agents/'),
            ]);
            if (campaignsRes.status === 'fulfilled') {
                setCampaigns(campaignsRes.value.data.results || campaignsRes.value.data || []);
            }
            if (callsRes.status === 'fulfilled') {
                const rows = callsRes.value.data.results || callsRes.value.data || [];
                setRecentCalls(rows.slice(0, 15));
            }
            if (agentsRes.status === 'fulfilled') {
                const list = Array.isArray(agentsRes.value.data?.agents) ? agentsRes.value.data.agents : [];
                setAgents(list);
            }
        } catch {
            toast.error('Failed to load salesfloor data');
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchData(); }, [fetchData]);
    useVisibleInterval(fetchData, 10000);

    const toggleAvailability = async () => {
        const prev = available;
        setAvailable(!prev);
        try {
            await api.patch('/auth/users/update_availability/', { is_available: !prev });
        } catch {
            setAvailable(prev);
            toast.error('Failed to update availability');
        }
    };

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Salesfloor</Typography>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography color="text.secondary" variant="body2">Real-time team activity and live campaigns</Typography>
                        <Chip label="LIVE" size="small"
                            sx={{ bgcolor: '#10b98120', color: '#10b981', fontWeight: 700, fontSize: '0.6rem', height: 20, animation: 'pulse 2s ease-in-out infinite', '@keyframes pulse': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.6 } } }} />
                    </Box>
                </Box>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <FormControlLabel
                        control={<Switch checked={available} onChange={toggleAvailability}
                            sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#10b981' }, '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: '#10b98150' } }} />}
                        label={
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                <Circle sx={{ fontSize: 8, color: available ? '#10b981' : '#94a3b8' }} />
                                <Typography variant="body2" fontWeight={600} color={available ? '#10b981' : '#94a3b8'}>
                                    {available ? 'Available' : 'Away'}
                                </Typography>
                            </Box>
                        }
                    />
                    <Button variant="contained" size="small" startIcon={<Phone />}
                        onClick={() => navigate('/dial')}
                        sx={{ bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' } }}>
                        Dialer
                    </Button>
                </Box>
            </Box>

            {/* Live metrics strip */}
            <LiveMetricsStrip campaigns={campaigns} recentCalls={recentCalls} agents={agents} loading={loading} />

            <Grid container spacing={2}>
                {/* Left column: Agent grid + My Status */}
                <Grid item xs={12} md={3}>
                    {/* My Status */}
                    <Card sx={{ mb: 2 }}>
                        <CardContent sx={{ pb: '12px !important' }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                                <Box sx={{ position: 'relative' }}>
                                    <Avatar sx={{ width: 44, height: 44, bgcolor: '#0142a2', fontSize: '1rem', fontWeight: 700 }}>
                                        {(user?.full_name || user?.username || '?')[0].toUpperCase()}
                                    </Avatar>
                                    <Box sx={{
                                        position: 'absolute', bottom: 0, right: 0,
                                        width: 12, height: 12, borderRadius: '50%',
                                        bgcolor: available ? '#10b981' : '#94a3b8', border: '2px solid white',
                                    }} />
                                </Box>
                                <Box>
                                    <Typography fontWeight={700} fontSize="0.85rem">{user?.full_name || user?.username}</Typography>
                                    <Typography variant="caption" color="text.secondary" textTransform="capitalize">{user?.role}</Typography>
                                </Box>
                            </Box>
                        </CardContent>
                    </Card>

                    {/* Team agents */}
                    <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 0.5, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                        Team ({agents.length})
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap' }}>
                        {[
                            { label: 'Available', color: '#10b981' },
                            { label: 'On Call', color: '#f59e0b' },
                            { label: 'Ringing', color: '#3b82f6' },
                            { label: 'Wrap Up', color: '#8b5cf6' },
                            { label: 'Offline', color: '#94a3b8' },
                        ].map((s) => (
                            <Box key={s.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.3 }}>
                                <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: s.color }} />
                                <Typography variant="caption" fontSize="0.6rem" color="text.secondary">{s.label}</Typography>
                            </Box>
                        ))}
                    </Box>
                    {loading ? (
                        Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} height={56} sx={{ mb: 1, borderRadius: 2 }} />)
                    ) : agents.length === 0 ? (
                        <Typography variant="caption" color="text.secondary">No SDRs found</Typography>
                    ) : (
                        <Box sx={{ display: 'grid', gap: 1 }}>
                            {agents.map((agent) => <AgentCard key={agent.id} agent={agent} />)}
                        </Box>
                    )}
                </Grid>

                {/* Center column: Active Campaigns */}
                <Grid item xs={12} md={5}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Typography variant="subtitle2" fontWeight={700} sx={{ textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                            Active Campaigns
                        </Typography>
                        <Chip label={`${campaigns.length} live`} size="small"
                            sx={{ bgcolor: campaigns.length > 0 ? '#10b98120' : '#64748b20', color: campaigns.length > 0 ? '#10b981' : '#94a3b8', fontWeight: 600, height: 22, fontSize: '0.7rem' }} />
                    </Box>

                    {loading ? (
                        Array.from({ length: 2 }).map((_, i) => <Skeleton key={i} height={100} sx={{ mb: 1, borderRadius: 2 }} />)
                    ) : campaigns.length === 0 ? (
                        <Card>
                            <CardContent sx={{ textAlign: 'center', py: 4 }}>
                                <Headphones sx={{ fontSize: 48, color: '#cbd5e1', mb: 1 }} />
                                <Typography color="text.secondary">No active campaigns right now</Typography>
                                <Button variant="outlined" size="small" onClick={() => navigate('/campaigns')} sx={{ mt: 1.5 }}>
                                    View Campaigns
                                </Button>
                            </CardContent>
                        </Card>
                    ) : campaigns.map((c) => (
                        <CampaignRow key={c.id} campaign={c} />
                    ))}
                </Grid>

                {/* Right column: Live Call Feed */}
                <Grid item xs={12} md={4}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                        <Typography variant="subtitle2" fontWeight={700} sx={{ textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                            Live Call Feed
                        </Typography>
                        <Button size="small" onClick={() => navigate('/call-logs')} sx={{ color: '#1a5bc4', textTransform: 'none', fontWeight: 600, fontSize: '0.75rem' }}>
                            View all
                        </Button>
                    </Box>

                    <Card>
                        <CardContent sx={{ py: 1.5 }}>
                            {loading ? (
                                Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={40} sx={{ mb: 0.5, borderRadius: 1 }} />)
                            ) : recentCalls.length === 0 ? (
                                <Box sx={{ textAlign: 'center', py: 3 }}>
                                    <PhoneInTalk sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                    <Typography variant="body2" color="text.secondary">No calls yet</Typography>
                                </Box>
                            ) : recentCalls.map((call) => (
                                <LiveCallItem key={call.id} call={call} />
                            ))}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
