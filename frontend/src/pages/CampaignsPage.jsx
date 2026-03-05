import React, { useEffect, useState } from 'react';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Grid,
    IconButton,
    LinearProgress,
    Skeleton,
    ToggleButton,
    ToggleButtonGroup,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    Add,
    Campaign,
    DeleteOutline,
    Dialpad,
    Pause,
    PlayArrow,
    ViewAgenda,
    ViewModule,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
    active: { bg: '#10b98125', text: '#10b981', label: 'Active' },
    paused: { bg: '#f59e0b25', text: '#f59e0b', label: 'Paused' },
    completed: { bg: '#0142a225', text: '#0142a2', label: 'Completed' },
    draft: { bg: '#64748b25', text: '#94a3b8', label: 'Draft' },
    archived: { bg: '#37415125', text: '#94a3b8', label: 'Archived' },
};

const MODE_LABELS = {
    power: '⚡ Power',
    dynamic: '🔀 Dynamic',
};

function CampaignCard({ campaign, onAction, onDelete, deleting }) {
    const navigate = useNavigate();
    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;

    return (
        <Card
            sx={{
                transition: 'all 0.2s',
                '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 32px rgba(1,66,162,0.2)' },
                border: campaign.status === 'active'
                    ? '1px solid rgba(16,185,129,0.3)'
                    : '1px solid rgba(1,66,162,0.1)',
            }}
        >
            <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1.5 }}>
                    <Box sx={{ flex: 1, mr: 1 }}>
                        <Typography
                            fontWeight={700}
                            noWrap
                            onClick={() => navigate(`/campaigns/${campaign.id}`)}
                            sx={{ cursor: 'pointer', '&:hover': { color: '#0142a2' } }}
                        >
                            {campaign.name}
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                            <Chip
                                label={statusCfg.label}
                                size="small"
                                sx={{ bgcolor: statusCfg.bg, color: statusCfg.text, height: 20, fontSize: '0.7rem' }}
                            />
                            <Chip
                                label={MODE_LABELS[campaign.dialing_mode] || campaign.dialing_mode}
                                size="small"
                                variant="outlined"
                                sx={{ height: 20, fontSize: '0.7rem', borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}
                            />
                        </Box>
                    </Box>
                </Box>

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
                            height: 6,
                            borderRadius: 3,
                            bgcolor: 'rgba(1,66,162,0.1)',
                            '& .MuiLinearProgress-bar': {
                                bgcolor: campaign.status === 'active' ? '#10b981' : '#0142a2',
                                borderRadius: 3,
                            },
                        }}
                    />
                </Box>

                <Grid container spacing={1} sx={{ mb: 2 }}>
                    <Grid item xs={4}>
                        <Box sx={{ textAlign: 'center', p: 0.5, borderRadius: 1, bgcolor: 'rgba(1,66,162,0.05)' }}>
                            <Typography fontSize="1.1rem" fontWeight={700} color="#0142a2">{campaign.total_contacts}</Typography>
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

                <Typography variant="caption" color="text.secondary" display="block" mb={1.5}>
                    Agent: {campaign.assigned_agent_name || 'Unassigned'}
                </Typography>

                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {campaign.status === 'active' ? (
                        <Button size="small" variant="outlined" startIcon={<Pause />} onClick={() => onAction(campaign, 'pause')}
                            sx={{ borderColor: '#f59e0b', color: '#f59e0b', flex: 1 }}>
                            Pause
                        </Button>
                    ) : campaign.status === 'draft' || campaign.status === 'paused' ? (
                        <Button size="small" variant="contained" startIcon={<PlayArrow />}
                            onClick={() => onAction(campaign, campaign.status === 'draft' ? 'start' : 'resume')}
                            sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)', flex: 1 }}>
                            {campaign.status === 'draft' ? 'Start' : 'Resume'}
                        </Button>
                    ) : null}

                    <Button
                        size="small"
                        variant="outlined"
                        startIcon={<Dialpad />}
                        onClick={() => navigate(`/dial?campaign_id=${campaign.id}`)}
                        sx={{ borderColor: 'rgba(1,66,162,0.5)', color: '#1a5bc4' }}
                    >
                        Dialer
                    </Button>
                    <Button
                        size="small"
                        variant="text"
                        onClick={() => navigate(`/campaigns/${campaign.id}`)}
                        sx={{ color: '#94a3b8' }}
                    >
                        Details
                    </Button>
                    <Button
                        size="small"
                        color="error"
                        variant="text"
                        startIcon={<DeleteOutline />}
                        onClick={() => onDelete(campaign)}
                        disabled={deleting}
                    >
                        Delete
                    </Button>
                </Box>
            </CardContent>
        </Card>
    );
}

function CampaignRow({ campaign, onAction, onDelete, deleting }) {
    const navigate = useNavigate();
    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;

    return (
        <Card
            sx={{
                border: campaign.status === 'active'
                    ? '1px solid rgba(16,185,129,0.3)'
                    : '1px solid rgba(1,66,162,0.12)',
            }}
        >
            <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap' }}>
                    <Box sx={{ minWidth: 220, flex: 1 }}>
                        <Typography
                            fontWeight={700}
                            noWrap
                            onClick={() => navigate(`/campaigns/${campaign.id}`)}
                            sx={{ cursor: 'pointer', '&:hover': { color: '#0142a2' } }}
                        >
                            {campaign.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary" noWrap>
                            Agent: {campaign.assigned_agent_name || 'Unassigned'}
                        </Typography>
                    </Box>

                    <Chip
                        label={statusCfg.label}
                        size="small"
                        sx={{ bgcolor: statusCfg.bg, color: statusCfg.text, height: 22, fontSize: '0.72rem' }}
                    />
                    <Chip
                        label={MODE_LABELS[campaign.dialing_mode] || campaign.dialing_mode}
                        size="small"
                        variant="outlined"
                        sx={{ height: 22, fontSize: '0.72rem', borderColor: 'rgba(1,66,162,0.3)', color: '#1a5bc4' }}
                    />

                    <Box sx={{ width: 180 }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.4 }}>
                            <Typography variant="caption" color="text.secondary">
                                {campaign.progress_percentage}%
                            </Typography>
                            <Typography variant="caption" color="text.secondary">
                                {campaign.dialed_contacts}/{campaign.total_contacts}
                            </Typography>
                        </Box>
                        <LinearProgress
                            value={campaign.progress_percentage}
                            variant="determinate"
                            sx={{
                                height: 6,
                                borderRadius: 3,
                                bgcolor: 'rgba(1,66,162,0.1)',
                                '& .MuiLinearProgress-bar': {
                                    bgcolor: campaign.status === 'active' ? '#10b981' : '#0142a2',
                                    borderRadius: 3,
                                },
                            }}
                        />
                    </Box>

                    <Typography variant="caption" sx={{ minWidth: 90, color: '#10b981' }}>
                        Connected: {campaign.connected_calls}
                    </Typography>
                    <Typography variant="caption" sx={{ minWidth: 75, color: '#f59e0b' }}>
                        Rate: {campaign.connect_rate}%
                    </Typography>

                    {campaign.status === 'active' ? (
                        <Button size="small" variant="outlined" startIcon={<Pause />} onClick={() => onAction(campaign, 'pause')}
                            sx={{ borderColor: '#f59e0b', color: '#f59e0b' }}>
                            Pause
                        </Button>
                    ) : campaign.status === 'draft' || campaign.status === 'paused' ? (
                        <Button size="small" variant="contained" startIcon={<PlayArrow />}
                            onClick={() => onAction(campaign, campaign.status === 'draft' ? 'start' : 'resume')}
                            sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}>
                            {campaign.status === 'draft' ? 'Start' : 'Resume'}
                        </Button>
                    ) : null}

                    <Button
                        size="small"
                        variant="outlined"
                        startIcon={<Dialpad />}
                        onClick={() => navigate(`/dial?campaign_id=${campaign.id}`)}
                        sx={{ borderColor: 'rgba(1,66,162,0.5)', color: '#1a5bc4' }}
                    >
                        Dialer
                    </Button>
                    <Button
                        size="small"
                        variant="text"
                        onClick={() => navigate(`/campaigns/${campaign.id}`)}
                        sx={{ color: '#94a3b8' }}
                    >
                        Details
                    </Button>
                    <IconButton size="small" color="error" onClick={() => onDelete(campaign)} disabled={deleting}>
                        <DeleteOutline fontSize="small" />
                    </IconButton>
                </Box>
            </CardContent>
        </Card>
    );
}

export default function CampaignsPage() {
    const [campaigns, setCampaigns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');
    const [viewMode, setViewMode] = useState(() => localStorage.getItem('campaigns_view_mode') || 'grid');
    const [deletingCampaignId, setDeletingCampaignId] = useState(null);
    const navigate = useNavigate();

    const fetchCampaigns = async ({ silent = false } = {}) => {
        try {
            if (!silent) {
                setLoading(true);
            }
            const params = filter !== 'all' ? `?status=${filter}` : '';
            const { data } = await api.get(`/campaigns/${params}`);
            const rows = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : []);
            setCampaigns(rows);
        } catch (error) {
            const apiError = error?.response?.data?.error || error?.response?.data?.detail;
            const status = error?.response?.status;
            if (!silent) {
                toast.error(apiError || (status ? `Failed to load campaigns (${status})` : 'Failed to load campaigns'));
            }
        } finally {
            if (!silent) {
                setLoading(false);
            }
        }
    };

    useEffect(() => {
        fetchCampaigns();
    }, [filter]);

    useEffect(() => {
        localStorage.setItem('campaigns_view_mode', viewMode);
    }, [viewMode]);

    useEffect(() => {
        const hasActive = campaigns.some((campaign) => campaign.status === 'active');
        if (!hasActive) return undefined;

        const timer = setInterval(async () => {
            const activeIds = campaigns
                .filter((campaign) => campaign.status === 'active')
                .map((campaign) => campaign.id)
                .filter(Boolean);
            await Promise.allSettled(
                activeIds.map((campaignId) => api.post(`/campaigns/${campaignId}/tick/`))
            );
            fetchCampaigns({ silent: true });
        }, 5000);

        return () => clearInterval(timer);
    }, [campaigns]);

    const handleCampaignAction = async (campaign, action) => {
        try {
            await api.post(`/campaigns/${campaign.id}/${action}/`);
            const actionLabel = {
                start: 'started',
                resume: 'resumed',
                pause: 'paused',
                stop: 'stopped',
            }[action] || 'updated';
            toast.success(`Campaign ${actionLabel}`);
            fetchCampaigns({ silent: true });
        } catch (error) {
            toast.error(error?.response?.data?.error || `Failed to ${action}`);
        }
    };

    const handleDeleteCampaign = async (campaign) => {
        const ok = window.confirm(`Delete campaign "${campaign.name}"?`);
        if (!ok) return;

        setDeletingCampaignId(campaign.id);
        try {
            await api.post(`/campaigns/${campaign.id}/delete/`);
            toast.success('Campaign deleted');
            fetchCampaigns({ silent: true });
        } catch (error) {
            const code = error?.response?.data?.error;
            if (code === 'campaign_call_in_progress') {
                toast.error('Cannot delete while call is in progress. Pause or stop first.');
            } else {
                toast.error(code || 'Failed to delete campaign');
            }
        } finally {
            setDeletingCampaignId(null);
        }
    };

    const filters = ['all', 'active', 'paused', 'draft', 'completed'];

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Campaigns</Typography>
                    <Typography color="text.secondary" variant="body2">Queue-based outbound campaign control</Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    <Tooltip title="Card Grid">
                        <ToggleButtonGroup
                            size="small"
                            value={viewMode}
                            exclusive
                            onChange={(_event, next) => next && setViewMode(next)}
                            sx={{
                                '& .MuiToggleButton-root': {
                                    color: '#94a3b8',
                                    borderColor: 'rgba(1,66,162,0.25)',
                                    px: 1.2,
                                },
                                '& .Mui-selected': {
                                    bgcolor: 'rgba(1,66,162,0.18)',
                                    color: '#1a5bc4',
                                },
                            }}
                        >
                            <ToggleButton value="grid" aria-label="grid view">
                                <ViewModule fontSize="small" />
                            </ToggleButton>
                            <ToggleButton value="list" aria-label="single-line view">
                                <ViewAgenda fontSize="small" />
                            </ToggleButton>
                        </ToggleButtonGroup>
                    </Tooltip>
                    <Button
                        variant="contained"
                        startIcon={<Add />}
                        onClick={() => navigate('/campaigns/new')}
                        sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                    >
                        Create Campaign
                    </Button>
                </Box>
            </Box>

            <Box sx={{ display: 'flex', gap: 1, mb: 3, flexWrap: 'wrap' }}>
                {filters.map((value) => (
                    <Chip
                        key={value}
                        label={value.charAt(0).toUpperCase() + value.slice(1)}
                        onClick={() => setFilter(value)}
                        variant={filter === value ? 'filled' : 'outlined'}
                        sx={{
                            bgcolor: filter === value ? 'rgba(1,66,162,0.2)' : 'transparent',
                            color: filter === value ? '#1a5bc4' : '#94a3b8',
                            borderColor: filter === value ? '#0142a2' : 'rgba(1,66,162,0.3)',
                            cursor: 'pointer',
                        }}
                    />
                ))}
            </Box>

            {loading ? (
                <Grid container spacing={2}>
                    {Array.from({ length: 6 }).map((_, index) => (
                        <Grid item xs={12} sm={6} md={4} key={index}>
                            <Card><CardContent><Skeleton height={220} /></CardContent></Card>
                        </Grid>
                    ))}
                </Grid>
            ) : campaigns.length === 0 ? (
                <Card>
                    <CardContent sx={{ textAlign: 'center', py: 8 }}>
                        <Campaign sx={{ fontSize: 64, color: '#374151', mb: 2 }} />
                        <Typography variant="h6" color="text.secondary">No campaigns found</Typography>
                        <Button
                            variant="contained"
                            startIcon={<Add />}
                            sx={{ mt: 2 }}
                            onClick={() => navigate('/campaigns/new')}
                        >
                            Create Your First Campaign
                        </Button>
                    </CardContent>
                </Card>
            ) : viewMode === 'grid' ? (
                <Grid container spacing={2}>
                    {campaigns.map((campaign) => (
                        <Grid item xs={12} sm={6} md={4} key={campaign.id}>
                            <CampaignCard
                                campaign={campaign}
                                onAction={handleCampaignAction}
                                onDelete={handleDeleteCampaign}
                                deleting={deletingCampaignId === campaign.id}
                            />
                        </Grid>
                    ))}
                </Grid>
            ) : (
                <Box sx={{ display: 'grid', gap: 1.25 }}>
                    {campaigns.map((campaign) => (
                        <CampaignRow
                            key={campaign.id}
                            campaign={campaign}
                            onAction={handleCampaignAction}
                            onDelete={handleDeleteCampaign}
                            deleting={deletingCampaignId === campaign.id}
                        />
                    ))}
                </Box>
            )}
        </Box>
    );
}
