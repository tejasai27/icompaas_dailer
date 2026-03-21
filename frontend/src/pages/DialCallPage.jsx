import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
    Alert,
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
    TextField,
    Typography,
} from '@mui/material';
import {
    ArrowBack,
    CallEnd,
    Campaign as CampaignIcon,
    CheckCircle as CheckCircleIcon,
    ErrorOutline,
    ExpandLess,
    ExpandMore,
    Person,
    Phone as PhoneIcon,
    Refresh,
    Sync as SyncIcon,
} from '@mui/icons-material';
import { keyframes } from '@emotion/react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import api from '../services/api';
import { normalizeCallStatus, formatCallStatus, formatSeconds } from '../lib/callStatus';
import { shortDateTime } from '../lib/formatDate';
import useVisibleInterval from '../lib/useVisibleInterval';

const PRIMARY_OUTCOMES = [
    { value: 'connected', label: 'Connected', color: '#10b981' },
    { value: 'no_answer', label: 'No Answer', color: '#f59e0b' },
    { value: 'busy', label: 'Busy', color: '#f59e0b' },
];

const SECONDARY_OUTCOMES = [
    { value: 'interested', label: 'Interested', color: '#10b981' },
    { value: 'follow_up', label: 'Follow Up', color: '#3b82f6' },
    { value: 'not_interested', label: 'Not Interested', color: '#ef4444' },
    { value: 'voicemail', label: 'Voicemail', color: '#8b5cf6' },
    { value: 'machine', label: 'Machine', color: '#8b5cf6' },
    { value: 'bad_number', label: 'Bad Number', color: '#ef4444' },
];

/* ── Pulsing ring animation for ringing state ── */
const pulseRing = keyframes`
    0%   { transform: scale(1);   opacity: 0.6; }
    100% { transform: scale(2.8); opacity: 0; }
`;

function PulsingCallIndicator() {
    const ringStyle = (delay) => ({
        position: 'absolute',
        inset: 0,
        borderRadius: '50%',
        border: '2px solid #3b82f6',
        animation: `${pulseRing} 2s ease-out infinite`,
        animationDelay: `${delay}s`,
        willChange: 'transform, opacity',
    });

    return (
        <Box sx={{ position: 'relative', width: 80, height: 80, mx: 'auto', mb: 3 }}>
            <Box sx={ringStyle(0)} />
            <Box sx={ringStyle(0.5)} />
            <Box sx={ringStyle(1)} />
            <Avatar sx={{
                width: 80, height: 80, bgcolor: '#3b82f6',
                position: 'relative', zIndex: 1,
                boxShadow: '0 0 24px rgba(59,130,246,0.35)',
            }}>
                <PhoneIcon sx={{ fontSize: 36 }} />
            </Avatar>
        </Box>
    );
}

/* ── Contact context card (left panel) ── */
function ContactContextCard({ call, campaignId }) {
    return (
        <Card sx={{ height: '100%' }}>
            <CardContent>
                <Box sx={{ textAlign: 'center', mb: 2 }}>
                    <Avatar sx={{
                        width: 56, height: 56, mx: 'auto', mb: 1.5,
                        bgcolor: '#0142a2', fontSize: '1.25rem', fontWeight: 700,
                    }}>
                        {(call?.contact_name || '?')[0].toUpperCase()}
                    </Avatar>
                    <Typography variant="h6" fontWeight={700} noWrap>
                        {call?.contact_name || 'Contact'}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" fontFamily="monospace">
                        {call?.contact_phone || '-'}
                    </Typography>
                </Box>

                <Divider sx={{ my: 1.5, borderColor: 'rgba(1,66,162,0.1)' }} />

                <Box sx={{ display: 'grid', gap: 1.5 }}>
                    {call?.contact_company && (
                        <Box>
                            <Typography variant="caption" color="text.secondary">Company</Typography>
                            <Typography variant="body2" fontWeight={500}>{call.contact_company}</Typography>
                        </Box>
                    )}
                    {call?.contact_email && (
                        <Box>
                            <Typography variant="caption" color="text.secondary">Email</Typography>
                            <Typography variant="body2" fontWeight={500} sx={{ wordBreak: 'break-all' }}>
                                {call.contact_email}
                            </Typography>
                        </Box>
                    )}
                    {call?.agent_name && (
                        <Box>
                            <Typography variant="caption" color="text.secondary">SDR</Typography>
                            <Typography variant="body2" fontWeight={500}>{call.agent_name}</Typography>
                        </Box>
                    )}
                    {campaignId && call?.campaign_name && (
                        <Box>
                            <Typography variant="caption" color="text.secondary">Campaign</Typography>
                            <Chip
                                icon={<CampaignIcon sx={{ fontSize: 14 }} />}
                                label={call.campaign_name}
                                size="small"
                                sx={{ bgcolor: 'rgba(1,66,162,0.1)', color: '#1a5bc4', mt: 0.5 }}
                            />
                        </Box>
                    )}
                    {call?.initiated_at && (
                        <Box>
                            <Typography variant="caption" color="text.secondary">Started at</Typography>
                            <Typography variant="body2">{shortDateTime(call.initiated_at)}</Typography>
                        </Box>
                    )}
                </Box>
            </CardContent>
        </Card>
    );
}

/* ── Disposition button grid with primary/secondary split ── */
function DispositionButtonGrid({ primaryOptions, secondaryOptions, value, onChange, showMore, onToggleMore }) {
    const renderButton = (opt, size = 'small') => {
        const isSelected = value === opt.value;
        const isPrimary = size === 'large';
        return (
            <Button
                key={opt.value}
                size={size}
                variant={isSelected ? 'contained' : 'outlined'}
                onClick={() => onChange(opt.value)}
                sx={{
                    py: isPrimary ? 1.25 : 0.75,
                    fontSize: isPrimary ? '0.85rem' : '0.72rem',
                    fontWeight: 600,
                    borderRadius: 2,
                    textTransform: 'none',
                    ...(isSelected
                        ? { bgcolor: opt.color, color: '#fff', borderColor: opt.color, '&:hover': { bgcolor: opt.color, filter: 'brightness(0.9)' } }
                        : { borderColor: `${opt.color}40`, color: opt.color, '&:hover': { bgcolor: `${opt.color}10`, borderColor: opt.color } }),
                }}
            >
                {opt.label}
            </Button>
        );
    };

    return (
        <Box sx={{ mb: 3 }}>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, mb: 1 }}>
                {primaryOptions.map((opt) => renderButton(opt, 'large'))}
            </Box>
            <Button
                size="small" fullWidth
                endIcon={showMore ? <ExpandLess sx={{ fontSize: 16 }} /> : <ExpandMore sx={{ fontSize: 16 }} />}
                onClick={onToggleMore}
                sx={{ color: '#94a3b8', textTransform: 'none', fontSize: '0.72rem', mb: 0.5 }}
            >
                {showMore ? 'Fewer outcomes' : 'More outcomes'}
            </Button>
            <Collapse in={showMore}>
                <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 0.75 }}>
                    {secondaryOptions.map((opt) => renderButton(opt))}
                </Box>
            </Collapse>
        </Box>
    );
}

/* ── Notes panel (right panel) ── */
function NotesPanel({ notes, setNotes, dealId, setDealId, dealName, setDealName, autosaveState, setHasEditedDisposition, onSave, savingDisposition }) {
    const autosaveColor = autosaveState === 'error' ? '#ef4444' : autosaveState === 'saved' ? '#10b981' : autosaveState === 'saving' ? '#3b82f6' : '#94a3b8';
    const autosaveText = autosaveState === 'error' ? 'Save failed' : autosaveState === 'saving' ? 'Saving...' : autosaveState === 'saved' ? 'Saved' : 'Autosave';
    const autosaveIcon = autosaveState === 'saved' ? <CheckCircleIcon sx={{ fontSize: 14 }} /> : autosaveState === 'saving' ? <SyncIcon sx={{ fontSize: 14 }} /> : autosaveState === 'error' ? <ErrorOutline sx={{ fontSize: 14 }} /> : undefined;

    return (
        <Card sx={{ height: '100%' }}>
            <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Typography variant="h6" fontWeight={700}>Notes</Typography>
                    <Chip icon={autosaveIcon} label={autosaveText} size="small" sx={{ bgcolor: `${autosaveColor}20`, color: autosaveColor, fontWeight: 600, fontSize: '0.75rem', height: 28, '& .MuiChip-icon': { color: autosaveColor } }} />
                </Box>

                <TextField
                    fullWidth
                    multiline
                    minRows={5}
                    value={notes}
                    onChange={(e) => { setNotes(e.target.value); setHasEditedDisposition(true); }}
                    placeholder="Summary, objections, next steps..."
                    helperText={`${notes.length} / 2000`}
                    inputProps={{ maxLength: 2000 }}
                    sx={{ mb: 2 }}
                />

                <Divider sx={{ my: 1.5, borderColor: 'rgba(1,66,162,0.1)' }}>
                    <Typography variant="caption" color="text.secondary">Deal (optional)</Typography>
                </Divider>

                <TextField
                    fullWidth size="small" label="Deal ID" value={dealId}
                    onChange={(e) => { setDealId(e.target.value); setHasEditedDisposition(true); }}
                    sx={{ mb: 1.5 }}
                />
                <TextField
                    fullWidth size="small" label="Deal Name" value={dealName}
                    onChange={(e) => { setDealName(e.target.value); setHasEditedDisposition(true); }}
                    sx={{ mb: 2 }}
                />

                <Button
                    fullWidth variant="contained" onClick={onSave} disabled={savingDisposition}
                    sx={{ bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' } }}
                >
                    {savingDisposition ? 'Saving...' : 'Save Wrap-Up'}
                </Button>
            </CardContent>
        </Card>
    );
}

/* ── Main page ── */
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
    const [timerTick, setTimerTick] = useState(0);
    const [terminalAtMs, setTerminalAtMs] = useState(null);
    const [hasEditedDisposition, setHasEditedDisposition] = useState(false);
    const [autosaveState, setAutosaveState] = useState('idle');
    const [showMoreOutcomes, setShowMoreOutcomes] = useState(false);
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
    const stageColor = isTerminal ? '#64748b' : isConnected ? '#10b981' : '#3b82f6';

    async function loadCall({ silent = false } = {}) {
        if (!callPublicId) return;
        if (silent) { setRefreshing(true); } else { setLoading(true); }
        try {
            const { data } = await api.get(`/calls/${callPublicId}/?sync_exotel=1`);
            const current = data?.call || null;
            setCall(current);
            const serverOutcomeRaw = String(current?.call_outcome || '').trim();
            const serverOutcome = serverOutcomeRaw || 'follow_up';
            const serverNotes = typeof current?.agent_notes === 'string' ? current.agent_notes : '';
            const serverDealId = typeof current?.deal_id === 'string' ? current.deal_id : '';
            const serverDealName = typeof current?.deal_name === 'string' ? current.deal_name : '';
            lastSavedRef.current = { outcome: serverOutcome, notes: serverNotes, dealId: serverDealId, dealName: serverDealName };
            if (!hasEditedDisposition) {
                setOutcome(serverOutcome);
                setNotes(serverNotes);
                setDealId(serverDealId);
                setDealName(serverDealName);
                setAutosaveState(serverOutcomeRaw || serverNotes || serverDealId || serverDealName ? 'saved' : 'idle');
            }
        } catch (error) {
            toast.error(error.response?.data?.error || error.message || 'Failed to load call status');
        } finally {
            if (silent) { setRefreshing(false); } else { setLoading(false); }
        }
    }

    useEffect(() => { loadCall(); }, [callPublicId]);

    useEffect(() => {
        if (isTerminal) return undefined;
        const timer = setInterval(() => setTimerTick((t) => t + 1), 1000);
        return () => clearInterval(timer);
    }, [isTerminal]);

    useEffect(() => {
        if (isTerminal) { setTerminalAtMs((prev) => prev || Date.now()); return; }
        setTerminalAtMs(null);
    }, [isTerminal, callPublicId]);

    useVisibleInterval(() => { loadCall({ silent: true }); }, (!callPublicId || isTerminal) ? null : 4000);

    async function handleHangup() {
        if (!callPublicId) return;
        setHangupLoading(true);
        try {
            await api.post(`/calls/${callPublicId}/hangup/`);
            toast.success('Call end requested');
            await loadCall({ silent: true });
        } catch (error) {
            toast.error(error.response?.data?.error || error.message || 'Failed to end call');
        } finally {
            setHangupLoading(false);
        }
    }

    async function handleSaveDisposition({ silent = false } = {}) {
        if (!callPublicId) return;
        if (!outcome) { if (!silent) toast.error('Select call outcome'); return; }
        if (!silent) setSavingDisposition(true);
        try {
            const { data } = await api.post(`/calls/${callPublicId}/disposition/`, { outcome, notes, deal_id: dealId, deal_name: dealName });
            if (data?.call) setCall(data.call);
            lastSavedRef.current = { outcome, notes, dealId, dealName };
            setAutosaveState('saved');
            if (!silent) toast.success('Outcome and notes saved');
        } catch (error) {
            setAutosaveState('error');
            if (!silent) toast.error(error.response?.data?.error || error.message || 'Failed to save disposition');
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
        if (unchanged) { setAutosaveState('saved'); return undefined; }
        setAutosaveState('saving');
        const timer = setTimeout(() => handleSaveDisposition({ silent: true }), 900);
        return () => clearTimeout(timer);
    }, [callPublicId, hasEditedDisposition, outcome, notes, dealId, dealName]);

    // Auto-expand secondary outcomes if the selected outcome is in the secondary list
    useEffect(() => {
        if (SECONDARY_OUTCOMES.some((o) => o.value === outcome)) setShowMoreOutcomes(true);
    }, [outcome]);

    function goBackToDial() {
        if (hasEditedDisposition && autosaveState !== 'saved') {
            const confirmed = window.confirm('You have unsaved changes. Are you sure you want to leave?');
            if (!confirmed) return;
        }
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
            {/* Toolbar */}
            <Box sx={{ mb: 2, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 1 }}>
                <Button startIcon={<ArrowBack />} onClick={goBackToDial} sx={{ color: '#64748b' }}>
                    Back to Dialer
                </Button>
                <Button
                    variant="outlined" size="small"
                    startIcon={refreshing ? <CircularProgress size={14} color="inherit" /> : <Refresh />}
                    onClick={() => loadCall({ silent: true })} disabled={refreshing || hangupLoading}
                >
                    Refresh
                </Button>
            </Box>

            <Grid container spacing={2}>
                {/* LEFT — Contact Context */}
                <Grid item xs={12} md={3} order={{ xs: 2, md: 1 }}>
                    <ContactContextCard call={call} campaignId={campaignId} />
                </Grid>

                {/* CENTER — Call Status Hero */}
                <Grid item xs={12} md={5} order={{ xs: 1, md: 2 }}>
                    <Card>
                        <CardContent sx={{ textAlign: 'center', py: 4 }}>
                            {/* Pulsing animation for ringing state */}
                            {!isTerminal && !isConnected && <PulsingCallIndicator />}

                            {/* Connected indicator */}
                            {isConnected && (
                                <Avatar sx={{ width: 80, height: 80, mx: 'auto', mb: 3, bgcolor: '#10b981', boxShadow: '0 0 24px rgba(16,185,129,0.35)' }}>
                                    <PhoneIcon sx={{ fontSize: 36 }} />
                                </Avatar>
                            )}

                            {/* Ended indicator */}
                            {isTerminal && (
                                <Avatar sx={{ width: 80, height: 80, mx: 'auto', mb: 3, bgcolor: '#64748b' }}>
                                    <CallEnd sx={{ fontSize: 36 }} />
                                </Avatar>
                            )}

                            <Chip
                                label={stageText}
                                sx={{ mb: 1, bgcolor: `${stageColor}20`, color: stageColor, fontWeight: 700, fontSize: '0.8rem' }}
                            />

                            <Typography
                                variant="h2"
                                fontWeight={800}
                                sx={{ my: 2, fontVariantNumeric: 'tabular-nums', color: stageColor }}
                            >
                                {formatSeconds(elapsedSeconds)}
                            </Typography>

                            {isTerminal && call?.duration_formatted && (
                                <Typography variant="body2" sx={{ color: '#64748b', mb: 1 }}>
                                    Duration: {call.duration_formatted}
                                </Typography>
                            )}

                            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                                {call?.contact_name || 'Contact'} · {formatCallStatus(call?.status)}
                            </Typography>

                            {/* Disposition buttons */}
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                                Call Outcome
                            </Typography>
                            <DispositionButtonGrid
                                primaryOptions={PRIMARY_OUTCOMES}
                                secondaryOptions={SECONDARY_OUTCOMES}
                                value={outcome}
                                onChange={(val) => { setOutcome(val); setHasEditedDisposition(true); }}
                                showMore={showMoreOutcomes}
                                onToggleMore={() => setShowMoreOutcomes((v) => !v)}
                            />

                            {/* End Call / Call Ended */}
                            {!isTerminal ? (
                                <Button
                                    color="error" variant="contained" size="large" fullWidth
                                    startIcon={hangupLoading ? <CircularProgress size={16} color="inherit" /> : <CallEnd />}
                                    onClick={handleHangup} disabled={hangupLoading}
                                    sx={{ py: 1.5, borderRadius: 3, fontSize: '1rem' }}
                                >
                                    {hangupLoading ? 'Ending...' : 'End Call'}
                                </Button>
                            ) : (
                                <Alert severity="success" sx={{ borderRadius: 2 }}>
                                    Call ended. Complete your notes on the right.
                                </Alert>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                {/* RIGHT — Notes + Deal */}
                <Grid item xs={12} md={4} order={{ xs: 3, md: 3 }}>
                    <NotesPanel
                        notes={notes} setNotes={setNotes}
                        dealId={dealId} setDealId={setDealId}
                        dealName={dealName} setDealName={setDealName}
                        autosaveState={autosaveState}
                        setHasEditedDisposition={setHasEditedDisposition}
                        onSave={() => handleSaveDisposition({ silent: false })}
                        savingDisposition={savingDisposition}
                    />
                </Grid>
            </Grid>
        </Box>
    );
}
