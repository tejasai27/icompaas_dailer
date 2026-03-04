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
import { Backspace, Call, Contacts, Dialpad } from '@mui/icons-material';
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
                toast.error(error.message || 'Failed to load agents');
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
    }, [contactSearch]);

    function appendKey(key) {
        setDialNumber((value) => `${value}${key}`);
    }

    async function startCall(leadId) {
        const agentIdNum = Number(agentId);
        const agentPhoneValue = agentPhone.trim();
        if (!leadId || !agentIdNum || !agentPhoneValue) {
            toast.error('Lead, agent and agent phone are required');
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
            if (callerId.trim()) {
                payload.caller_id = callerId.trim();
            }
            const data = await request('/api/v1/dialer/calls/start/exotel/', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            setLastCall(data.call || null);
            toast.success('Call initiated');
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

    return (
        <Box>
            <Box sx={{ mb: 3 }}>
                <Typography variant="h4" fontWeight={700}>
                    Dial
                </Typography>
                <Typography color="text.secondary" variant="body2">
                    Use keypad for quick dial or call directly from contacts.
                </Typography>
            </Box>

            <Grid container spacing={2}>
                <Grid item xs={12} md={7}>
                    <Card>
                        <Tabs
                            value={tab}
                            onChange={(_, value) => setTab(value)}
                            sx={{
                                borderBottom: '1px solid rgba(99,102,241,0.12)',
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
                                                sx={{ height: 52, fontSize: '1.15rem', borderColor: 'rgba(99,102,241,0.28)' }}
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
                    <Card sx={{ mb: 2 }}>
                        <CardContent>
                            <Typography variant="h6" fontWeight={600} mb={2}>
                                Call Settings
                            </Typography>
                            <TextField
                                fullWidth
                                select
                                label="Agent"
                                value={agentId}
                                onChange={(event) => setAgentId(event.target.value)}
                                sx={{ mb: 2 }}
                                helperText={loadingAgents ? 'Loading agents...' : `${agents.length} agents`}
                            >
                                {agents.map((agent) => (
                                    <MenuItem key={agent.id} value={String(agent.id)}>
                                        {agent.id} - {agent.display_name} ({agent.status})
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                fullWidth
                                label="Agent Phone"
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
                            <Divider sx={{ my: 1.5, borderColor: 'rgba(99,102,241,0.12)' }} />
                            {lastCall ? (
                                <Box sx={{ display: 'grid', gap: 1 }}>
                                    <Chip
                                        size="small"
                                        label={lastCall.status}
                                        sx={{ width: 'fit-content', bgcolor: 'rgba(99,102,241,0.2)', color: '#818cf8' }}
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
