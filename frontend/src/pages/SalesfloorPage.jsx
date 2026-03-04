import React, { useEffect, useState } from 'react';
import {
    Box, Card, CardContent, Typography, Grid, Chip, Avatar,
    Button, Divider, TextField, Alert, List, ListItem,
    ListItemAvatar, ListItemText, Switch, FormControlLabel
} from '@mui/material';
import { Phone, Headphones, Circle, PlayArrow, Stop, Timer } from '@mui/icons-material';
import api from '../services/api';
import useAuth from '../context/useAuth';

export default function SalesfloorPage() {
    const [campaigns, setCampaigns] = useState([]);
    const [recentCalls, setRecentCalls] = useState([]);
    const [available, setAvailable] = useState(true);
    const { user } = useAuth();

    useEffect(() => {
        api.get('/campaigns/?status=active').then(r => setCampaigns(r.data.results || r.data));
        api.get('/call-logs/?ordering=-initiated_at').then(r => setRecentCalls((r.data.results || r.data).slice(0, 10)));
    }, []);

    const toggleAvailability = async () => {
        try {
            await api.patch('/auth/users/update_availability/', { is_available: !available });
            setAvailable(!available);
        } catch (e) { }
    };

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Salesfloor</Typography>
                    <Typography color="text.secondary" variant="body2">Real-time agent activity and live campaigns</Typography>
                </Box>
                <FormControlLabel
                    control={<Switch checked={available} onChange={toggleAvailability} sx={{ '& .MuiSwitch-switchBase.Mui-checked': { color: '#10b981' } }} />}
                    label={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                            <Circle sx={{ fontSize: 8, color: available ? '#10b981' : '#64748b' }} />
                            <Typography variant="body2" color={available ? '#10b981' : '#64748b'} fontWeight={600}>
                                {available ? 'Available' : 'Away'}
                            </Typography>
                        </Box>
                    }
                />
            </Box>

            <Grid container spacing={3}>
                {/* Agent Status */}
                <Grid item xs={12} md={4}>
                    <Card>
                        <CardContent>
                            <Typography variant="subtitle1" fontWeight={600} mb={2}>🎧 My Status</Typography>
                            <Box sx={{ textAlign: 'center', py: 2 }}>
                                <Avatar sx={{
                                    width: 72, height: 72, fontSize: '1.5rem', mx: 'auto', mb: 2,
                                    bgcolor: '#6366f1', border: `3px solid ${available ? '#10b981' : '#64748b'}`
                                }}>
                                    {user?.full_name?.[0] || user?.username?.[0]}
                                </Avatar>
                                <Typography variant="h6" fontWeight={600}>{user?.full_name || user?.username}</Typography>
                                <Chip
                                    label={available ? '🟢 Available' : '🔴 Away'}
                                    sx={{ bgcolor: available ? '#10b98125' : '#ef444425', color: available ? '#10b981' : '#ef4444', mt: 1 }}
                                />
                            </Box>
                            <Divider sx={{ my: 2, borderColor: 'rgba(99,102,241,0.1)' }} />
                            <Typography variant="caption" color="text.secondary">Role</Typography>
                            <Typography fontWeight={500} textTransform="capitalize">{user?.role}</Typography>
                        </CardContent>
                    </Card>
                </Grid>

                {/* Active Campaigns */}
                <Grid item xs={12} md={8}>
                    <Card>
                        <CardContent>
                            <Typography variant="subtitle1" fontWeight={600} mb={2}>⚡ Active Campaigns</Typography>
                            {campaigns.length === 0 ? (
                                <Box sx={{ textAlign: 'center', py: 4, color: '#64748b' }}>
                                    <Headphones sx={{ fontSize: 48, mb: 1 }} />
                                    <Typography>No active campaigns right now</Typography>
                                </Box>
                            ) : campaigns.map(c => (
                                <Box key={c.id} sx={{
                                    p: 2, mb: 1.5, borderRadius: 2,
                                    bgcolor: 'rgba(16,185,129,0.05)', border: '1px solid rgba(16,185,129,0.2)'
                                }}>
                                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                                        <Typography fontWeight={600}>{c.name}</Typography>
                                        <Chip label="LIVE" size="small"
                                            sx={{ bgcolor: '#10b98125', color: '#10b981', fontSize: '0.65rem', fontWeight: 700 }} />
                                    </Box>
                                    <Box sx={{ display: 'flex', gap: 3 }}>
                                        <Box>
                                            <Typography variant="caption" color="text.secondary">Dialed</Typography>
                                            <Typography fontWeight={700} color="#6366f1">{c.dialed_contacts}/{c.total_contacts}</Typography>
                                        </Box>
                                        <Box>
                                            <Typography variant="caption" color="text.secondary">Connected</Typography>
                                            <Typography fontWeight={700} color="#10b981">{c.connected_calls}</Typography>
                                        </Box>
                                        <Box>
                                            <Typography variant="caption" color="text.secondary">Rate</Typography>
                                            <Typography fontWeight={700} color="#f59e0b">{c.connect_rate}%</Typography>
                                        </Box>
                                        <Box>
                                            <Typography variant="caption" color="text.secondary">Agent</Typography>
                                            <Typography fontWeight={600} fontSize="0.9rem">{c.assigned_agent_name}</Typography>
                                        </Box>
                                    </Box>
                                </Box>
                            ))}
                        </CardContent>
                    </Card>
                </Grid>

                {/* Live Feed */}
                <Grid item xs={12}>
                    <Card>
                        <CardContent>
                            <Typography variant="subtitle1" fontWeight={600} mb={2}>📞 Live Call Feed</Typography>
                            <List disablePadding>
                                {recentCalls.map(call => (
                                    <ListItem key={call.id} divider sx={{ borderColor: 'rgba(99,102,241,0.08)' }}>
                                        <ListItemAvatar>
                                            <Avatar sx={{ bgcolor: call.status === 'answered' ? '#10b98130' : '#6366f130', color: call.status === 'answered' ? '#10b981' : '#818cf8', width: 36, height: 36, fontSize: '0.8rem' }}>
                                                {call.contact_name?.[0] || '?'}
                                            </Avatar>
                                        </ListItemAvatar>
                                        <ListItemText
                                            primary={<Typography fontWeight={500} fontSize="0.9rem">{call.contact_name}</Typography>}
                                            secondary={<Typography fontSize="0.8rem" color="text.secondary">{call.contact_phone} · {call.campaign_name}</Typography>}
                                        />
                                        <Box sx={{ textAlign: 'right' }}>
                                            <Chip label={call.status} size="small"
                                                sx={{
                                                    bgcolor: call.status === 'answered' ? '#10b98125' : '#64748b25',
                                                    color: call.status === 'answered' ? '#10b981' : '#94a3b8',
                                                    fontSize: '0.7rem', mb: 0.5
                                                }} />
                                            <Typography fontSize="0.75rem" color="text.secondary" display="block">
                                                {call.duration_formatted !== '-' ? `⏱ ${call.duration_formatted}` : new Date(call.initiated_at).toLocaleTimeString()}
                                            </Typography>
                                        </Box>
                                    </ListItem>
                                ))}
                            </List>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
