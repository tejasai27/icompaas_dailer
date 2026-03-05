import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Grid,
    MenuItem,
    TextField,
    Typography,
} from '@mui/material';
import {
    ArrowBack,
    CallEnd,
    Dialpad,
    Mic,
    MicOff,
    Refresh,
    VolumeOff,
    VolumeUp,
} from '@mui/icons-material';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import { request } from '../lib/api';

const OUTCOME_OPTIONS = [
    { value: 'connected', label: 'Connected' },
    { value: 'no_answer', label: 'No Answer' },
    { value: 'busy', label: 'Busy' },
    { value: 'voicemail', label: 'Voicemail' },
    { value: 'machine', label: 'Machine' },
    { value: 'bad_number', label: 'Bad Number' },
    { value: 'interested', label: 'Interested' },
    { value: 'not_interested', label: 'Not Interested' },
    { value: 'follow_up', label: 'Follow Up' },
];

function formatSeconds(total) {
    const value = Math.max(0, Number(total || 0));
    const minutes = Math.floor(value / 60);
    const seconds = value % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function normalizeCallStatus(status) {
    return String(status || '').trim().toLowerCase().replace(/_/g, '-');
}

function formatCallStatus(status) {
    const normalized = normalizeCallStatus(status);
    if (!normalized) return '-';
    if (normalized === 'sdr-cut') return 'SDR Cut the Call';
    return normalized
        .split('-')
        .filter(Boolean)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

export default function DialCallPage() {
    const navigate = useNavigate();
    const { callPublicId } = useParams();
    const [searchParams] = useSearchParams();
    const campaignId = searchParams.get('campaign_id');

    const [call, setCall] = useState(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [hangupLoading, setHangupLoading] = useState(false);
    const [savingDisposition, setSavingDisposition] = useState(false);
    const [outcome, setOutcome] = useState('follow_up');
    const [notes, setNotes] = useState('');
    const [dealId, setDealId] = useState('');
    const [dealName, setDealName] = useState('');
    const [muted, setMuted] = useState(false);
    const [speakerOn, setSpeakerOn] = useState(true);
    const [keypadOpen, setKeypadOpen] = useState(false);
    const [timerTick, setTimerTick] = useState(0);
    const [terminalAtMs, setTerminalAtMs] = useState(null);
    const [hasEditedDisposition, setHasEditedDisposition] = useState(false);
    const [autosaveState, setAutosaveState] = useState('idle');
    const lastSavedRef = useRef({ outcome: '', notes: '', dealId: '', dealName: '' });

    const internalStatus = String(call?.internal_status || '').toLowerCase();
    const displayStatus = normalizeCallStatus(call?.status);
    const isTerminal =
        Boolean(call?.ended_at) ||
        internalStatus === 'completed' ||
        internalStatus === 'failed' ||
        ['failed', 'busy', 'no-answer', 'cancelled', 'completed', 'sdr-cut'].includes(displayStatus);
    const isConnected =
        internalStatus === 'bridged' ||
        internalStatus === 'human_detected' ||
        displayStatus === 'answered' ||
        displayStatus === 'completed';

    const elapsedSeconds = useMemo(() => {
        const startedAt = call?.started_at || call?.initiated_at;
        if (!startedAt) return 0;
        const startedMs = new Date(startedAt).getTime();
        const endedMs = call?.ended_at ? new Date(call.ended_at).getTime() : terminalAtMs || Date.now();
        const diff = Math.floor((endedMs - startedMs) / 1000);
        return Math.max(0, diff);
    }, [call?.started_at, call?.initiated_at, call?.ended_at, terminalAtMs, timerTick]);

    const stageText = isTerminal ? 'Call Ended' : isConnected ? 'In Call' : 'Calling';

    async function loadCall({ silent = false } = {}) {
        if (!callPublicId) return;
        if (silent) {
            setRefreshing(true);
        } else {
            setLoading(true);
        }
        try {
            const data = await request(`/api/v1/dialer/calls/${callPublicId}/?sync_exotel=1`);
            const current = data?.call || null;
            setCall(current);
            const serverOutcomeRaw = String(current?.call_outcome || '').trim();
            const serverOutcome = serverOutcomeRaw || 'follow_up';
            const serverNotes = typeof current?.agent_notes === 'string' ? current.agent_notes : '';
            const serverDealId = typeof current?.deal_id === 'string' ? current.deal_id : '';
            const serverDealName = typeof current?.deal_name === 'string' ? current.deal_name : '';
            lastSavedRef.current = {
                outcome: serverOutcome,
                notes: serverNotes,
                dealId: serverDealId,
                dealName: serverDealName,
            };
            if (!hasEditedDisposition) {
                setOutcome(serverOutcome);
                setNotes(serverNotes);
                setDealId(serverDealId);
                setDealName(serverDealName);
                setAutosaveState(serverOutcomeRaw || serverNotes || serverDealId || serverDealName ? 'saved' : 'idle');
            }
        } catch (error) {
            toast.error(error.message || 'Failed to load call status');
        } finally {
            if (silent) {
                setRefreshing(false);
            } else {
                setLoading(false);
            }
        }
    }

    useEffect(() => {
        loadCall();
    }, [callPublicId]);

    useEffect(() => {
        if (isTerminal) return undefined;
        const timer = setInterval(() => {
            setTimerTick((tick) => tick + 1);
        }, 1000);
        return () => clearInterval(timer);
    }, [isTerminal]);

    useEffect(() => {
        if (isTerminal) {
            setTerminalAtMs((previous) => previous || Date.now());
            return;
        }
        setTerminalAtMs(null);
    }, [isTerminal, callPublicId]);

    useEffect(() => {
        if (!callPublicId) return undefined;
        if (isTerminal) return undefined;
        const poll = setInterval(() => {
            loadCall({ silent: true });
        }, 4000);
        return () => clearInterval(poll);
    }, [callPublicId, isTerminal, hasEditedDisposition]);

    async function handleHangup() {
        if (!callPublicId) return;
        setHangupLoading(true);
        try {
            await request(`/api/v1/dialer/calls/${callPublicId}/hangup/`, { method: 'POST' });
            toast.success('Call end requested');
            await loadCall({ silent: true });
        } catch (error) {
            toast.error(error.message || 'Failed to end call');
        } finally {
            setHangupLoading(false);
        }
    }

    async function handleSaveDisposition({ silent = false } = {}) {
        if (!callPublicId) return;
        if (!outcome) {
            if (!silent) toast.error('Select call outcome');
            return;
        }
        if (!silent) setSavingDisposition(true);
        try {
            const data = await request(`/api/v1/dialer/calls/${callPublicId}/disposition/`, {
                method: 'POST',
                body: JSON.stringify({
                    outcome,
                    notes,
                    deal_id: dealId,
                    deal_name: dealName,
                }),
            });
            if (data?.call) {
                setCall(data.call);
            }
            lastSavedRef.current = { outcome, notes, dealId, dealName };
            setAutosaveState('saved');
            if (!silent) toast.success('Outcome and notes saved');
        } catch (error) {
            setAutosaveState('error');
            if (!silent) toast.error(error.message || 'Failed to save disposition');
        } finally {
            if (!silent) setSavingDisposition(false);
        }
    }

    useEffect(() => {
        if (!callPublicId || !hasEditedDisposition) return undefined;

        const unchanged =
            lastSavedRef.current.outcome === String(outcome || '') &&
            lastSavedRef.current.notes === String(notes || '') &&
            lastSavedRef.current.dealId === String(dealId || '') &&
            lastSavedRef.current.dealName === String(dealName || '');
        if (unchanged) {
            setAutosaveState('saved');
            return undefined;
        }

        setAutosaveState('saving');
        const timer = setTimeout(() => {
            handleSaveDisposition({ silent: true });
        }, 900);
        return () => clearTimeout(timer);
    }, [callPublicId, hasEditedDisposition, outcome, notes, dealId, dealName]);

    function goBackToDial() {
        const path = campaignId ? `/dial?campaign_id=${encodeURIComponent(campaignId)}` : '/dial';
        navigate(path);
    }

    if (loading) {
        return (
            <Box sx={{ py: 6, display: 'flex', justifyContent: 'center' }}>
                <CircularProgress />
            </Box>
        );
    }

    return (
        <Box>
            <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1 }}>
                <Button startIcon={<ArrowBack />} onClick={goBackToDial}>
                    Back to Dialer
                </Button>
                <Button
                    variant="outlined"
                    size="small"
                    startIcon={refreshing ? <CircularProgress size={14} color="inherit" /> : <Refresh />}
                    onClick={() => loadCall({ silent: true })}
                    disabled={refreshing || hangupLoading}
                >
                    Refresh
                </Button>
            </Box>

            <Grid container spacing={2}>
                <Grid item xs={12} md={7}>
                    <Card>
                        <CardContent>
                            <Box sx={{ textAlign: 'center', py: 2 }}>
                                <Typography variant="overline" color="text.secondary">
                                    {stageText}
                                </Typography>
                                <Typography variant="h5" fontWeight={700} sx={{ mt: 1 }}>
                                    {call?.contact_name || 'Contact'}
                                </Typography>
                                <Typography color="text.secondary" sx={{ mt: 0.5 }}>
                                    {call?.contact_phone || '-'}
                                </Typography>
                                <Chip
                                    size="small"
                                    label={formatCallStatus(call?.status)}
                                    sx={{ mt: 1.5, bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' }}
                                />
                                <Typography variant="h3" fontWeight={700} sx={{ mt: 2.5, mb: 2 }}>
                                    {formatSeconds(elapsedSeconds)}
                                </Typography>

                                <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 1, mb: 2 }}>
                                    <Button
                                        variant={muted ? 'contained' : 'outlined'}
                                        startIcon={muted ? <MicOff /> : <Mic />}
                                        onClick={() => setMuted((v) => !v)}
                                    >
                                        {muted ? 'Muted' : 'Mute'}
                                    </Button>
                                    <Button
                                        variant={speakerOn ? 'contained' : 'outlined'}
                                        startIcon={speakerOn ? <VolumeUp /> : <VolumeOff />}
                                        onClick={() => setSpeakerOn((v) => !v)}
                                    >
                                        {speakerOn ? 'Speaker' : 'Earpiece'}
                                    </Button>
                                    <Button
                                        variant={keypadOpen ? 'contained' : 'outlined'}
                                        startIcon={<Dialpad />}
                                        onClick={() => setKeypadOpen((v) => !v)}
                                    >
                                        Keypad
                                    </Button>
                                </Box>
                                <Typography variant="caption" color="text.secondary">
                                    Mute and Speaker are local UI controls only and are not stored in DB.
                                </Typography>

                                {!isTerminal ? (
                                    <Button
                                        color="error"
                                        variant="contained"
                                        size="large"
                                        startIcon={hangupLoading ? <CircularProgress size={16} color="inherit" /> : <CallEnd />}
                                        onClick={handleHangup}
                                        disabled={hangupLoading}
                                        sx={{ minWidth: 220 }}
                                    >
                                        {hangupLoading ? 'Ending...' : 'End Call'}
                                    </Button>
                                ) : (
                                    <Alert severity="success" sx={{ textAlign: 'left' }}>
                                        Call ended. Complete call outcome and notes on the right.
                                    </Alert>
                                )}
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>

                <Grid item xs={12} md={5}>
                    <Card>
                        <CardContent>
                            <Typography variant="h6" fontWeight={700} sx={{ mb: 1 }}>
                                Call Wrap-Up
                            </Typography>
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                                Notes, outcome and deal details autosave during the call and are stored in DB.
                            </Typography>

                            <TextField
                                fullWidth
                                select
                                label="Call Outcome"
                                value={outcome}
                                onChange={(event) => {
                                    setOutcome(event.target.value);
                                    setHasEditedDisposition(true);
                                }}
                                sx={{ mb: 2 }}
                            >
                                {OUTCOME_OPTIONS.map((item) => (
                                    <MenuItem key={item.value} value={item.value}>
                                        {item.label}
                                    </MenuItem>
                                ))}
                            </TextField>
                            <TextField
                                fullWidth
                                multiline
                                minRows={4}
                                label="Notes"
                                value={notes}
                                onChange={(event) => {
                                    setNotes(event.target.value);
                                    setHasEditedDisposition(true);
                                }}
                                placeholder="Add summary, objections, next step, follow-up context..."
                                sx={{ mb: 2 }}
                            />
                            <TextField
                                fullWidth
                                label="Deal ID (Optional)"
                                value={dealId}
                                onChange={(event) => {
                                    setDealId(event.target.value);
                                    setHasEditedDisposition(true);
                                }}
                                sx={{ mb: 2 }}
                            />
                            <TextField
                                fullWidth
                                label="Deal Name (Optional)"
                                value={dealName}
                                onChange={(event) => {
                                    setDealName(event.target.value);
                                    setHasEditedDisposition(true);
                                }}
                                sx={{ mb: 2 }}
                            />
                            <Alert
                                severity={
                                    autosaveState === 'error'
                                        ? 'error'
                                        : autosaveState === 'saving'
                                            ? 'info'
                                            : autosaveState === 'saved'
                                                ? 'success'
                                                : 'info'
                                }
                                sx={{ mb: 2 }}
                            >
                                {autosaveState === 'error'
                                    ? 'Autosave failed. Use Save button.'
                                    : autosaveState === 'saving'
                                        ? 'Saving call wrap-up...'
                                        : autosaveState === 'saved'
                                            ? 'Call wrap-up saved in DB.'
                                            : 'Changes will autosave while you type.'}
                            </Alert>
                            <Button
                                fullWidth
                                variant="contained"
                                onClick={() => handleSaveDisposition({ silent: false })}
                                disabled={savingDisposition}
                            >
                                {savingDisposition ? 'Saving...' : 'Save Wrap-Up'}
                            </Button>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    );
}
