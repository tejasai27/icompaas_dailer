import React, { useEffect, useState } from 'react';
import {
    Alert, Avatar, Box, Grid, Card, CardContent, Typography, Chip, Button,
    LinearProgress, Table, TableBody, TableCell, TableContainer, TableHead,
    TableRow, Skeleton
} from '@mui/material';
import {
    Phone, CheckCircle, TrendingUp, Contacts, History,
    ArrowUpward, ArrowDownward, Campaign, Circle, Dialpad
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { Tooltip, ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid } from 'recharts';
import api from '../services/api';
import useAuth from '../context/useAuth';
import { CALL_STATUS_COLORS, normalizeCallStatus, formatCallStatus } from '../lib/callStatus';
import { shortDateTime, relativeTime } from '../lib/formatDate';
import useVisibleInterval from '../lib/useVisibleInterval';

/* ── Stat card with optional trend ── */
function StatCard({ title, value, icon, color, subtitle, loading, trend, onClick }) {
    return (
        <Card sx={{ height: '100%', cursor: onClick ? 'pointer' : 'default', transition: 'all 0.2s', '&:hover': onClick ? { transform: 'translateY(-2px)', boxShadow: '0 4px 12px rgba(1,66,162,0.12)' } : {} }} onClick={onClick}>
            <CardContent sx={{ pb: '16px !important' }}>
                <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                    <Box>
                        <Typography variant="caption" color="text.secondary" sx={{ textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>
                            {title}
                        </Typography>
                        {loading ? <Skeleton width={80} height={40} /> : (
                            <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
                                <Typography variant="h4" fontWeight={800} color={color || 'text.primary'}>
                                    {value}
                                </Typography>
                                {trend && (
                                    <Chip
                                        icon={trend > 0 ? <ArrowUpward sx={{ fontSize: 12 }} /> : <ArrowDownward sx={{ fontSize: 12 }} />}
                                        label={`${Math.abs(trend)}%`}
                                        size="small"
                                        sx={{
                                            height: 22, fontSize: '0.7rem', fontWeight: 700,
                                            bgcolor: trend > 0 ? '#10b98120' : '#ef444420',
                                            color: trend > 0 ? '#10b981' : '#ef4444',
                                            '& .MuiChip-icon': { color: 'inherit', ml: 0.5 },
                                        }}
                                    />
                                )}
                            </Box>
                        )}
                        {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
                    </Box>
                    <Box sx={{
                        width: 44, height: 44, borderRadius: 2.5,
                        bgcolor: `${color || '#0142a2'}15`,
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                        {React.cloneElement(icon, { sx: { color: color || '#0142a2', fontSize: 22 } })}
                    </Box>
                </Box>
            </CardContent>
        </Card>
    );
}

/* ── Live strip: "Right Now" metrics ── */
function LiveStrip({ stats, loading }) {
    const items = [
        { label: 'Connect Rate', value: stats.total_calls > 0 ? `${((stats.answered_calls / stats.total_calls) * 100).toFixed(1)}%` : '0%', color: '#f59e0b' },
        { label: 'Answered', value: stats.answered_calls, color: '#10b981' },
        { label: 'No Answer', value: stats.no_answer_calls, color: '#f59e0b' },
        { label: 'Failed', value: stats.failed_calls, color: '#ef4444' },
        { label: 'Busy', value: stats.busy_calls, color: '#f59e0b' },
    ];

    return (
        <Box sx={{
            display: 'flex', gap: 1, mb: 3, p: 1.5, borderRadius: 2,
            bgcolor: 'rgba(1,66,162,0.04)', border: '1px solid rgba(1,66,162,0.08)',
            overflowX: 'auto', flexWrap: 'wrap',
        }}>
            {items.map((item) => (
                <Box key={item.label} sx={{ display: 'flex', alignItems: 'center', gap: 0.75, px: 1.5, py: 0.5, borderRadius: 1.5, bgcolor: 'white', border: '1px solid rgba(1,66,162,0.06)' }}>
                    <Box sx={{ width: 6, height: 6, borderRadius: '50%', bgcolor: item.color }} />
                    <Typography variant="caption" color="text.secondary">{item.label}</Typography>
                    <Typography variant="body2" fontWeight={700}>
                        {loading ? <Skeleton width={30} /> : item.value}
                    </Typography>
                </Box>
            ))}
        </Box>
    );
}

/* ── Call activity feed item ── */
function CallFeedItem({ call }) {
    const statusKey = normalizeCallStatus(call.status);
    const statusColor = CALL_STATUS_COLORS[statusKey] || '#64748b';
    const isConnected = statusKey === 'answered';

    return (
        <Box sx={{
            display: 'flex', alignItems: 'center', gap: 1.5, p: 1.5,
            borderRadius: 2, mb: 0.75,
            borderLeft: `3px solid ${statusColor}`,
            bgcolor: 'rgba(1,66,162,0.02)',
            transition: 'background 0.15s',
            '&:hover': { bgcolor: 'rgba(1,66,162,0.05)' },
        }}>
            <Avatar sx={{
                width: 36, height: 36, fontSize: '0.8rem', fontWeight: 600,
                bgcolor: `${statusColor}20`, color: statusColor,
            }}>
                {(call.contact_name || '?')[0]}
            </Avatar>
            <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography fontWeight={600} fontSize="0.85rem" noWrap>{call.contact_name}</Typography>
                <Typography fontSize="0.75rem" color="text.secondary" noWrap>
                    {call.agent_name} · {call.campaign_name}
                </Typography>
            </Box>
            <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                <Chip label={formatCallStatus(call.status)} size="small"
                    sx={{ bgcolor: `${statusColor}15`, color: statusColor, fontSize: '0.65rem', fontWeight: 600, height: 22, mb: 0.25 }} />
                <Typography fontSize="0.7rem" color="text.secondary" display="block">
                    {call.duration_formatted !== '-' ? call.duration_formatted : ''} · {relativeTime(call.initiated_at)}
                </Typography>
            </Box>
        </Box>
    );
}

/* ── Status breakdown as compact bar items ── */
function StatusBreakdown({ statusCounts, loading }) {
    const total = Object.values(statusCounts).reduce((sum, v) => sum + Number(v || 0), 0) || 1;

    if (loading) return <Skeleton height={200} />;
    if (Object.entries(statusCounts).length === 0) {
        return (
            <Box sx={{ textAlign: 'center', py: 6 }}>
                <Typography color="text.secondary">No call status data yet</Typography>
            </Box>
        );
    }

    return (
        <Box sx={{ display: 'grid', gap: 1 }}>
            {Object.entries(statusCounts)
                .sort(([, a], [, b]) => Number(b) - Number(a))
                .map(([status, value]) => {
                    const statusKey = normalizeCallStatus(status);
                    const color = CALL_STATUS_COLORS[statusKey] || '#64748b';
                    const pct = Math.round((Number(value) / total) * 100);
                    return (
                        <Box key={status}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
                                <Typography variant="caption" fontWeight={500}>{formatCallStatus(status)}</Typography>
                                <Typography variant="caption" fontWeight={700}>{Number(value).toLocaleString()} ({pct}%)</Typography>
                            </Box>
                            <LinearProgress
                                value={pct} variant="determinate"
                                sx={{
                                    height: 6, borderRadius: 3,
                                    bgcolor: `${color}15`,
                                    '& .MuiLinearProgress-bar': { bgcolor: color, borderRadius: 3 },
                                }}
                            />
                        </Box>
                    );
                })}
        </Box>
    );
}

const initialStats = {
    total_calls: 0, total_contacts: 0, answered_calls: 0, failed_calls: 0,
    no_answer_calls: 0, busy_calls: 0, cancelled_calls: 0,
};

export default function DashboardPage() {
    const [stats, setStats] = useState(initialStats);
    const [statusCounts, setStatusCounts] = useState({});
    const [recentCalls, setRecentCalls] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [lastRefreshed, setLastRefreshed] = useState(null);
    const navigate = useNavigate();
    const { user } = useAuth();

    const fetchData = React.useCallback(async () => {
        try {
            const [leadsRes, callsRes] = await Promise.all([
                api.get('/leads/?page=1&page_size=1'),
                api.get('/call-logs/?ordering=-initiated_at'),
            ]);
            const leadsData = leadsRes.data || {};
            const callData = callsRes.data || {};
            const summary = callData.summary_all || callData.summary || {};

            setStats({
                total_calls: Number(summary.total_calls || callData.count || 0),
                total_contacts: Number(leadsData.count || 0),
                answered_calls: Number(summary.answered_calls || 0),
                failed_calls: Number(summary.failed_calls || 0),
                no_answer_calls: Number(summary.no_answer_calls || 0),
                busy_calls: Number(summary.busy_calls || 0),
                cancelled_calls: Number(summary.cancelled_calls || 0),
            });
            setStatusCounts(summary.status_counts || {});
            setRecentCalls(Array.isArray(callData.results) ? callData.results : []);
            setError('');
            setLastRefreshed(new Date());
        } catch (err) {
            setError('Failed to load dashboard data');
            console.error(err);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => { fetchData(); }, [fetchData]);
    useVisibleInterval(fetchData, 30000);

    const pieData = stats ? [
        { name: 'Answered', value: stats.answered_calls, color: '#10b981' },
        { name: 'Failed', value: stats.failed_calls, color: '#ef4444' },
        { name: 'No Answer', value: stats.no_answer_calls, color: '#f59e0b' },
    ].filter((d) => d.value > 0) : [];

    const connectRate = stats.total_calls > 0
        ? ((stats.answered_calls / stats.total_calls) * 100).toFixed(1)
        : '0.0';

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <Typography variant="h4" fontWeight={800}>Dashboard</Typography>
                        <Chip
                            icon={<Circle sx={{ fontSize: 6, color: '#10b981', animation: 'pulse 2s infinite', '@keyframes pulse': { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.4 } } }} />}
                            label="Live"
                            size="small"
                            sx={{ bgcolor: '#10b98115', color: '#10b981', fontWeight: 600, fontSize: '0.7rem', height: 22, '& .MuiChip-icon': { color: '#10b981' } }}
                        />
                    </Box>
                    <Typography color="text.secondary" variant="body2">
                        Welcome back, {user?.full_name || user?.username}
                    </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                        variant="outlined" startIcon={<Campaign />}
                        onClick={() => navigate('/campaigns')}
                        sx={{ borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}
                    >
                        Campaigns
                    </Button>
                    <Button
                        variant="contained" startIcon={<Dialpad />}
                        onClick={() => navigate('/dial')}
                        sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                    >
                        Open Dialer
                    </Button>
                </Box>
            </Box>

            {error && (
                <Alert severity="error" sx={{ mb: 2 }} action={
                    <Button color="inherit" size="small" onClick={fetchData}>Retry</Button>
                }>{error}</Alert>
            )}

            {/* Live metrics strip */}
            <LiveStrip stats={stats} loading={loading} />

            {/* Stat cards */}
            <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={6} sm={3}>
                    <StatCard title="Total Calls" value={stats.total_calls.toLocaleString()}
                        icon={<History />} color="#0142a2" loading={loading}
                        onClick={() => navigate('/call-logs')} />
                </Grid>
                <Grid item xs={6} sm={3}>
                    <StatCard title="Contacts" value={stats.total_contacts.toLocaleString()}
                        icon={<Contacts />} color="#3b82f6" loading={loading}
                        onClick={() => navigate('/contacts')} />
                </Grid>
                <Grid item xs={6} sm={3}>
                    <StatCard title="Connected" value={stats.answered_calls.toLocaleString()}
                        icon={<CheckCircle />} color="#10b981" loading={loading}
                        subtitle={`of ${stats.total_calls.toLocaleString()} calls`}
                        onClick={() => navigate('/call-logs?status=answered')} />
                </Grid>
                <Grid item xs={6} sm={3}>
                    <StatCard title="Connect Rate" value={`${connectRate}%`}
                        icon={<TrendingUp />} color="#f59e0b" loading={loading} />
                </Grid>
            </Grid>

            {/* Charts row: Pie + Status Breakdown */}
            <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} md={4}>
                    <Card sx={{ height: '100%' }}>
                        <CardContent>
                            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 1, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                Call Distribution
                            </Typography>
                            {loading ? <Skeleton height={180} /> : pieData.length > 0 ? (
                                <>
                                    <ResponsiveContainer width="100%" height={180}>
                                        <PieChart>
                                            <Pie data={pieData} cx="50%" cy="50%" innerRadius={50} outerRadius={75}
                                                paddingAngle={4} dataKey="value" strokeWidth={0}>
                                                {pieData.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                                            </Pie>
                                            <Tooltip contentStyle={{ background: '#fff', border: 'none', borderRadius: 8, boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }} />
                                        </PieChart>
                                    </ResponsiveContainer>
                                    <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap', mt: 1 }}>
                                        {pieData.map((d) => (
                                            <Box key={d.name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: d.color }} />
                                                <Typography variant="caption" color="text.secondary">{d.name}: {d.value}</Typography>
                                            </Box>
                                        ))}
                                    </Box>
                                </>
                            ) : (
                                <Box sx={{ textAlign: 'center', py: 6, color: '#94a3b8' }}>
                                    <Phone sx={{ fontSize: 40, mb: 1 }} />
                                    <Typography variant="body2">No calls yet</Typography>
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                <Grid item xs={12} md={8}>
                    <Card sx={{ height: '100%' }}>
                        <CardContent>
                            <Typography variant="subtitle2" fontWeight={700} sx={{ mb: 2, textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                Status Breakdown
                            </Typography>
                            <StatusBreakdown statusCounts={statusCounts} loading={loading} />
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>

            {/* Recent call activity feed */}
            <Card>
                <CardContent>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Typography variant="subtitle2" fontWeight={700} sx={{ textTransform: 'uppercase', letterSpacing: '0.04em', color: '#64748b', fontSize: '0.72rem' }}>
                                Recent Activity
                            </Typography>
                            {lastRefreshed && (
                                <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.68rem' }}>
                                    Updated {relativeTime(lastRefreshed)}
                                </Typography>
                            )}
                        </Box>
                        <Button size="small" onClick={() => navigate('/call-logs')} sx={{ color: '#1a5bc4', textTransform: 'none', fontWeight: 600 }}>
                            View all
                        </Button>
                    </Box>
                    {loading ? (
                        Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height={56} sx={{ mb: 0.75, borderRadius: 2 }} />)
                    ) : recentCalls.length === 0 ? (
                        <Box sx={{ textAlign: 'center', py: 4 }}>
                            <Phone sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                            <Typography color="text.secondary">No call activity yet. Start dialing!</Typography>
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>Make your first call to see activity here</Typography>
                            <Button variant="contained" size="small" startIcon={<Dialpad />} onClick={() => navigate('/dial')} sx={{ mt: 2, bgcolor: '#0142a2' }}>
                                Open Dialer
                            </Button>
                        </Box>
                    ) : recentCalls.slice(0, 10).map((call) => (
                        <CallFeedItem key={call.id} call={call} />
                    ))}
                </CardContent>
            </Card>
        </Box>
    );
}
