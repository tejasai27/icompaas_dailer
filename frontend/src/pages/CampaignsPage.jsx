import React, { useEffect, useRef, useState } from 'react';
import {
    Avatar,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Grid,
    IconButton,
    InputAdornment,
    LinearProgress,
    Menu,
    MenuItem,
    Skeleton,
    TextField,
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
    MoreVert,
    Pause,
    PlayArrow,
    Search,
    ViewAgenda,
    ViewModule,
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import toast from 'react-hot-toast';
import { CAMPAIGN_STATUS_COLORS as STATUS_COLORS } from '../lib/callStatus';
import useConfirm from '../lib/useConfirm';
import useVisibleInterval from '../lib/useVisibleInterval';
import useDebounce from '../lib/useDebounce';

const MODE_LABELS = { power: 'Power', dynamic: 'Dynamic' };

/* ── Campaign Card (grid view) ── */
function CampaignCard({ campaign, onAction, onDelete, deleting }) {
    const navigate = useNavigate();
    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;
    const [menuAnchor, setMenuAnchor] = useState(null);

    return (
        <Card sx={{
            transition: 'all 0.2s', cursor: 'pointer',
            '&:hover': { transform: 'translateY(-2px)', boxShadow: '0 8px 28px rgba(1,66,162,0.15)' },
            border: campaign.status === 'active' ? '2px solid rgba(16,185,129,0.4)' : '1px solid rgba(1,66,162,0.08)',
            boxShadow: campaign.status === 'active' ? '0 0 0 1px rgba(16,185,129,0.1)' : 'none',
        }}
            onClick={() => navigate(`/campaigns/${campaign.id}`)}
        >
            <CardContent sx={{ pb: '12px !important' }}>
                {/* Header */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1.5 }}>
                    <Box sx={{ flex: 1, mr: 1 }}>
                        <Typography fontWeight={700} noWrap sx={{ mb: 0.5 }}>{campaign.name}</Typography>
                        <Box sx={{ display: 'flex', gap: 0.5 }}>
                            <Chip label={statusCfg.label} size="small"
                                sx={{ bgcolor: statusCfg.bg, color: statusCfg.text, height: 20, fontSize: '0.65rem', fontWeight: 700 }} />
                            <Chip label={MODE_LABELS[campaign.dialing_mode] || campaign.dialing_mode} size="small" variant="outlined"
                                sx={{ height: 20, fontSize: '0.65rem', borderColor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' }} />
                        </Box>
                    </Box>
                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); setMenuAnchor(e.currentTarget); }}
                        sx={{ color: '#94a3b8', mt: -0.5 }}>
                        <MoreVert fontSize="small" />
                    </IconButton>
                    <Menu anchorEl={menuAnchor} open={Boolean(menuAnchor)} onClose={() => setMenuAnchor(null)} onClick={(e) => e.stopPropagation()}>
                        <MenuItem onClick={() => { setMenuAnchor(null); navigate(`/dial?campaign_id=${campaign.id}`); }}>
                            <Dialpad sx={{ fontSize: 16, mr: 1 }} /> Open Dialer
                        </MenuItem>
                        <MenuItem onClick={() => { setMenuAnchor(null); onDelete(campaign); }} disabled={deleting} sx={{ color: '#ef4444' }}>
                            <DeleteOutline sx={{ fontSize: 16, mr: 1 }} /> Delete
                        </MenuItem>
                    </Menu>
                </Box>

                {/* Progress */}
                <Box sx={{ mb: 1.5 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
                        <Typography variant="caption" color="text.secondary">
                            {campaign.dialed_contacts}/{campaign.total_contacts} dialed
                        </Typography>
                        <Typography variant="caption" fontWeight={600}>{campaign.progress_percentage}%</Typography>
                    </Box>
                    <LinearProgress value={campaign.progress_percentage} variant="determinate"
                        sx={{ height: 5, borderRadius: 3, bgcolor: 'rgba(1,66,162,0.08)',
                            '& .MuiLinearProgress-bar': { bgcolor: campaign.status === 'active' ? '#10b981' : '#0142a2', borderRadius: 3 } }} />
                </Box>

                {/* Metrics row */}
                <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
                    {[
                        { label: 'Total', value: campaign.total_contacts, color: '#0142a2' },
                        { label: 'Connected', value: campaign.connected_calls, color: '#10b981' },
                        { label: 'Rate', value: `${campaign.connect_rate}%`, color: '#f59e0b' },
                    ].map((m) => (
                        <Box key={m.label} sx={{ flex: 1, textAlign: 'center', p: 0.5, borderRadius: 1, bgcolor: `${m.color}08` }}>
                            <Typography fontSize="1rem" fontWeight={800} color={m.color}>{m.value}</Typography>
                            <Typography variant="caption" color="text.secondary" sx={{ fontSize: '0.65rem' }}>{m.label}</Typography>
                        </Box>
                    ))}
                </Box>

                {/* SDR + Action */}
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
                        <Avatar sx={{ width: 22, height: 22, fontSize: '0.6rem', bgcolor: '#0142a2' }}>
                            {(campaign.assigned_agent_name || '?')[0]}
                        </Avatar>
                        <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: 100 }}>
                            {campaign.assigned_agent_name || 'Unassigned'}
                        </Typography>
                    </Box>
                    {campaign.status === 'active' ? (
                        <Button size="small" variant="outlined" startIcon={<Pause sx={{ fontSize: 14 }} />}
                            onClick={(e) => { e.stopPropagation(); onAction(campaign, 'pause'); }}
                            sx={{ fontSize: '0.7rem', py: 0.25, borderColor: '#f59e0b', color: '#f59e0b' }}>
                            Pause
                        </Button>
                    ) : (campaign.status === 'draft' || campaign.status === 'paused') ? (
                        <Button size="small" variant="contained" startIcon={<PlayArrow sx={{ fontSize: 14 }} />}
                            onClick={(e) => { e.stopPropagation(); onAction(campaign, campaign.status === 'draft' ? 'start' : 'resume'); }}
                            sx={{ fontSize: '0.7rem', py: 0.25, bgcolor: '#10b981', '&:hover': { bgcolor: '#059669' } }}>
                            {campaign.status === 'draft' ? 'Start' : 'Resume'}
                        </Button>
                    ) : null}
                </Box>
            </CardContent>
        </Card>
    );
}

/* ── Campaign Row (list view) ── */
function CampaignRow({ campaign, onAction, onDelete, deleting }) {
    const navigate = useNavigate();
    const statusCfg = STATUS_COLORS[campaign.status] || STATUS_COLORS.draft;

    return (
        <Card sx={{
            border: campaign.status === 'active' ? '1px solid rgba(16,185,129,0.2)' : '1px solid rgba(1,66,162,0.06)',
            cursor: 'pointer', transition: 'background 0.15s',
            '&:hover': { bgcolor: 'rgba(1,66,162,0.02)' },
        }}
            onClick={() => navigate(`/campaigns/${campaign.id}`)}
        >
            <CardContent sx={{ py: 1.25, '&:last-child': { pb: 1.25 } }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
                    <Box sx={{ minWidth: 200, flex: 1 }}>
                        <Typography fontWeight={700} noWrap>{campaign.name}</Typography>
                        <Typography variant="caption" color="text.secondary" noWrap>
                            {campaign.assigned_agent_name || 'Unassigned'} · {MODE_LABELS[campaign.dialing_mode] || campaign.dialing_mode}
                        </Typography>
                    </Box>

                    <Chip label={statusCfg.label} size="small"
                        sx={{ bgcolor: statusCfg.bg, color: statusCfg.text, height: 22, fontSize: '0.7rem', fontWeight: 600 }} />

                    <Box sx={{ width: 160 }}>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
                            <Typography variant="caption" color="text.secondary">{campaign.progress_percentage}%</Typography>
                            <Typography variant="caption" color="text.secondary">{campaign.dialed_contacts}/{campaign.total_contacts}</Typography>
                        </Box>
                        <LinearProgress value={campaign.progress_percentage} variant="determinate"
                            sx={{ height: 5, borderRadius: 3, bgcolor: 'rgba(1,66,162,0.08)',
                                '& .MuiLinearProgress-bar': { bgcolor: campaign.status === 'active' ? '#10b981' : '#0142a2', borderRadius: 3 } }} />
                    </Box>

                    <Typography variant="caption" sx={{ minWidth: 80, color: '#10b981', fontWeight: 600 }}>
                        {campaign.connected_calls} connected
                    </Typography>
                    <Typography variant="caption" sx={{ minWidth: 60, color: '#f59e0b', fontWeight: 600 }}>
                        {campaign.connect_rate}%
                    </Typography>

                    {campaign.status === 'active' ? (
                        <Button size="small" variant="outlined" startIcon={<Pause sx={{ fontSize: 14 }} />}
                            onClick={(e) => { e.stopPropagation(); onAction(campaign, 'pause'); }}
                            sx={{ fontSize: '0.7rem', py: 0.25, borderColor: '#f59e0b', color: '#f59e0b' }}>
                            Pause
                        </Button>
                    ) : (campaign.status === 'draft' || campaign.status === 'paused') ? (
                        <Button size="small" variant="contained" startIcon={<PlayArrow sx={{ fontSize: 14 }} />}
                            onClick={(e) => { e.stopPropagation(); onAction(campaign, campaign.status === 'draft' ? 'start' : 'resume'); }}
                            sx={{ fontSize: '0.7rem', py: 0.25, bgcolor: '#10b981', '&:hover': { bgcolor: '#059669' } }}>
                            {campaign.status === 'draft' ? 'Start' : 'Resume'}
                        </Button>
                    ) : null}

                    <Tooltip title="Open Dialer">
                        <IconButton size="small" onClick={(e) => { e.stopPropagation(); navigate(`/dial?campaign_id=${campaign.id}`); }}
                            sx={{ color: '#1a5bc4' }}>
                            <Dialpad fontSize="small" />
                        </IconButton>
                    </Tooltip>
                    <Tooltip title="Delete">
                        <IconButton size="small" color="error" onClick={(e) => { e.stopPropagation(); onDelete(campaign); }} disabled={deleting}>
                            <DeleteOutline fontSize="small" />
                        </IconButton>
                    </Tooltip>
                </Box>
            </CardContent>
        </Card>
    );
}

/* ── Main page ── */
export default function CampaignsPage() {
    const [campaigns, setCampaigns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState('all');
    const [searchQuery, setSearchQuery] = useState('');
    const [viewMode, setViewMode] = useState(() => localStorage.getItem('campaigns_view_mode') || 'grid');
    const [deletingCampaignId, setDeletingCampaignId] = useState(null);
    const navigate = useNavigate();
    const [confirm, ConfirmEl] = useConfirm();
    const campaignsRef = useRef(campaigns);
    const fetchCampaignsRef = useRef(null);
    const debouncedSearch = useDebounce(searchQuery, 300);

    const fetchCampaigns = async ({ silent = false } = {}) => {
        try {
            if (!silent) setLoading(true);
            const params = filter !== 'all' ? `?status=${filter}` : '';
            const { data } = await api.get(`/campaigns/${params}`);
            const rows = Array.isArray(data?.results) ? data.results : (Array.isArray(data) ? data : []);
            setCampaigns(rows);
        } catch (error) {
            const apiError = error?.response?.data?.error || error?.response?.data?.detail;
            if (!silent) toast.error(apiError || 'Failed to load campaigns');
        } finally {
            if (!silent) setLoading(false);
        }
    };

    useEffect(() => { fetchCampaigns(); }, [filter]);
    useEffect(() => { localStorage.setItem('campaigns_view_mode', viewMode); }, [viewMode]);

    useEffect(() => { campaignsRef.current = campaigns; }, [campaigns]);
    useEffect(() => { fetchCampaignsRef.current = fetchCampaigns; });

    useVisibleInterval(async () => {
        const activeIds = campaignsRef.current.filter((c) => c.status === 'active').map((c) => c.id).filter(Boolean);
        if (activeIds.length === 0) return;
        await Promise.allSettled(activeIds.map((id) => api.post(`/campaigns/${id}/tick/`)));
        fetchCampaignsRef.current?.({ silent: true });
    }, 5000);

    const handleCampaignAction = async (campaign, action) => {
        try {
            await api.post(`/campaigns/${campaign.id}/${action}/`);
            toast.success(`Campaign ${({ start: 'started', resume: 'resumed', pause: 'paused', stop: 'stopped' })[action] || 'updated'}`);
            fetchCampaigns({ silent: true });
        } catch (error) {
            toast.error(error?.response?.data?.error || `Failed to ${action}`);
        }
    };

    const handleDeleteCampaign = async (campaign) => {
        const ok = await confirm({
            title: 'Delete Campaign',
            body: `"${campaign.name}" will be permanently deleted. This cannot be undone.`,
            confirmLabel: 'Delete',
        });
        if (!ok) return;
        setDeletingCampaignId(campaign.id);
        try {
            await api.post(`/campaigns/${campaign.id}/delete/`);
            toast.success('Campaign deleted');
            fetchCampaigns({ silent: true });
        } catch (error) {
            const code = error?.response?.data?.error;
            toast.error(code === 'campaign_call_in_progress' ? 'Cannot delete while call is in progress.' : (code || 'Failed to delete'));
        } finally {
            setDeletingCampaignId(null);
        }
    };

    // Client-side search filter
    const filteredCampaigns = debouncedSearch
        ? campaigns.filter((c) => c.name?.toLowerCase().includes(debouncedSearch.toLowerCase()) || c.assigned_agent_name?.toLowerCase().includes(debouncedSearch.toLowerCase()))
        : campaigns;

    const filters = ['all', 'active', 'paused', 'draft', 'completed'];
    const activeCampaigns = campaigns.filter((c) => c.status === 'active').length;

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Campaigns</Typography>
                    <Typography color="text.secondary" variant="body2">
                        {campaigns.length} campaigns · {activeCampaigns} active
                    </Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <ToggleButtonGroup size="small" value={viewMode} exclusive
                        onChange={(_, next) => next && setViewMode(next)}
                        sx={{ '& .MuiToggleButton-root': { color: '#94a3b8', borderColor: 'rgba(1,66,162,0.2)', px: 1 },
                            '& .Mui-selected': { bgcolor: 'rgba(1,66,162,0.15)', color: '#1a5bc4' } }}>
                        <ToggleButton value="grid" aria-label="grid view"><ViewModule fontSize="small" /></ToggleButton>
                        <ToggleButton value="list" aria-label="list view"><ViewAgenda fontSize="small" /></ToggleButton>
                    </ToggleButtonGroup>
                    <Button variant="contained" startIcon={<Add />} onClick={() => navigate('/campaigns/new')}
                        sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}>
                        Create Campaign
                    </Button>
                </Box>
            </Box>

            {/* Search + Filters */}
            <Box sx={{ display: 'flex', gap: 1.5, mb: 3, flexWrap: 'wrap', alignItems: 'center' }}>
                <TextField
                    size="small" placeholder="Search campaigns..."
                    value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                    InputProps={{ startAdornment: <InputAdornment position="start"><Search sx={{ color: '#94a3b8', fontSize: 18 }} /></InputAdornment> }}
                    sx={{ width: 260 }}
                />
                <Box sx={{ display: 'flex', gap: 0.5 }}>
                    {filters.map((value) => {
                        const isActive = filter === value;
                        const count = value === 'all' ? campaigns.length : campaigns.filter((c) => c.status === value).length;
                        return (
                            <Chip key={value}
                                label={`${value.charAt(0).toUpperCase() + value.slice(1)} (${count})`}
                                onClick={() => setFilter(value)}
                                sx={{
                                    fontWeight: isActive ? 700 : 500,
                                    bgcolor: isActive ? 'rgba(1,66,162,0.15)' : 'transparent',
                                    color: isActive ? '#1a5bc4' : '#94a3b8',
                                    border: `1px solid ${isActive ? '#0142a2' : 'rgba(1,66,162,0.15)'}`,
                                    cursor: 'pointer',
                                    '&:hover': { bgcolor: 'rgba(1,66,162,0.08)' },
                                }}
                            />
                        );
                    })}
                </Box>
            </Box>

            {/* Content */}
            {loading ? (
                <Grid container spacing={2}>
                    {Array.from({ length: 6 }).map((_, i) => (
                        <Grid item xs={12} sm={6} md={4} key={i}>
                            <Card><CardContent><Skeleton height={200} /></CardContent></Card>
                        </Grid>
                    ))}
                </Grid>
            ) : filteredCampaigns.length === 0 ? (
                <Card>
                    <CardContent sx={{ textAlign: 'center', py: 8 }}>
                        <Campaign sx={{ fontSize: 56, color: '#cbd5e1', mb: 2 }} />
                        <Typography variant="h6" color="text.secondary" fontWeight={600}>
                            {searchQuery ? 'No campaigns match your search' : 'No campaigns found'}
                        </Typography>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                            {searchQuery ? 'Try a different search term' : 'Create your first campaign to start dialing'}
                        </Typography>
                        {!searchQuery && (
                            <Typography variant="caption" color="text.secondary" sx={{ mb: 2, display: 'block' }}>
                                Set up a campaign to start automated dialing for your team
                            </Typography>
                        )}
                        {!searchQuery && (
                            <Button variant="contained" startIcon={<Add />} onClick={() => navigate('/campaigns/new')}
                                sx={{ bgcolor: '#0142a2' }}>
                                Create Campaign
                            </Button>
                        )}
                    </CardContent>
                </Card>
            ) : viewMode === 'grid' ? (
                <Grid container spacing={2}>
                    {filteredCampaigns.map((campaign) => (
                        <Grid item xs={12} sm={6} md={4} key={campaign.id}>
                            <CampaignCard campaign={campaign} onAction={handleCampaignAction}
                                onDelete={handleDeleteCampaign} deleting={deletingCampaignId === campaign.id} />
                        </Grid>
                    ))}
                </Grid>
            ) : (
                <Box sx={{ display: 'grid', gap: 1 }}>
                    {filteredCampaigns.map((campaign) => (
                        <CampaignRow key={campaign.id} campaign={campaign} onAction={handleCampaignAction}
                            onDelete={handleDeleteCampaign} deleting={deletingCampaignId === campaign.id} />
                    ))}
                </Box>
            )}
            {ConfirmEl}
        </Box>
    );
}
