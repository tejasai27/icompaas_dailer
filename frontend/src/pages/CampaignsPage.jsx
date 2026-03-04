import React, { useEffect, useState } from 'react';
import {
    Box, Grid, Card, CardContent, Typography, Chip, Button,
    IconButton, Menu, MenuItem, LinearProgress, Skeleton,
    Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
    Tooltip, Dialog, DialogTitle, DialogContent, DialogActions
} from '@mui/material';
import {
    Add, PlayArrow, Pause, BarChart, MoreVert,
    Campaign, CheckCircle, Phone, TrendingUp, Stop
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
    active: { bg: '#10b98125', text: '#10b981', label: 'Active' },
    paused: { bg: '#f59e0b25', text: '#f59e0b', label: 'Paused' },
    completed: { bg: '#6366f125', text: '#6366f1', label: 'Completed' },
    draft: { bg: '#64748b25', text: '#94a3b8', label: 'Draft' },
    archived: { bg: '#37415125', text: '#64748b', label: 'Archived' },
};

const MODE_LABELS = { power: '⚡ Power', dynamic: '🔀 Dynamic', preview: '👁 Preview' };

function CampaignCard({ campaign, onAction }) {
    const navigate = useNavigate();
    const [anchorEl, setAnchorEl] = useState(null);
    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;

    const handleStart = async () => {
        try {
            await api.post(`/campaigns/${campaign.id}/start/`);
            toast.success('Campaign started!');
            onAction();
        } catch (e) { toast.error(e.response?.data?.error || 'Failed'); }
    };

    const handlePause = async () => {
        try {
            await api.post(`/campaigns/${campaign.id}/pause/`);
            toast.success('Campaign paused');
            onAction();
        } catch (e) { toast.error(e.response?.data?.error || 'Failed'); }
    };

    return (
        <Card sx={{
            cursor: 'pointer',
            transition: 'all 0.2s',
            '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 32px rgba(99,102,241,0.2)' },
            border: campaign.status === 'active' ? '1px solid rgba(16,185,129,0.3)' : '1px solid rgba(99,102,241,0.1)',
        }}>
            <CardContent>
                {/* Header */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1.5 }}>
                    <Box sx={{ flex: 1, mr: 1 }}>
                        <Typography fontWeight={700} noWrap
                            onClick={() => navigate(`/campaigns/${campaign.id}`)}
                            sx={{ '&:hover': { color: '#6366f1' } }}>
                            {campaign.name}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                            <Chip label={statusCfg.label} size="small"
                                sx={{ bgcolor: statusCfg.bg, color: statusCfg.text, height: 20, fontSize: '0.7rem' }} />
                            <Chip label={MODE_LABELS[campaign.dialing_mode] || campaign.dialing_mode}
                                size="small" variant="outlined"
                                sx={{ height: 20, fontSize: '0.7rem', borderColor: 'rgba(99,102,241,0.3)', color: '#818cf8' }} />
                        </Box>
                    </Box>
                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); setAnchorEl(e.currentTarget); }}>
                        <MoreVert fontSize="small" />
                    </IconButton>
                    <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
                        <MenuItem onClick={() => { navigate(`/campaigns/${campaign.id}`); setAnchorEl(null); }}>View Details</MenuItem>
                        <MenuItem onClick={() => { navigate(`/campaigns/${campaign.id}/analytics`); setAnchorEl(null); }}>Analytics</MenuItem>
                    </Menu>
                </Box>

                {/* Progress */}
                <Box sx={{ mb: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                        <Typography variant="caption" color="text.secondary">
                            {campaign.dialed_contacts}/{campaign.total_contacts} dialed
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                            {campaign.progress_percentage}%
                        </Typography>
                    </Box>
                    <LinearProgress
                        value={campaign.progress_percentage}
                        variant="determinate"
                        sx={{
                            height: 6, borderRadius: 3,
                            bgcolor: 'rgba(99,102,241,0.1)',
                            '& .MuiLinearProgress-bar': {
                                bgcolor: campaign.status === 'active' ? '#10b981' : '#6366f1',
                                borderRadius: 3,
                            }
                        }}
                    />
                </Box>

                {/* Stats row */}
                <Grid container spacing={1} sx={{ mb: 2 }}>
                    <Grid item xs={4}>
                        <Box sx={{ textAlign: 'center', p: 0.5, borderRadius: 1, bgcolor: 'rgba(99,102,241,0.05)' }}>
                            <Typography fontSize="1.1rem" fontWeight={700} color="#6366f1">{campaign.total_contacts}</Typography>
                            <Typography variant="caption" color="text.secondary">Total</Typography>
                        </Box>
                    </Grid>
                    <Grid item xs={4}>
                        <Box sx={{ textAlign: 'center', p: 0.5, borderRadius: 1, bgcolor: 'rgba(16,185,129,0.05)' }}>
                            <Typography fontSize="1.1rem" fontWeight={700} color="#10b981">{campaign.connected_calls}</Typography>
                            <Typography variant="caption" color="text.secondary">Connected</Typography>
                        </Box>
                    </Grid>
                    <Grid item xs={4}>
                        <Box sx={{ textAlign: 'center', p: 0.5, borderRadius: 1, bgcolor: 'rgba(245,158,11,0.05)' }}>
                            <Typography fontSize="1.1rem" fontWeight={700} color="#f59e0b">{campaign.connect_rate}%</Typography>
                            <Typography variant="caption" color="text.secondary">Rate</Typography>
                        </Box>
                    </Grid>
                </Grid>

                {/* Agent */}
                <Typography variant="caption" color="text.secondary" display="block" mb={1.5}>
                    Agent: {campaign.assigned_agent_name}
                </Typography>

                {/* Actions */}
                <Box sx={{ display: 'flex', gap: 1 }}>
                    {campaign.status === 'active' ? (
                        <Button size="small" variant="outlined" startIcon={<Pause />} onClick={handlePause}
                            sx={{ borderColor: '#f59e0b', color: '#f59e0b', flex: 1 }}>Pause</Button>
                    ) : campaign.status === 'paused' ? (
                        <Button size="small" variant="contained" startIcon={<PlayArrow />} onClick={handleStart}
                            sx={{ bgcolor: '#10b981', flex: 1, '&:hover': { bgcolor: '#059669' } }}>Resume</Button>
                    ) : campaign.status === 'draft' ? (
                        <Button size="small" variant="contained" startIcon={<PlayArrow />} onClick={handleStart}
                            sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)', flex: 1 }}>Start</Button>
                    ) : null}
                    <Tooltip title="Analytics">
                        <IconButton size="small" onClick={() => navigate(`/campaigns/${campaign.id}`)}
                            sx={{ border: '1px solid rgba(99,102,241,0.3)', color: '#818cf8' }}>
                            <BarChart fontSize="small" />
                        </IconButton>
                    </Tooltip>
                </Box>
            </CardContent>
        </Card>
    );
}

export default function CampaignsPage() {
    const [campaigns, setCampaigns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');
    const navigate = useNavigate();

    const fetchCampaigns = async () => {
        try {
            const params = filter !== 'all' ? `?status=${filter}` : '';
            const { data } = await api.get(`/campaigns/${params}`);
            setCampaigns(data.results || data);
        } catch (e) {
            toast.error('Failed to load campaigns');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => { fetchCampaigns(); }, [filter]);

    const filters = ['all', 'active', 'paused', 'draft', 'completed'];

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Campaigns</Typography>
                    <Typography color="text.secondary" variant="body2">Manage your dialing campaigns</Typography>
                </Box>
                <Button
                    variant="contained"
                    startIcon={<Add />}
                    onClick={() => navigate('/campaigns/new')}
                    sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)' }}
                >
                    Create Campaign
                </Button>
            </Box>

            {/* Filter tabs */}
            <Box sx={{ display: 'flex', gap: 1, mb: 3, flexWrap: 'wrap' }}>
                {filters.map(f => (
                    <Chip
                        key={f}
                        label={f.charAt(0).toUpperCase() + f.slice(1)}
                        onClick={() => setFilter(f)}
                        variant={filter === f ? 'filled' : 'outlined'}
                        sx={{
                            bgcolor: filter === f ? 'rgba(99,102,241,0.2)' : 'transparent',
                            color: filter === f ? '#818cf8' : '#94a3b8',
                            borderColor: filter === f ? '#6366f1' : 'rgba(99,102,241,0.3)',
                            cursor: 'pointer',
                        }}
                    />
                ))}
            </Box>

            {loading ? (
                <Grid container spacing={2}>
                    {Array.from({ length: 6 }).map((_, i) => (
                        <Grid item xs={12} sm={6} md={4} key={i}>
                            <Card><CardContent><Skeleton height={200} /></CardContent></Card>
                        </Grid>
                    ))}
                </Grid>
            ) : campaigns.length === 0 ? (
                <Card>
                    <CardContent sx={{ textAlign: 'center', py: 8 }}>
                        <Campaign sx={{ fontSize: 64, color: '#374151', mb: 2 }} />
                        <Typography variant="h6" color="text.secondary">No campaigns found</Typography>
                        <Button variant="contained" startIcon={<Add />} sx={{ mt: 2 }}
                            onClick={() => navigate('/campaigns/new')}>
                            Create Your First Campaign
                        </Button>
                    </CardContent>
                </Card>
            ) : (
                <Grid container spacing={2}>
                    {campaigns.map(c => (
                        <Grid item xs={12} sm={6} md={4} key={c.id}>
                            <CampaignCard campaign={c} onAction={fetchCampaigns} />
                        </Grid>
                    ))}
                </Grid>
            )}
        </Box>
    );
}
