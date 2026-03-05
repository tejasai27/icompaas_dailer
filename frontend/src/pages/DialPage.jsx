import React, { useEffect, useMemo, useState } from 'react';
import {
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Divider,
    Grid,
    MenuItem,
    Tab,
    Tabs,
    TextField,
    Typography,
} from '@mui/material';
import { Backspace, Call, Contacts, Dialpad, Pause, PlayArrow, Refresh } from '@mui/icons-material';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { request } from '../lib/api';
import toast from 'react-hot-toast';

const KEYPAD = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '0', '#'];

function normalizePhone(value) {
    if (!value) return '';
    const raw = String(value).trim().replace(/\s+/g, '');
    if (raw.startsWith('+')) {
        return `+${raw.slice(1).replace(/\D/g, '')}`;
    }
    const digits = raw.replace(/\D/g, '');
    if (digits.length === 10) {
        return `+91${digits}`;
    }
    if (digits.startsWith('91')) {
        return `+${digits}`;
    }
    return digits ? `+${digits}` : '';
}

export default function DialPage() {
    const navigate = useNavigate();
    const [searchParams] = useSearchParams();
    const campaignId = searchParams.get('campaign_id');
    const [tab, setTab] = useState(0);
    const [dialNumber, setDialNumber] = useState('');
    const [quickName, setQuickName] = useState('');

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

    const selectedContact = useMemo(
        () => contacts.find((item) => String(item.id) === String(selectedContactId)) || null,
        [contacts, selectedContactId]
    );

    useEffect(() => {
        async function loadAgents() {
            setLoadingAgents(true);
            try {
                const data = await request('/api/v1/dialer/agents/');
                const rows = Array.isArray(data.agents) ? data.agents : [];
                setAgents(rows);
                if (!agentId && rows.length > 0) {
                    setAgentId(String(rows[0].id));
                }
            } catch (error) {
                toast.error(error.message || 'Failed to load SDRs');
            } finally {
                setLoadingAgents(false);
            }
        }
        loadAgents();
    }, []);

    useEffect(() => {
        let mounted = true;
        async function loadContacts() {
            setLoadingContacts(true);
            try {
                let path = '/api/v1/dialer/leads/?page=1&page_size=100';
                if (contactSearch.trim()) {
                    path += `&search=${encodeURIComponent(contactSearch.trim())}`;
                }
                if (campaignId) {
                    path += `&campaign=${encodeURIComponent(campaignId)}`;
                }
                const data = await request(path);
                if (!mounted) return;
                const rows = Array.isArray(data.results) ? data.results : [];
                setContacts(rows);
                if (rows.length === 0) {
                    setSelectedContactId('');
                } else if (!rows.some((row) => String(row.id) === String(selectedContactId))) {
                    setSelectedContactId(String(rows[0].id));
                }
            } catch (error) {
                if (mounted) {
                    toast.error(error.message || 'Failed to load contacts');
                }
            } finally {
                if (mounted) {
                    setLoadingContacts(false);
                }
            }
        }
        loadContacts();
        return () => {
            mounted = false;
        };
    }, [contactSearch, campaignId]);

    async function reloadCampaignContext(showErrorToast = true, options = {}) {
        const silent = Boolean(options?.silent);
        if (!campaignId) {
            setCampaign(null);
            setCampaignQueue([]);
            return;
        }
        if (!silent) {
            setLoadingCampaign(true);
        }
        try {
            const [campaignData, queueData] = await Promise.all([
                request(`/api/v1/dialer/campaigns/${campaignId}/`),
                request(`/api/v1/dialer/campaigns/${campaignId}/queue/`),
            ]);
            setCampaign(campaignData);
            setCampaignQueue(Array.isArray(queueData?.results) ? queueData.results : []);

            if (campaignData?.assigned_agent_id) {
                setAgentId(String(campaignData.assigned_agent_id));
            }
            if (campaignData?.agent_phone) {
                setAgentPhone(campaignData.agent_phone);
            }
            if (campaignData?.caller_id) {
                setCallerId(campaignData.caller_id);
            }
        } catch (error) {
            if (showErrorToast) {
                toast.error(error.message || 'Failed to load campaign context');
            }
        } finally {
            if (!silent) {
                setLoadingCampaign(false);
            }
        }
    }

    useEffect(() => {
        reloadCampaignContext(true);
    }, [campaignId]);

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
        const timer = setInterval(() => {
            setCooldownSeconds(computeRemaining());
        }, 1000);

        return () => clearInterval(timer);
    }, [campaign?.next_dispatch_at, campaign?.cooldown_remaining_seconds]);

    function formatSeconds(total) {
        const value = Math.max(0, Number(total || 0));
        const minutes = Math.floor(value / 60);
        const seconds = value % 60;
        return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

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

    const activeCall = campaign?.active_call || null;
    const activeCallDisplayStatus = normalizeCallStatus(activeCall?.display_status || activeCall?.status);
    const waitingForPickup = (
        activeCall?.stage === 'waiting_for_pickup'
        && !activeCall?.answered_at
        && !['answered', 'completed', 'sdr-cut', 'bridged', 'human-detected'].includes(activeCallDisplayStatus)
    );
    const pickupLeftSeconds = Number(activeCall?.pickup_seconds_left || 0);
    const lastCallStatus = normalizeCallStatus(campaign?.last_call_result?.display_status);

    useEffect(() => {
        if (!campaignId) return undefined;
        const shouldTick = campaign && (campaign.status === 'active' || Number(campaign.in_progress_contacts || 0) > 0);
        if (!shouldTick) return undefined;
        let cancelled = false;

        const tickCampaign = async () => {
            try {
                await request(`/api/v1/dialer/campaigns/${campaignId}/tick/`, { method: 'POST' });
                if (!cancelled) {
                    await reloadCampaignContext(false, { silent: true });
                }
            } catch (_error) {
                // Keep polling; transient provider/network failures are expected.
            }
        };

        tickCampaign();
        const interval = setInterval(tickCampaign, 5000);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [campaignId, campaign?.status, campaign?.in_progress_contacts]);

    function appendKey(key) {
        setDialNumber((value) => `${value}${key}`);
    }

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
            const payload = {
                lead_id: leadId,
                agent_id: agentIdNum,
                agent_phone: agentPhoneValue,
            };
            if (campaignId) {
                payload.campaign_id = Number(campaignId);
            }
            if (callerId.trim()) {
                payload.caller_id = callerId.trim();
            }
            const data = await request('/api/v1/dialer/calls/start/exotel/', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            setLastCall(data.call || null);
            toast.success('Call initiated');

            const callPublicId = String(data?.call?.public_id || data?.call?.id || '').trim();
            if (callPublicId) {
                const nextPath = campaignId
                    ? `/dial/call/${encodeURIComponent(callPublicId)}?campaign_id=${encodeURIComponent(campaignId)}`
                    : `/dial/call/${encodeURIComponent(callPublicId)}`;
                navigate(nextPath);
            }
        } catch (error) {
            toast.error(error.message || 'Failed to start call');
        } finally {
            setCalling(false);
        }
    }

    async function handleManualCall() {
        const phone = normalizePhone(dialNumber);
        if (!phone) {
            toast.error('Enter a valid phone number');
            return;
        }
        setCalling(true);
        try {
            await request('/api/v1/dialer/leads/manual/', {
                method: 'POST',
                body: JSON.stringify({
                    full_name: quickName.trim() || `Quick Dial ${phone}`,
                    phone_e164: phone,
                }),
            });

            const list = await request(
                `/api/v1/dialer/leads/?page=1&page_size=20&search=${encodeURIComponent(phone)}`
            );
            const rows = Array.isArray(list.results) ? list.results : [];
            const match = rows.find((item) => normalizePhone(item.phone || item.phone_e164) === phone) || rows[0];
            if (!match?.id) {
                throw new Error('Could not resolve lead for this number');
            }

            await startCall(Number(match.id));
        } catch (error) {
            toast.error(error.message || 'Failed to call number');
            setCalling(false);
        }
    }

    async function handleContactCall() {
        if (!selectedContact?.id) {
            toast.error('Select a contact');
            return;
        }
        await startCall(Number(selectedContact.id));
    }

    async function runCampaignAction(action) {
        if (!campaignId) return;
        setCampaignActionLoading(true);
        try {
            await request(`/api/v1/dialer/campaigns/${campaignId}/${action}/`, { method: 'POST' });
            const actionLabel = {
                start: 'started',
                resume: 'resumed',
                pause: 'paused',
                dispatch: 'dispatched',
            }[action] || 'updated';
            toast.success(`Campaign ${actionLabel}`);
            await reloadCampaignContext(false);
        } catch (error) {
            toast.error(error.message || `Failed to ${action} campaign`);
        } finally {
            setCampaignActionLoading(false);
        }
    }

    return (
        <Box>
            <Box sx={{ mb: 3 }}>
                <Typography variant="h4" fontWeight={700}>
                    Dial
                </Typography>
                <Typography color="text.secondary" variant="body2">
                    Use keypad for quick dial or call directly from contacts.
                </Typography>
                {campaignId ? (
                    <Chip
                        label={`Campaign #${campaignId}`}
                        sx={{ mt: 1, bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' }}
                    />
                ) : null}
            </Box>

            <Grid container spacing={2}>
                <Grid item xs={12} md={7}>
                    <Card>
                        <Tabs
                            value={tab}
                            onChange={(_, value) => setTab(value)}
                            sx={{
                                borderBottom: '1px solid rgba(1,66,162,0.12)',
                                '& .MuiTab-root': { textTransform: 'none' },
                            }}
                        >
                            <Tab icon={<Dialpad fontSize="small" />} iconPosition="start" label="Keypad" />
                            <Tab icon={<Contacts fontSize="small" />} iconPosition="start" label="Contacts" />
                        </Tabs>

                        <CardContent>
                            {tab === 0 ? (
                                <Box>
                                    <TextField
                                        fullWidth
                                        label="Number"
                                        value={dialNumber}
                                        onChange={(event) => setDialNumber(event.target.value)}
                                        placeholder="+91XXXXXXXXXX"
                                        sx={{ mb: 2 }}
                                    />
                                    <TextField
                                        fullWidth
                                        label="Lead Name (optional)"
                                        value={quickName}
                                        onChange={(event) => setQuickName(event.target.value)}
                                        placeholder="Quick Dial Lead"
                                        sx={{ mb: 2 }}
                                    />

                                    <Box
                                        sx={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                                            gap: 1,
                                            mb: 2,
                                        }}
                                    >
                                        {KEYPAD.map((key) => (
                                            <Button
                                                key={key}
                                                variant="outlined"
                                                onClick={() => appendKey(key)}
                                                sx={{ height: 52, fontSize: '1.15rem', borderColor: 'rgba(1,66,162,0.28)' }}
                                            >
                                                {key}
                                            </Button>
                                        ))}
                                    </Box>

                                    <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                                        <Button
                                            variant="outlined"
                                            startIcon={<Backspace />}
                                            onClick={() => setDialNumber((value) => value.slice(0, -1))}
                                        >
                                            Backspace
                                        </Button>
                                        <Button variant="text" onClick={() => setDialNumber('')}>
                                            Clear
                                        </Button>
                                    </Box>

                                    <Button
                                        fullWidth
                                        variant="contained"
                                        startIcon={calling ? <CircularProgress size={16} color="inherit" /> : <Call />}
                                        disabled={calling}
                                        onClick={handleManualCall}
                                        sx={{ py: 1.2, background: 'linear-gradient(135deg, #10b981, #059669)' }}
                                    >
                                        {calling ? 'Calling...' : 'Call Number'}
                                    </Button>
                                </Box>
                            ) : (
                                <Box>
                                    <TextField
                                        fullWidth
                                        label="Search Contacts"
                                        value={contactSearch}
                                        onChange={(event) => setContactSearch(event.target.value)}
                                        placeholder="Name, phone, company"
                                        sx={{ mb: 2 }}
                                    />
                                    <TextField
                                        fullWidth
                                        select
                                        label="Select Contact"
                                        value={selectedContactId}
                                        onChange={(event) => setSelectedContactId(event.target.value)}
                                        sx={{ mb: 2 }}
                                        helperText={loadingContacts ? 'Loading contacts...' : `${contacts.length} contacts`}
                                    >
                                        {contacts.map((contact) => (
                                            <MenuItem key={contact.id} value={String(contact.id)}>
                                                {contact.name} - {contact.phone}
                                            </MenuItem>
                                        ))}
                                    </TextField>

                                    <Box sx={{ mb: 2 }}>
                                        <Typography variant="body2" color="text.secondary">
                                            Selected
                                        </Typography>
                                        <Typography fontWeight={600}>
                                            {selectedContact?.name || '-'}
                                        </Typography>
                                        <Typography variant="body2" color="text.secondary">
                                            {selectedContact?.phone || '-'} {selectedContact?.company ? `· ${selectedContact.company}` : ''}
                                        </Typography>
                                    </Box>

                                    <Button
                                        fullWidth
                                        variant="contained"
                                        startIcon={calling ? <CircularProgress size={16} color="inherit" /> : <Call />}
                                        disabled={calling || loadingContacts || !selectedContactId}
                                        onClick={handleContactCall}
                                        sx={{ py: 1.2, background: 'linear-gradient(135deg, #10b981, #059669)' }}
                                    >
                                        {calling ? 'Calling...' : 'Call Contact'}
                                    </Button>
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                <Grid item xs={12} md={5}>
                    {campaignId ? (
                        <Card sx={{ mb: 2 }}>
                            <CardContent>
                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                                    <Typography variant="h6" fontWeight={600}>Campaign Queue</Typography>
                                    <Button
                                        size="small"
                                        startIcon={<Refresh fontSize="small" />}
                                        onClick={() => reloadCampaignContext(false)}
                                        disabled={campaignActionLoading}
                                    >
                                        Refresh
                                    </Button>
                                </Box>
                                {loadingCampaign ? (
                                    <CircularProgress size={20} />
                                ) : (
                                    <>
                                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                                            {campaign?.name || `Campaign ${campaignId}`} · Status: {campaign?.status || '-'}
                                        </Typography>
                                        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                                            Queue: {campaign?.pending_contacts ?? 0} pending, {campaign?.in_progress_contacts ?? 0} in progress
                                        </Typography>
                                        {campaign?.active_call_in_progress ? (
                                            waitingForPickup ? (
                                                <Typography variant="body2" sx={{ mb: 1.5, color: '#f59e0b' }}>
                                                    Customer not picking yet. Waiting {formatSeconds(pickupLeftSeconds)} before marking no-answer.
                                                </Typography>
                                            ) : (
                                                <Typography variant="body2" sx={{ mb: 1.5, color: '#10b981' }}>
                                                    SDR is in call{activeCall?.contact_name ? ` with ${activeCall.contact_name}` : ''}.
                                                </Typography>
                                            )
                                        ) : cooldownSeconds > 0 ? (
                                            lastCallStatus === 'no-answer' ? (
                                                <Typography variant="body2" sx={{ mb: 1.5, color: '#ef4444' }}>
                                                    Customer did not pick the call. Next call in {formatSeconds(cooldownSeconds)}.
                                                </Typography>
                                            ) : lastCallStatus === 'sdr-cut' ? (
                                                <Typography variant="body2" sx={{ mb: 1.5, color: '#ef4444' }}>
                                                    SDR cut the call. Next call in {formatSeconds(cooldownSeconds)}.
                                                </Typography>
                                            ) : (
                                                <Typography variant="body2" sx={{ mb: 1.5, color: '#f59e0b' }}>
                                                    Next call in {formatSeconds(cooldownSeconds)}
                                                </Typography>
                                            )
                                        ) : null}
                                        <Box sx={{ display: 'flex', gap: 1, mb: 1.5 }}>
                                            {campaign?.status === 'active' ? (
                                                <Button
                                                    size="small"
                                                    variant="outlined"
                                                    startIcon={<Pause fontSize="small" />}
                                                    onClick={() => runCampaignAction('pause')}
                                                    disabled={campaignActionLoading}
                                                >
                                                    Pause
                                                </Button>
                                            ) : campaign?.status === 'draft' || campaign?.status === 'paused' ? (
                                                <Button
                                                    size="small"
                                                    variant="contained"
                                                    startIcon={<PlayArrow fontSize="small" />}
                                                    onClick={() => runCampaignAction(campaign?.status === 'draft' ? 'start' : 'resume')}
                                                    disabled={campaignActionLoading}
                                                >
                                                    {campaign?.status === 'draft' ? 'Start' : 'Resume'}
                                                </Button>
                                            ) : null}
                                            <Button
                                                size="small"
                                                variant="outlined"
                                                onClick={() => runCampaignAction('dispatch')}
                                                disabled={campaignActionLoading || campaign?.status !== 'active'}
                                            >
                                                Run Next
                                            </Button>
                                        </Box>
                                        <Box sx={{ display: 'grid', gap: 0.75, maxHeight: 180, overflowY: 'auto' }}>
                                            {campaignQueue.slice(0, 8).map((item) => (
                                                <Box key={item.id} sx={{ p: 1, borderRadius: 1, bgcolor: 'rgba(1,66,162,0.08)' }}>
                                                    <Typography fontSize="0.8rem" fontWeight={600}>
                                                        {item.contact_name}
                                                    </Typography>
                                                    <Typography fontSize="0.75rem" color="text.secondary">
                                                        {item.contact_phone} · {item.status} · tries {item.attempt_count}
                                                    </Typography>
                                                </Box>
                                            ))}
                                            {campaignQueue.length === 0 ? (
                                                <Typography fontSize="0.8rem" color="text.secondary">
                                                    Queue is empty.
                                                </Typography>
                                            ) : null}
                                        </Box>
                                    </>
                                )}
                            </CardContent>
                        </Card>
                    ) : null}

                    <Card sx={{ mb: 2 }}>
                        <CardContent>
                            <Typography variant="h6" fontWeight={600} mb={2}>
                                Call Settings
                            </Typography>
                            <TextField
                                fullWidth
                                select
                                label="SDR"
                                value={agentId}
                                onChange={(event) => setAgentId(event.target.value)}
                                sx={{ mb: 2 }}
                                helperText={loadingAgents ? 'Loading SDRs...' : `${agents.length} SDRs`}
                            >
                                {agents.map((agent) => (
                                    <MenuItem key={agent.id} value={String(agent.id)}>
                                        {agent.id} - {agent.display_name} ({agent.status})
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                fullWidth
                                label="SDR Phone"
                                value={agentPhone}
                                onChange={(event) => setAgentPhone(event.target.value)}
                                placeholder="+91XXXXXXXXXX"
                                sx={{ mb: 2 }}
                            />
                            <TextField
                                fullWidth
                                label="Caller ID (optional)"
                                value={callerId}
                                onChange={(event) => setCallerId(event.target.value)}
                                placeholder="Exotel caller id"
                            />
                        </CardContent>
                    </Card>

                    <Card>
                        <CardContent>
                            <Typography variant="h6" fontWeight={600}>
                                Last Call
                            </Typography>
                            <Divider sx={{ my: 1.5, borderColor: 'rgba(1,66,162,0.12)' }} />
                            {lastCall ? (
                                <Box sx={{ display: 'grid', gap: 1 }}>
                                    <Chip
                                        size="small"
                                        label={formatCallStatus(lastCall.status)}
                                        sx={{ width: 'fit-content', bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' }}
                                    />
                                    <Typography variant="body2">
                                        <strong>ID:</strong> {lastCall.id}
                                    </Typography>
                                    <Typography variant="body2">
                                        <strong>Provider:</strong> {lastCall.provider}
                                    </Typography>
                                    <Typography variant="body2" sx={{ wordBreak: 'break-all' }}>
                                        <strong>Provider UUID:</strong> {lastCall.provider_call_uuid || '-'}
                                    </Typography>
                                </Box>
                            ) : (
                                <Typography variant="body2" color="text.secondary">
                                    No call started yet.
                                </Typography>
                            )}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
