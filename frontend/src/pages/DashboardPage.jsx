import React, { useEffect, useState } from 'react';
import {
    Box, Grid, Card, CardContent, Typography, Chip, Button,
    Table, TableBody, TableCell, TableContainer, TableHead,
    TableRow, Skeleton, Paper
} from '@mui/material';
import {
    Phone, CheckCircle, TrendingUp, Contacts, History, ArrowUpward
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts';
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
                    bgcolor: `${color || '#0142a2'}20`,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                    {React.cloneElement(icon, { sx: { color: color || '#0142a2', fontSize: 22 } })}
                </Box>
            </Box>
        </CardContent>
    </Card>
);

const callStatusColors = {
    answered: '#10b981',
    'sdr-cut': '#ef4444',
    'no-answer': '#f59e0b',
    no_answer: '#f59e0b',
    busy: '#f59e0b',
    failed: '#ef4444',
    completed: '#0142a2',
    initiated: '#3b82f6',
    cancelled: '#64748b',
};

const normalizeCallStatus = (status) => String(status || '').trim().toLowerCase().replace(/_/g, '-');
const formatCallStatus = (status) => {
    const normalized = normalizeCallStatus(status);
    if (!normalized) return '-';
    if (normalized === 'sdr-cut') return 'SDR Cut the Call';
    return normalized
        .split('-')
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
};

const initialStats = {
    total_calls: 0,
    total_contacts: 0,
    answered_calls: 0,
    failed_calls: 0,
    no_answer_calls: 0,
    busy_calls: 0,
    cancelled_calls: 0,
};

export default function DashboardPage() {
    const [stats, setStats] = useState(initialStats);
    const [statusCounts, setStatusCounts] = useState({});
    const [recentCalls, setRecentCalls] = useState([]);
    const [loading, setLoading] = useState(true);
    const navigate = useNavigate();
    const { user } = useAuth();

    useEffect(() => {
        const fetchData = async () => {
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
        { name: 'No Answer', value: stats.no_answer_calls, color: '#f59e0b' },
    ] : [];

    const connectRate = stats.total_calls > 0
        ? ((stats.answered_calls / stats.total_calls) * 100).toFixed(1)
        : '0.0';

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
                    startIcon={<Phone />}
                    onClick={() => navigate('/dial')}
                    sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                >
                    Open Dialer
                </Button>
            </Box>

            {/* Stats row */}
            <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard title="Total Calls" value={stats.total_calls.toLocaleString()}
                        icon={<History />} color="#0142a2" loading={loading} />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard title="Total Contacts" value={stats.total_contacts.toLocaleString()}
                        icon={<Contacts />} color="#3b82f6" loading={loading} />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard title="Calls Answered" value={stats.answered_calls.toLocaleString()}
                        icon={<CheckCircle />} color="#10b981" loading={loading}
                        subtitle={`of ${stats.total_calls.toLocaleString()} total`} />
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                    <StatCard
                        title="Connect Rate"
                        value={`${connectRate}%`}
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
                                        <Tooltip contentStyle={{ background: '#ffffff', border: '1px solid rgba(1,66,162,0.3)', borderRadius: 8 }} />
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

                {/* Status Breakdown */}
                <Grid item xs={12} md={8}>
                    <Card>
                        <CardContent>
                            <Typography variant="subtitle1" fontWeight={600} mb={2}>Call Status Breakdown</Typography>
                            {loading ? <Skeleton height={200} /> : (
                                <Grid container spacing={1.5}>
                                    {Object.entries(statusCounts).length === 0 ? (
                                        <Grid item xs={12}>
                                            <Box sx={{ textAlign: 'center', py: 8 }}>
                                                <Typography color="text.secondary">No call status data yet</Typography>
                                            </Box>
                                        </Grid>
                                    ) : Object.entries(statusCounts).map(([status, value]) => (
                                        <Grid item xs={6} sm={4} md={3} key={status}>
                                            <Box sx={{ p: 1.5, borderRadius: 2, bgcolor: 'rgba(1,66,162,0.08)', border: '1px solid rgba(1,66,162,0.12)' }}>
                                                <Typography variant="caption" color="text.secondary">{formatCallStatus(status)}</Typography>
                                                <Typography variant="h6" fontWeight={700}>{Number(value).toLocaleString()}</Typography>
                                            </Box>
                                        </Grid>
                                    ))}
                                </Grid>
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
                                    <TableCell>SDR</TableCell>
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
                                ) : recentCalls.slice(0, 8).map(call => {
                                    const statusKey = normalizeCallStatus(call.status);
                                    return (
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
                                                label={formatCallStatus(call.status)}
                                                size="small"
                                                sx={{ bgcolor: `${callStatusColors[statusKey] || '#64748b'}25`, color: callStatusColors[statusKey] || '#64748b' }}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.875rem">{call.duration_formatted}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.75rem" color="text.secondary">
                                                {call.initiated_at ? new Date(call.initiated_at).toLocaleTimeString() : '-'}
                                            </Typography>
                                        </TableCell>
                                    </TableRow>
                                )})}
                            </TableBody>
                        </Table>
                    </TableContainer>
                </CardContent>
            </Card>
        </Box>
    );
}
