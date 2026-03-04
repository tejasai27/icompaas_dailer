import React, { useEffect, useState } from 'react';
import {
    Box, Grid, Card, CardContent, Typography, Chip, Button,
    Table, TableBody, TableCell, TableContainer, TableHead,
    TableRow, Avatar, LinearProgress, Skeleton, CircularProgress
} from '@mui/material';
import {
    Campaign, Phone, CheckCircle, Cancel, TrendingUp,
    PlayArrow, Pause, BarChart, Add
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
import api from '../services/api';
import useAuth from '../context/useAuth';

const StatCard = ({ title, value, icon, color, subtitle, loading }) => (
    <Card sx={{ height: '100%' }}>
        <CardContent>
            <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
                <Box>
                    <Typography variant="body2" color="text.secondary" gutterBottom>{title}</Typography>
                    {loading ? <Skeleton width={80} height={40} /> : (
                        <Typography variant="h4" fontWeight={700} color={color || 'text.primary'}>
                            {value}
                        </Typography>
                    )}
                    {subtitle && <Typography variant="caption" color="text.secondary">{subtitle}</Typography>}
                </Box>
                <Box sx={{
                    width: 48, height: 48, borderRadius: 2,
                    bgcolor: `${color || '#6366f1'}20`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                    {React.cloneElement(icon, { sx: { color: color || '#6366f1', fontSize: 22 } })}
                </Box>
            </Box>
        </CardContent>
    </Card>
);

const statusColors = {
    active: '#10b981', paused: '#f59e0b', completed: '#6366f1',
    draft: '#64748b', archived: '#374151'
};

const callStatusColors = { answered: '#10b981', 'no-answer': '#f59e0b', busy: '#f59e0b', failed: '#ef4444', completed: '#6366f1' };

export default function DashboardPage() {
    const [stats, setStats] = useState(null);
    const [campaigns, setCampaigns] = useState([]);
    const [recentCalls, setRecentCalls] = useState([]);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();
    const { user } = useAuth();

    useEffect(() => {
        const fetchData = async () => {
            try {
                const [statsRes, callsRes] = await Promise.all([
                    api.get('/campaigns/dashboard_stats/'),
                    api.get('/call-logs/?ordering=-initiated_at'),
                ]);
                setStats(statsRes.data);
                setCampaigns(statsRes.data.recent_campaigns || []);
                setRecentCalls(callsRes.data.results || []);
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };
        fetchData();
        const interval = setInterval(fetchData, 30000);
        return () => clearInterval(interval);
    }, []);

    const pieData = stats ? [
        { name: 'Answered', value: stats.answered_calls, color: '#10b981' },
        { name: 'Failed', value: stats.failed_calls, color: '#ef4444' },
        { name: 'No Answer', value: Math.max(0, stats.total_calls - stats.answered_calls - stats.failed_calls), color: '#f59e0b' },
    ] : [];

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Dashboard</Typography>
                    <Typography color="text.secondary" variant="body2">
                        Welcome back, {user?.full_name || user?.username} 👋
                    </Typography>
                </Box>
                <Button
                    variant="contained"
                    startIcon={<Add />}
                    onClick={() => navigate('/campaigns/new')}
                    sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)' }}
                >
                    New Campaign
                </Button>
            </Box>

            {/* Stats row */}
            <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard title="Total Campaigns" value={stats?.total_campaigns ?? '—'}
                        icon={<Campaign />} color="#6366f1" loading={loading}
                        subtitle={`${stats?.active_campaigns ?? 0} active`} />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard title="Total Contacts" value={stats?.total_contacts?.toLocaleString() ?? '—'}
                        icon={<Phone />} color="#3b82f6" loading={loading} />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard title="Calls Answered" value={stats?.answered_calls ?? '—'}
                        icon={<CheckCircle />} color="#10b981" loading={loading}
                        subtitle={`of ${stats?.total_calls ?? 0} total`} />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard
                        title="Connect Rate"
                        value={stats?.total_calls > 0
                            ? `${((stats.answered_calls / stats.total_calls) * 100).toFixed(1)}%`
                            : '—'}
                        icon={<TrendingUp />} color="#f59e0b" loading={loading} />
                </Grid>
            </Grid>

            <Grid container spacing={2} sx={{ mb: 3 }}>
                {/* Call distribution chart */}
                <Grid item xs={12} md={4}>
                    <Card sx={{ height: 280 }}>
                        <CardContent>
                            <Typography variant="subtitle1" fontWeight={600} mb={2}>Call Distribution</Typography>
                            {loading ? <Skeleton height={200} /> : (
                                <ResponsiveContainer width="100%" height={200}>
                                    <PieChart>
                                        <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={80}
                                            paddingAngle={4} dataKey="value">
                                            {pieData.map((entry, i) => (
                                                <Cell key={i} fill={entry.color} />
                                            ))}
                                        </Pie>
                                        <Tooltip contentStyle={{ background: '#1a1a2e', border: '1px solid rgba(99,102,241,0.3)', borderRadius: 8 }} />
                                    </PieChart>
                                </ResponsiveContainer>
                            )}
                            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center', flexWrap: 'wrap' }}>
                                {pieData.map(d => (
                                    <Box key={d.name} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                        <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: d.color }} />
                                        <Typography variant="caption" color="text.secondary">{d.name}: {d.value}</Typography>
                                    </Box>
                                ))}
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>

                {/* Recent Campaigns */}
                <Grid item xs={12} md={8}>
                    <Card>
                        <CardContent>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                                <Typography variant="subtitle1" fontWeight={600}>Recent Campaigns</Typography>
                                <Button size="small" onClick={() => navigate('/campaigns')} sx={{ color: '#6366f1' }}>
                                    View all
                                </Button>
                            </Box>
                            {loading ? <Skeleton height={200} /> : (
                                <Box>
                                    {campaigns.length === 0 ? (
                                        <Box sx={{ textAlign: 'center', py: 4 }}>
                                            <Campaign sx={{ fontSize: 40, color: '#374151', mb: 1 }} />
                                            <Typography color="text.secondary">No campaigns yet</Typography>
                                            <Button variant="outlined" size="small" sx={{ mt: 1 }}
                                                onClick={() => navigate('/campaigns/new')}>Create Campaign</Button>
                                        </Box>
                                    ) : campaigns.map(c => (
                                        <Box
                                            key={c.id}
                                            onClick={() => navigate(`/campaigns/${c.id}`)}
                                            sx={{
                                                display: 'flex', alignItems: 'center', gap: 2, p: 1.5, mb: 1,
                                                borderRadius: 2, cursor: 'pointer',
                                                '&:hover': { bgcolor: 'rgba(99,102,241,0.08)' },
                                                border: '1px solid rgba(99,102,241,0.08)'
                                            }}
                                        >
                                            <Box sx={{ flex: 1, minWidth: 0 }}>
                                                <Typography fontWeight={600} noWrap fontSize="0.875rem">{c.name}</Typography>
                                                <Typography variant="caption" color="text.secondary">
                                                    {c.dialed_contacts}/{c.total_contacts} dialed
                                                </Typography>
                                                <LinearProgress
                                                    value={c.progress_percentage}
                                                    variant="determinate"
                                                    sx={{ mt: 0.5, height: 4, borderRadius: 2, bgcolor: 'rgba(99,102,241,0.1)', '& .MuiLinearProgress-bar': { bgcolor: '#6366f1' } }}
                                                />
                                            </Box>
                                            <Box sx={{ textAlign: 'right', flexShrink: 0 }}>
                                                <Chip
                                                    label={c.status}
                                                    size="small"
                                                    sx={{ bgcolor: `${statusColors[c.status] || '#64748b'}25`, color: statusColors[c.status] || '#64748b', mb: 0.5 }}
                                                />
                                                <Typography variant="caption" color="text.secondary" display="block">
                                                    {c.connect_rate}% connect
                                                </Typography>
                                            </Box>
                                        </Box>
                                    ))}
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>

            {/* Recent Calls table */}
            <Card>
                <CardContent>
                    <Typography variant="subtitle1" fontWeight={600} mb={2}>Recent Call Activity</Typography>
                    <TableContainer>
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    <TableCell>Contact</TableCell>
                                    <TableCell>Campaign</TableCell>
                                    <TableCell>Agent</TableCell>
                                    <TableCell>Status</TableCell>
                                    <TableCell>Duration</TableCell>
                                    <TableCell>Time</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {loading ? (
                                    Array.from({ length: 5 }).map((_, i) => (
                                        <TableRow key={i}>
                                            {Array.from({ length: 6 }).map((_, j) => (
                                                <TableCell key={j}><Skeleton /></TableCell>
                                            ))}
                                        </TableRow>
                                    ))
                                ) : recentCalls.length === 0 ? (
                                    <TableRow>
                                        <TableCell colSpan={6} align="center" sx={{ py: 4, color: '#64748b' }}>
                                            No call activity yet
                                        </TableCell>
                                    </TableRow>
                                ) : recentCalls.slice(0, 8).map(call => (
                                    <TableRow key={call.id} hover>
                                        <TableCell>
                                            <Box>
                                                <Typography fontSize="0.875rem" fontWeight={500}>{call.contact_name}</Typography>
                                                <Typography fontSize="0.75rem" color="text.secondary">{call.contact_phone}</Typography>
                                            </Box>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.875rem" noWrap maxWidth={140}>{call.campaign_name}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.875rem">{call.agent_name}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Chip
                                                label={call.status}
                                                size="small"
                                                sx={{ bgcolor: `${callStatusColors[call.status] || '#64748b'}25`, color: callStatusColors[call.status] || '#64748b' }}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.875rem">{call.duration_formatted}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.75rem" color="text.secondary">
                                                {new Date(call.initiated_at).toLocaleTimeString()}
                                            </Typography>
                                        </TableCell>
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>
                </CardContent>
            </Card>
        </Box>
    );
}
