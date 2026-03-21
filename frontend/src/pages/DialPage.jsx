import React, { useEffect, useMemo, useState } from 'react';
import {
    Avatar,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Collapse,
    Divider,
    Grid,
    LinearProgress,
    MenuItem,
    Tab,
    Tabs,
    TextField,
    Typography,
} from '@mui/material';
import {
    Backspace,
    Call,
    Contacts,
    Dialpad,
    ExpandLess,
    ExpandMore,
    History,
    Pause,
    Person,
    PlayArrow,
    Refresh,
    Settings,
} from '@mui/icons-material';
import { useNavigate, useSearchParams } from 'react-router-dom';
import api from '../services/api';
import toast from 'react-hot-toast';
import { normalizeCallStatus, formatCallStatus, formatSeconds, CALL_STATUS_COLORS } from '../lib/callStatus';
import { shortDateTime } from '../lib/formatDate';
import useVisibleInterval from '../lib/useVisibleInterval';
import useDebounce from '../lib/useDebounce';

const KEYPAD = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

function normalizePhone(value) {
    if (!value) return '';
    const raw = String(value).trim().replace(/\s+/g, '');
    if (raw.startsWith('+')) return `+${raw.slice(1).replace(/\D/g, '')}`;
    const digits = raw.replace(/\D/g, '');
    if (digits.length === 10) return `+91${digits}`;
    if (digits.startsWith('91')) return `+${digits}`;
    return digits ? `+${digits}` : '';
}

/* ── Contact Context Panel (left) ── */
function ContactContextPanel({ contact, campaignContact, campaignId, callHistory, loadingHistory }) {
    const display = campaignContact || contact;

    return (
        <Card sx={{ height: '100%' }}>
            <CardContent>
                {display ? (
                    <>
                        <Box sx={{ textAlign: 'center', mb: 2 }}>
                            <Avatar sx={{
                                width: 56, height: 56, mx: 'auto', mb: 1.5,
                                bgcolor: '#0142a2', fontSize: '1.25rem', fontWeight: 700,
                            }}>
                                {(display.name || display.contact_name || '?')[0].toUpperCase()}
                            </Avatar>
                            <Typography variant="h6" fontWeight={700} noWrap>
                                {display.name || display.contact_name || '-'}
                            </Typography>
                            <Typography variant="body2" color="text.secondary" fontFamily="monospace">
                                {display.phone || display.contact_phone || '-'}
                            </Typography>
                            {display.company && (
                                <Typography variant="caption" color="text.secondary">{display.company}</Typography>
                            )}
                            {display.email && (
                                <Typography variant="caption" color="text.secondary" display="block">{display.email}</Typography>
                            )}
                        </Box>

                        <Divider sx={{ my: 1.5, borderColor: 'rgba(1,66,162,0.1)' }} />

                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                            <History sx={{ fontSize: 16, color: '#64748b' }} />
                            <Typography variant="caption" fontWeight={600} color="text.secondary">
                                Call History
                            </Typography>
                        </Box>

                        {loadingHistory ? (
                            <Box sx={{ display: 'grid', gap: 0.5 }}>
                                {[1, 2, 3].map((i) => (
                                    <Box key={i} sx={{ height: 32, borderRadius: 1, bgcolor: 'rgba(1,66,162,0.05)' }} />
                                ))}
                            </Box>
                        ) : callHistory.length > 0 ? (
                            <Box sx={{ display: 'grid', gap: 0.5, maxHeight: 200, overflowY: 'auto' }}>
                                {callHistory.map((log) => {
                                    const statusKey = normalizeCallStatus(log.status);
                                    return (
                                        <Box key={log.id} sx={{
                                            p: 1, borderRadius: 1, bgcolor: 'rgba(1,66,162,0.04)',
                                            borderLeft: `3px solid ${CALL_STATUS_COLORS[statusKey] || '#94a3b8'}`,
                                        }}>
                                            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                                <Chip label={formatCallStatus(log.status)} size="small"
                                                    sx={{ height: 20, fontSize: '0.65rem', bgcolor: `${CALL_STATUS_COLORS[statusKey] || '#64748b'}20`, color: CALL_STATUS_COLORS[statusKey] || '#94a3b8' }} />
                                                <Typography variant="caption" color="text.secondary">{log.duration_formatted || '-'}</Typography>
                                            </Box>
                                            <Typography variant="caption" color="text.secondary">{shortDateTime(log.initiated_at)}</Typography>
                                        </Box>
                                    );
                                })}
                            </Box>
                        ) : (
                            <Typography variant="caption" color="text.secondary">No previous calls</Typography>
                        )}
                    </>
                ) : (
                    <Box sx={{ textAlign: 'center', py: 4 }}>
                        <Person sx={{ fontSize: 48, color: '#cbd5e1', mb: 1 }} />
                        <Typography variant="body2" color="text.secondary">
                            Select a contact to see details
                        </Typography>
                    </Box>
                )}
            </CardContent>
        </Card>
    );
}

/* ── Contact list view (replaces dropdown) ── */
function ContactListView({ contacts, selectedContactId, onSelect, loading }) {
    return (
        <Box sx={{ maxHeight: 320, overflowY: 'auto', display: 'grid', gap: 0.5 }}>
            {loading ? (
                Array.from({ length: 4 }).map((_, i) => (
                    <Box key={i} sx={{ height: 52, borderRadius: 1.5, bgcolor: 'rgba(1,66,162,0.04)' }} />
                ))
            ) : contacts.length === 0 ? (
                <Box sx={{ textAlign: 'center', py: 3 }}>
                    <Typography variant="body2" color="text.secondary">No contacts found</Typography>
                </Box>
            ) : contacts.map((c) => {
                const isSelected = String(c.id) === String(selectedContactId);
                return (
                    <Box
                        key={c.id}
                        onClick={() => onSelect(String(c.id))}
                        sx={{
                            p: 1.5, borderRadius: 1.5, cursor: 'pointer',
                            display: 'flex', alignItems: 'center', gap: 1.5,
                            borderLeft: isSelected ? '3px solid #0142a2' : '3px solid transparent',
                            bgcolor: isSelected ? 'rgba(1,66,162,0.08)' : 'rgba(1,66,162,0.02)',
                            transition: 'all 0.15s',
                            '&:hover': { bgcolor: 'rgba(1,66,162,0.06)' },
                        }}
                    >
                        <Avatar sx={{ width: 32, height: 32, bgcolor: isSelected ? '#0142a2' : '#94a3b8', fontSize: '0.75rem' }}>
                            {(c.name || '?')[0].toUpperCase()}
                        </Avatar>
                        <Box sx={{ flex: 1, minWidth: 0 }}>
                            <Typography fontWeight={600} fontSize="0.85rem" noWrap>{c.name}</Typography>
                            <Typography fontSize="0.75rem" color="text.secondary" fontFamily="monospace" noWrap>
                                {c.phone} {c.company ? `· ${c.company}` : ''}
                            </Typography>
                        </Box>
                        {isSelected && <Chip label="Selected" size="small" sx={{ bgcolor: '#0142a220', color: '#0142a2', height: 20, fontSize: '0.65rem' }} />}
                    </Box>
                );
            })}
        </Box>
    );
}

/* ── Campaign queue preview (right panel) ── */
function CampaignQueuePreview({
    campaign, campaignId, campaignQueue, loadingCampaign,
    campaignActionLoading, runCampaignAction,
    cooldownSeconds, lastCallStatus, activeCall, waitingForPickup, pickupLeftSeconds,
}) {
    if (!campaignId) return null;

    const progress = campaign ? Math.round((campaign.dialed_contacts / Math.max(1, campaign.total_contacts)) * 100) : 0;

    return (
        <Card sx={{ mb: 2, border: campaign?.status === 'active' ? '1px solid rgba(16,185,129,0.3)' : undefined }}>
            <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1.5 }}>
                    <Typography fontWeight={700} fontSize="0.9rem">Campaign Queue</Typography>
                    <Chip
                        label={campaign?.status || 'loading'}
                        size="small"
                        sx={{
                            bgcolor: campaign?.status === 'active' ? '#10b98120' : '#64748b20',
                            color: campaign?.status === 'active' ? '#10b981' : '#94a3b8',
                            fontWeight: 600, fontSize: '0.7rem',
                        }}
                    />
                </Box>

                {loadingCampaign ? (
                    <CircularProgress size={20} />
                ) : (
                    <>
                        <Typography variant="body2" fontWeight={600} noWrap sx={{ mb: 0.5 }}>
                            {campaign?.name || `Campaign ${campaignId}`}
                        </Typography>

                        <Box sx={{ mb: 1.5 }}>
                            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.3 }}>
                                <Typography variant="caption" color="text.secondary">
                                    {campaign?.dialed_contacts || 0}/{campaign?.total_contacts || 0} dialed
                                </Typography>
                                <Typography variant="caption" color="text.secondary">{progress}%</Typography>
                            </Box>
                            <LinearProgress value={progress} variant="determinate"
                                sx={{ height: 5, borderRadius: 3, bgcolor: 'rgba(1,66,162,0.1)', '& .MuiLinearProgress-bar': { bgcolor: campaign?.status === 'active' ? '#10b981' : '#0142a2', borderRadius: 3 } }} />
                        </Box>

                        {/* Status message */}
                        {campaign?.active_call_in_progress ? (
                            <Typography variant="caption" sx={{ color: waitingForPickup ? '#f59e0b' : '#10b981', display: 'block', mb: 1 }}>
                                {waitingForPickup
                                    ? `Waiting ${formatSeconds(pickupLeftSeconds)}...`
                                    : `In call${activeCall?.contact_name ? ` with ${activeCall.contact_name}` : ''}`}
                            </Typography>
                        ) : cooldownSeconds > 0 ? (
                            <Typography variant="caption" sx={{ color: '#f59e0b', display: 'block', mb: 1 }}>
                                Next call in {formatSeconds(cooldownSeconds)}
                            </Typography>
                        ) : null}

                        {/* Controls */}
                        <Box sx={{ display: 'flex', gap: 0.5, mb: 1.5 }}>
                            {campaign?.status === 'active' ? (
                                <Button size="small" variant="outlined" startIcon={<Pause sx={{ fontSize: 14 }} />}
                                    onClick={() => runCampaignAction('pause')} disabled={campaignActionLoading}
                                    sx={{ fontSize: '0.75rem', py: 0.5 }}>
                                    Pause
                                </Button>
                            ) : (campaign?.status === 'draft' || campaign?.status === 'paused') ? (
                                <Button size="small" variant="contained" startIcon={<PlayArrow sx={{ fontSize: 14 }} />}
                                    onClick={() => runCampaignAction(campaign?.status === 'draft' ? 'start' : 'resume')}
                                    disabled={campaignActionLoading}
                                    sx={{ fontSize: '0.75rem', py: 0.5, bgcolor: '#10b981', '&:hover': { bgcolor: '#059669' } }}>
                                    {campaign?.status === 'draft' ? 'Start' : 'Resume'}
                                </Button>
                            ) : null}
                            <Button size="small" variant="outlined"
                                onClick={() => runCampaignAction('dispatch')}
                                disabled={campaignActionLoading || campaign?.status !== 'active'}
                                sx={{ fontSize: '0.75rem', py: 0.5 }}>
                                Next
                            </Button>
                        </Box>

                        {/* Queue preview */}
                        <Typography variant="caption" fontWeight={600} color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                            Up Next
                        </Typography>
                        <Box sx={{ display: 'grid', gap: 0.5 }}>
                            {campaignQueue.slice(0, 5).map((item, idx) => (
                                <Box key={item.id} sx={{
                                    p: 0.75, borderRadius: 1,
                                    bgcolor: idx === 0 ? 'rgba(1,66,162,0.1)' : 'rgba(1,66,162,0.04)',
                                    display: 'flex', alignItems: 'center', gap: 1,
                                }}>
                                    <Avatar sx={{ width: 24, height: 24, bgcolor: idx === 0 ? '#0142a2' : '#94a3b8', fontSize: '0.65rem' }}>
                                        {(item.contact_name || '?')[0]}
                                    </Avatar>
                                    <Box sx={{ flex: 1, minWidth: 0 }}>
                                        <Typography fontSize="0.75rem" fontWeight={600} noWrap>{item.contact_name}</Typography>
                                        <Typography fontSize="0.65rem" color="text.secondary" noWrap>{item.contact_phone}</Typography>
                                    </Box>
                                    <Chip label={`#${item.attempt_count || 0}`} size="small"
                                        sx={{ height: 18, fontSize: '0.6rem', bgcolor: 'rgba(1,66,162,0.08)' }} />
                                </Box>
                            ))}
                            {campaignQueue.length === 0 && (
                                <Typography variant="caption" color="text.secondary">Queue empty</Typography>
                            )}
                        </Box>
                    </>
                )}
            </CardContent>
        </Card>
    );
}

/* ── Main page ── */
export default function DialPage() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const campaignId = searchParams.get('campaign_id');
    const [tab, setTab] = useState(0);
    const [dialNumber, setDialNumber] = useState('');
    const [quickName, setQuickName] = useState('');
    const [settingsExpanded, setSettingsExpanded] = useState(false);

    const [agents, setAgents] = useState([]);
    const [agentId, setAgentId] = useState('');
    const [agentPhone, setAgentPhone] = useState('');
    const [callerId, setCallerId] = useState('');

    const [contactSearch, setContactSearch] = useState('');
    const [contacts, setContacts] = useState([]);
    const [selectedContactId, setSelectedContactId] = useState('');

    const [loadingAgents, setLoadingAgents] = useState(true);
    const [loadingContacts, setLoadingContacts] = useState(false);
    const [calling, setCalling] = useState(false);
    const [lastCall, setLastCall] = useState(null);
    const [campaign, setCampaign] = useState(null);
    const [campaignQueue, setCampaignQueue] = useState([]);
    const [loadingCampaign, setLoadingCampaign] = useState(false);
    const [campaignActionLoading, setCampaignActionLoading] = useState(false);
    const [cooldownSeconds, setCooldownSeconds] = useState(0);

    // Contact call history
    const [contactCallHistory, setContactCallHistory] = useState([]);
    const [loadingHistory, setLoadingHistory] = useState(false);

    const selectedContact = useMemo(
        () => contacts.find((item) => String(item.id) === String(selectedContactId)) || null,
        [contacts, selectedContactId]
    );

    const displayContact = campaignQueue.length > 0 ? campaignQueue[0] : selectedContact;
    const displayContactPhone = displayContact?.phone || displayContact?.contact_phone || '';
    const debouncedPhone = useDebounce(displayContactPhone, 500);

    // Fetch call history for displayed contact
    useEffect(() => {
        if (!debouncedPhone) { setContactCallHistory([]); return; }
        const controller = new AbortController();
        setLoadingHistory(true);
        api.get(`/call-logs/?search=${encodeURIComponent(debouncedPhone)}&page=1&page_size=5&ordering=-initiated_at`, { signal: controller.signal })
            .then((res) => {
                setContactCallHistory(Array.isArray(res.data?.results) ? res.data.results : []);
            })
            .catch((err) => {
                if (!controller.signal.aborted) setContactCallHistory([]);
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoadingHistory(false);
            });
        return () => controller.abort();
    }, [debouncedPhone]);

    useEffect(() => {
        async function loadAgents() {
            setLoadingAgents(true);
            try {
                const { data } = await api.get('/agents/');
                const rows = Array.isArray(data.agents) ? data.agents : [];
                setAgents(rows);
                if (!agentId && rows.length > 0) setAgentId(String(rows[0].id));
            } catch (error) {
                toast.error(error.response?.data?.error || error.message || 'Failed to load SDRs');
            } finally {
                setLoadingAgents(false);
            }
        }
        loadAgents();
    }, []);

    useEffect(() => {
        const controller = new AbortController();
        async function loadContacts() {
            setLoadingContacts(true);
            try {
                let path = '/leads/?page=1&page_size=100';
                if (contactSearch.trim()) path += `&search=${encodeURIComponent(contactSearch.trim())}`;
                if (campaignId) path += `&campaign=${encodeURIComponent(campaignId)}`;
                const { data } = await api.get(path, { signal: controller.signal });
                const rows = Array.isArray(data.results) ? data.results : [];
                setContacts(rows);
                if (rows.length === 0) {
                    setSelectedContactId('');
                } else if (!rows.some((row) => String(row.id) === String(selectedContactId))) {
                    setSelectedContactId(String(rows[0].id));
                }
            } catch (error) {
                if (controller.signal.aborted) return;
                toast.error(error.response?.data?.error || error.message || 'Failed to load contacts');
            } finally {
                if (!controller.signal.aborted) setLoadingContacts(false);
            }
        }
        loadContacts();
        return () => controller.abort();
    }, [contactSearch, campaignId]);

    async function reloadCampaignContext(showErrorToast = true, options = {}) {
        const silent = Boolean(options?.silent);
        if (!campaignId) { setCampaign(null); setCampaignQueue([]); return; }
        if (!silent) setLoadingCampaign(true);
        try {
            const [campaignRes, queueRes] = await Promise.all([
                api.get(`/campaigns/${campaignId}/`),
                api.get(`/campaigns/${campaignId}/queue/`),
            ]);
            setCampaign(campaignRes.data);
            setCampaignQueue(Array.isArray(queueRes.data?.results) ? queueRes.data.results : []);
            if (campaignRes.data?.assigned_agent_id) setAgentId(String(campaignRes.data.assigned_agent_id));
            if (campaignRes.data?.agent_phone) setAgentPhone(campaignRes.data.agent_phone);
            if (campaignRes.data?.caller_id) setCallerId(campaignRes.data.caller_id);
        } catch (error) {
            if (showErrorToast) toast.error(error.response?.data?.error || error.message || 'Failed to load campaign context');
        } finally {
            if (!silent) setLoadingCampaign(false);
        }
    }

    useEffect(() => { reloadCampaignContext(true); }, [campaignId]);

    useEffect(() => {
        if (!campaign?.next_dispatch_at) {
            setCooldownSeconds(Number(campaign?.cooldown_remaining_seconds || 0));
            return undefined;
        }
        const computeRemaining = () => {
            const ms = new Date(campaign.next_dispatch_at).getTime() - Date.now();
            return ms > 0 ? Math.ceil(ms / 1000) : 0;
        };
        setCooldownSeconds(computeRemaining());
        const timer = setInterval(() => setCooldownSeconds(computeRemaining()), 1000);
        return () => clearInterval(timer);
    }, [campaign?.next_dispatch_at, campaign?.cooldown_remaining_seconds]);

    const activeCall = campaign?.active_call || null;
    const activeCallDisplayStatus = normalizeCallStatus(activeCall?.display_status || activeCall?.status);
    const waitingForPickup = activeCall?.stage === 'waiting_for_pickup' && !activeCall?.answered_at
        && !['answered', 'completed', 'sdr-cut', 'bridged', 'human-detected'].includes(activeCallDisplayStatus);
    const pickupLeftSeconds = Number(activeCall?.pickup_seconds_left || 0);
    const lastCallStatus = normalizeCallStatus(campaign?.last_call_result?.display_status);

    const shouldTickDial = campaignId && campaign && (campaign.status === 'active' || Number(campaign.in_progress_contacts || 0) > 0);
    useVisibleInterval(async () => {
        try {
            await api.post(`/campaigns/${campaignId}/tick/`);
            await reloadCampaignContext(false, { silent: true });
        } catch (_error) {}
    }, shouldTickDial ? 5000 : null);

    function appendKey(key) { setDialNumber((v) => `${v}${key}`); }

    async function startCall(leadId) {
        const agentIdNum = Number(agentId);
        const agentPhoneValue = agentPhone.trim();
        if (!leadId || !agentIdNum || !agentPhoneValue) {
            toast.error('Lead, SDR and SDR phone are required');
            setCalling(false);
            return;
        }
        setCalling(true);
        try {
            const payload = { lead_id: leadId, agent_id: agentIdNum, agent_phone: agentPhoneValue };
            if (campaignId) payload.campaign_id = Number(campaignId);
            if (callerId.trim()) payload.caller_id = callerId.trim();
            const { data } = await api.post('/calls/start/exotel/', payload);
            setLastCall(data.call || null);
            toast.success('Call initiated');
            const callPublicId = String(data?.call?.public_id || data?.call?.id || '').trim();
            if (callPublicId) {
                navigate(campaignId
                    ? `/dial/call/${encodeURIComponent(callPublicId)}?campaign_id=${encodeURIComponent(campaignId)}`
                    : `/dial/call/${encodeURIComponent(callPublicId)}`);
            }
        } catch (error) {
            toast.error(error.response?.data?.error || error.message || 'Failed to start call');
        } finally {
            setCalling(false);
        }
    }

    async function handleManualCall() {
        const phone = normalizePhone(dialNumber);
        if (!phone) { toast.error('Enter a valid phone number'); return; }
        setCalling(true);
        try {
            await api.post('/leads/manual/', { full_name: quickName.trim() || `Quick Dial ${phone}`, phone_e164: phone });
            const { data: list } = await api.get(`/leads/?page=1&page_size=20&search=${encodeURIComponent(phone)}`);
            const rows = Array.isArray(list.results) ? list.results : [];
            const match = rows.find((item) => normalizePhone(item.phone || item.phone_e164) === phone) || rows[0];
            if (!match?.id) throw new Error('Could not resolve lead for this number');
            await startCall(Number(match.id));
        } catch (error) {
            toast.error(error.response?.data?.error || error.message || 'Failed to call number');
            setCalling(false);
        }
    }

    async function handleContactCall() {
        if (!selectedContact?.id) { toast.error('Select a contact'); return; }
        await startCall(Number(selectedContact.id));
    }

    async function runCampaignAction(action) {
        if (!campaignId) return;
        setCampaignActionLoading(true);
        try {
            await api.post(`/campaigns/${campaignId}/${action}/`);
            toast.success(`Campaign ${({ start: 'started', resume: 'resumed', pause: 'paused', dispatch: 'dispatched' })[action] || 'updated'}`);
            await reloadCampaignContext(false);
        } catch (error) {
            toast.error(error.response?.data?.error || error.message || `Failed to ${action} campaign`);
        } finally {
            setCampaignActionLoading(false);
        }
    }

    function handleCall() {
        if (tab === 0) handleManualCall();
        else handleContactCall();
    }

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Dialer</Typography>
                    <Typography color="text.secondary" variant="body2">
                        {campaignId ? `Campaign mode · #${campaignId}` : 'Quick dial or call from contacts'}
                    </Typography>
                </Box>
                {campaignId && campaign && (
                    <Chip
                        label={`${campaign.name} · ${campaign.status}`}
                        sx={{ bgcolor: campaign.status === 'active' ? '#10b98120' : 'rgba(1,66,162,0.1)', color: campaign.status === 'active' ? '#10b981' : '#1a5bc4', fontWeight: 600 }}
                    />
                )}
            </Box>

            <Grid container spacing={2}>
                {/* LEFT — Contact Context */}
                <Grid item xs={12} md={3} order={{ xs: 2, md: 1 }}>
                    <ContactContextPanel
                        contact={selectedContact}
                        campaignContact={campaignQueue.length > 0 ? campaignQueue[0] : null}
                        campaignId={campaignId}
                        callHistory={contactCallHistory}
                        loadingHistory={loadingHistory}
                    />
                </Grid>

                {/* CENTER — Keypad / Contacts + Call Button */}
                <Grid item xs={12} md={campaignId ? 5 : 6} order={{ xs: 1, md: 2 }}>
                    <Card>
                        <Tabs
                            value={tab}
                            onChange={(_, v) => setTab(v)}
                            sx={{ borderBottom: '1px solid rgba(1,66,162,0.12)', '& .MuiTab-root': { textTransform: 'none', fontWeight: 600 } }}
                        >
                            <Tab icon={<Dialpad fontSize="small" />} iconPosition="start" label="Keypad" />
                            <Tab icon={<Contacts fontSize="small" />} iconPosition="start" label={`Contacts (${contacts.length})`} />
                        </Tabs>

                        <CardContent>
                            {tab === 0 ? (
                                <Box>
                                    <TextField fullWidth label="Number" value={dialNumber}
                                        onChange={(e) => setDialNumber(e.target.value)} placeholder="+91XXXXXXXXXX"
                                        sx={{ mb: 1.5, '& .MuiInputBase-input': { fontSize: '1.2rem', fontFamily: 'monospace', letterSpacing: '0.05em' } }} />
                                    <TextField fullWidth size="small" label="Lead Name (optional)" value={quickName}
                                        onChange={(e) => setQuickName(e.target.value)} placeholder="Quick Dial Lead" sx={{ mb: 2 }} />

                                    <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 0.75, mb: 2 }}>
                                        {KEYPAD.map((key) => (
                                            <Button key={key} variant="outlined" onClick={() => appendKey(key)}
                                                sx={{ height: 48, fontSize: '1.1rem', fontWeight: 600, borderColor: 'rgba(1,66,162,0.2)', borderRadius: 2 }}>
                                                {key}
                                            </Button>
                                        ))}
                                    </Box>
                                    <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                                        <Button size="small" startIcon={<Backspace />} onClick={() => setDialNumber((v) => v.slice(0, -1))}>Back</Button>
                                        <Button size="small" variant="text" onClick={() => setDialNumber('')}>Clear</Button>
                                    </Box>
                                </Box>
                            ) : (
                                <Box>
                                    <TextField fullWidth size="small" value={contactSearch}
                                        onChange={(e) => setContactSearch(e.target.value)}
                                        placeholder="Search by name, phone, company..."
                                        sx={{ mb: 2 }} />
                                    <ContactListView
                                        contacts={contacts}
                                        selectedContactId={selectedContactId}
                                        onSelect={setSelectedContactId}
                                        loading={loadingContacts}
                                    />
                                </Box>
                            )}

                            {/* Call button — always visible */}
                            <Button
                                fullWidth variant="contained" size="large"
                                startIcon={calling ? <CircularProgress size={18} color="inherit" /> : <Call />}
                                disabled={calling || (tab === 1 && !selectedContactId)}
                                onClick={handleCall}
                                sx={{
                                    mt: 2, py: 1.5, borderRadius: 3, fontSize: '1rem', fontWeight: 700,
                                    background: 'linear-gradient(135deg, #10b981, #059669)',
                                    boxShadow: '0 4px 16px rgba(16,185,129,0.3)',
                                    '&:hover': { boxShadow: '0 6px 20px rgba(16,185,129,0.4)' },
                                }}
                            >
                                {calling ? 'Calling...' : tab === 0 ? 'Call Number' : 'Call Contact'}
                            </Button>
                        </CardContent>
                    </Card>
                </Grid>

                {/* RIGHT — Campaign Queue + Settings */}
                <Grid item xs={12} md={campaignId ? 4 : 3} order={{ xs: 3, md: 3 }}>
                    <CampaignQueuePreview
                        campaign={campaign} campaignId={campaignId} campaignQueue={campaignQueue}
                        loadingCampaign={loadingCampaign} campaignActionLoading={campaignActionLoading}
                        runCampaignAction={runCampaignAction}
                        cooldownSeconds={cooldownSeconds} lastCallStatus={lastCallStatus}
                        activeCall={activeCall} waitingForPickup={waitingForPickup}
                        pickupLeftSeconds={pickupLeftSeconds}
                    />

                    {/* Collapsible Call Settings */}
                    <Card>
                        <CardContent sx={{ pb: settingsExpanded ? 2 : '16px !important' }}>
                            <Box
                                onClick={() => setSettingsExpanded((v) => !v)}
                                sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                            >
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                    <Settings sx={{ fontSize: 18, color: '#64748b' }} />
                                    <Typography fontWeight={700} fontSize="0.9rem">Call Settings</Typography>
                                </Box>
                                {settingsExpanded ? <ExpandLess sx={{ color: '#64748b' }} /> : <ExpandMore sx={{ color: '#64748b' }} />}
                            </Box>
                            <Collapse in={settingsExpanded}>
                                <Box sx={{ mt: 2, display: 'grid', gap: 1.5 }}>
                                    <TextField fullWidth size="small" select label="SDR" value={agentId}
                                        onChange={(e) => setAgentId(e.target.value)}
                                        helperText={loadingAgents ? 'Loading...' : `${agents.length} SDRs`}>
                                        {agents.map((a) => (
                                            <MenuItem key={a.id} value={String(a.id)}>{a.display_name} ({a.status})</MenuItem>
                                        ))}
                                    </TextField>
                                    <TextField fullWidth size="small" label="SDR Phone" value={agentPhone}
                                        onChange={(e) => setAgentPhone(e.target.value)} placeholder="+91XXXXXXXXXX" />
                                    <TextField fullWidth size="small" label="Caller ID (optional)" value={callerId}
                                        onChange={(e) => setCallerId(e.target.value)} placeholder="Exotel caller id" />
                                </Box>
                            </Collapse>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
