import React, { useEffect, useMemo, useState } from 'react';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Grid,
    LinearProgress,
    Skeleton,
    Typography,
} from '@mui/material';
import { Add, Campaign, Dialpad } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';

const STATUS_COLORS = {
    active: { bg: '#10b98125', text: '#10b981', label: 'Active' },
    completed: { bg: '#6366f125', text: '#6366f1', label: 'Completed' },
    draft: { bg: '#64748b25', text: '#94a3b8', label: 'Draft' },
};

const MODE_LABELS = {
    power: '⚡ Power',
    dynamic: '🔀 Dynamic',
};

function toCampaignStatus(campaign) {
    if (campaign.dialed_contacts <= 0) return 'draft';
    if (campaign.dialed_contacts >= campaign.total_contacts) return 'completed';
    return 'active';
}

function isConnectedLeadStatus(status) {
    const value = String(status || '').toLowerCase();
    return value === 'connected' || value === 'interested' || value === 'follow_up';
}

function CampaignCard({ campaign }) {
    const navigate = useNavigate();
    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;

    return (
        <Card
            sx={{
                transition: 'all 0.2s',
                '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 32px rgba(99,102,241,0.2)' },
                border: campaign.status === 'active'
                    ? '1px solid rgba(16,185,129,0.3)'
                    : '1px solid rgba(99,102,241,0.1)',
            }}
        >
            <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1.5 }}>
                    <Box sx={{ flex: 1, mr: 1 }}>
                        <Typography fontWeight={700} noWrap>{campaign.name}</Typography>
                        <Box sx={{ display: 'flex', gap: 1, mt: 0.5 }}>
                            <Chip
                                label={statusCfg.label}
                                size="small"
                                sx={{ bgcolor: statusCfg.bg, color: statusCfg.text, height: 20, fontSize: '0.7rem' }}
                            />
                            <Chip
                                label={MODE_LABELS[campaign.dialing_mode] || campaign.dialing_mode || MODE_LABELS.power}
                                size="small"
                                variant="outlined"
                                sx={{
                                    height: 20,
                                    fontSize: '0.7rem',
                                    borderColor: 'rgba(99,102,241,0.3)',
                                    color: '#818cf8',
                                }}
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
                            bgcolor: 'rgba(99,102,241,0.1)',
                            '& .MuiLinearProgress-bar': {
                                bgcolor: campaign.status === 'active' ? '#10b981' : '#6366f1',
                                borderRadius: 3,
                            },
                        }}
                    />
                </Box>

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

                <Typography variant="caption" color="text.secondary" display="block" mb={1.5}>
                    Agent: {campaign.assigned_agent_name || 'Not assigned'}
                </Typography>

                <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                        size="small"
                        variant="contained"
                        startIcon={<Dialpad />}
                        onClick={() => navigate('/dial')}
                        sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)', flex: 1 }}
                    >
                        Open Dialer
                    </Button>
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

    const fetchAllLeads = async () => {
        const pageSize = 100;
        let page = 1;
        let totalCount = 0;
        const allResults = [];

        while (true) {
            const { data } = await api.get(`/leads/?page=${page}&page_size=${pageSize}`);
            const chunk = Array.isArray(data?.results) ? data.results : [];
            totalCount = Number(data?.count || chunk.length);
            allResults.push(...chunk);

            if (allResults.length >= totalCount || chunk.length === 0 || page >= 50) {
                break;
            }
            page += 1;
        }

        return allResults;
    };

    const fetchCampaigns = async () => {
        try {
            setLoading(true);
            const [leads, agentsRes] = await Promise.all([fetchAllLeads(), api.get('/agents/')]);
            const agents = Array.isArray(agentsRes.data?.agents) ? agentsRes.data.agents : [];
            const agentNameById = new Map(agents.map((agent) => [String(agent.id), agent.display_name]));

            const grouped = new Map();
            leads.forEach((lead) => {
                const campaignName = String(lead?.campaign_name || 'General').trim() || 'General';
                const settings = lead?.campaign_settings && typeof lead.campaign_settings === 'object'
                    ? lead.campaign_settings
                    : {};
                const group = grouped.get(campaignName) || {
                    id: campaignName,
                    name: campaignName,
                    dialing_mode: String(settings?.dialing_mode || 'power'),
                    assigned_agent_id: settings?.agent_id ? String(settings.agent_id) : '',
                    total_contacts: 0,
                    dialed_contacts: 0,
                    connected_calls: 0,
                };

                group.total_contacts += 1;
                if (lead?.retry_count > 0 || lead?.last_called_at || String(lead?.status || '').toLowerCase() !== 'pending') {
                    group.dialed_contacts += 1;
                }
                if (isConnectedLeadStatus(lead?.status)) {
                    group.connected_calls += 1;
                }

                if (!group.assigned_agent_id && settings?.agent_id) {
                    group.assigned_agent_id = String(settings.agent_id);
                }
                if ((!group.dialing_mode || group.dialing_mode === 'power') && settings?.dialing_mode) {
                    group.dialing_mode = String(settings.dialing_mode);
                }

                grouped.set(campaignName, group);
            });

            const normalized = Array.from(grouped.values()).map((campaign) => {
                const status = toCampaignStatus(campaign);
                const connectRate = campaign.total_contacts > 0
                    ? ((campaign.connected_calls / campaign.total_contacts) * 100).toFixed(1)
                    : '0.0';
                const progress = campaign.total_contacts > 0
                    ? Math.round((campaign.dialed_contacts / campaign.total_contacts) * 100)
                    : 0;
                return {
                    ...campaign,
                    status,
                    progress_percentage: progress,
                    connect_rate: connectRate,
                    assigned_agent_name: campaign.assigned_agent_id
                        ? (agentNameById.get(String(campaign.assigned_agent_id)) || `Agent ${campaign.assigned_agent_id}`)
                        : 'Not assigned',
                };
            });

            setCampaigns(normalized.sort((a, b) => b.total_contacts - a.total_contacts));
        } catch (error) {
            setCampaigns([]);
            toast.error(error?.response?.data?.error || 'Failed to load campaigns');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchCampaigns();
    }, []);

    const filters = ['all', 'active', 'draft', 'completed'];
    const filteredCampaigns = useMemo(
        () => (filter === 'all' ? campaigns : campaigns.filter((campaign) => campaign.status === filter)),
        [campaigns, filter]
    );

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

            <Box sx={{ display: 'flex', gap: 1, mb: 3, flexWrap: 'wrap' }}>
                {filters.map((value) => (
                    <Chip
                        key={value}
                        label={value.charAt(0).toUpperCase() + value.slice(1)}
                        onClick={() => setFilter(value)}
                        variant={filter === value ? 'filled' : 'outlined'}
                        sx={{
                            bgcolor: filter === value ? 'rgba(99,102,241,0.2)' : 'transparent',
                            color: filter === value ? '#818cf8' : '#94a3b8',
                            borderColor: filter === value ? '#6366f1' : 'rgba(99,102,241,0.3)',
                            cursor: 'pointer',
                        }}
                    />
                ))}
            </Box>

            {loading ? (
                <Grid container spacing={2}>
                    {Array.from({ length: 6 }).map((_, index) => (
                        <Grid item xs={12} sm={6} md={4} key={index}>
                            <Card><CardContent><Skeleton height={200} /></CardContent></Card>
                        </Grid>
                    ))}
                </Grid>
            ) : filteredCampaigns.length === 0 ? (
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
            ) : (
                <Grid container spacing={2}>
                    {filteredCampaigns.map((campaign) => (
                        <Grid item xs={12} sm={6} md={4} key={campaign.id}>
                            <CampaignCard campaign={campaign} />
                        </Grid>
                    ))}
                </Grid>
            )}
        </Box>
    );
}
