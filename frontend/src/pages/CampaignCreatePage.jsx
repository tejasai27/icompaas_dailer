import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    CircularProgress,
    Divider,
    Grid,
    MenuItem,
    Select,
    Step,
    StepLabel,
    Stepper,
    Tab,
    Tabs,
    TextField,
    Typography,
} from '@mui/material';
import { ArrowBack, ArrowForward, Check, CloudUpload, PlayArrow } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import toast from 'react-hot-toast';
import api from '../services/api';

const STEPS = ['Dialing Mode', 'Campaign Details', 'Add Contacts', 'Review'];

function DialingModeStep({ mode, onChange }) {
    const modes = [
        { id: 'power', title: 'Power Dialer', desc: 'Queue calls one by one.', icon: '⚡', available: true },
        { id: 'dynamic', title: 'Dynamic Dialer', desc: 'Parallel dialing for high volume.', icon: '🔀', available: false },
    ];

    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Select Dialing Mode</Typography>
            <Typography color="text.secondary" variant="body2" mb={3}>
                Power dialer is active now. Dynamic dialer will be added later.
            </Typography>
            <Grid container spacing={2}>
                {modes.map((item) => (
                    <Grid item xs={12} md={6} key={item.id}>
                        <Box
                            onClick={() => item.available && onChange(item.id)}
                            sx={{
                                p: 3,
                                borderRadius: 3,
                                cursor: item.available ? 'pointer' : 'not-allowed',
                                border: `2px solid ${mode === item.id ? '#0142a2' : 'rgba(1,66,162,0.15)'}`,
                                bgcolor: mode === item.id ? 'rgba(1,66,162,0.1)' : 'rgba(255,255,255,0.02)',
                                opacity: item.available ? 1 : 0.6,
                                transition: 'all 0.2s',
                                '&:hover': { borderColor: item.available ? 'rgba(1,66,162,0.4)' : 'rgba(1,66,162,0.15)' },
                            }}
                        >
                            {!item.available ? (
                                <Chip
                                    label="In future"
                                    size="small"
                                    sx={{ mb: 1, bgcolor: 'rgba(245,158,11,0.2)', color: '#f59e0b' }}
                                />
                            ) : null}
                            <Typography fontSize="2rem" mb={1}>{item.icon}</Typography>
                            <Typography variant="h6" fontWeight={600}>{item.title}</Typography>
                            <Typography variant="body2" color="text.secondary">{item.desc}</Typography>
                        </Box>
                    </Grid>
                ))}
            </Grid>
        </Box>
    );
}

function CampaignDetailsStep({ details, onChange, agents, loadingAgents }) {
    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Campaign Details</Typography>
            <Typography color="text.secondary" variant="body2" mb={3}>
                Agent and agent phone are required to run queue calls.
            </Typography>
            <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                    <TextField
                        fullWidth
                        label="Campaign Name *"
                        value={details.name}
                        onChange={(e) => onChange({ ...details, name: e.target.value })}
                    />
                </Grid>
                <Grid item xs={12} md={6}>
                    <TextField
                        select
                        fullWidth
                        label="Timezone"
                        value={details.timezone}
                        onChange={(e) => onChange({ ...details, timezone: e.target.value })}
                    >
                        <MenuItem value="Asia/Kolkata">Asia/Kolkata</MenuItem>
                        <MenuItem value="Asia/Dubai">Asia/Dubai</MenuItem>
                        <MenuItem value="Europe/London">Europe/London</MenuItem>
                        <MenuItem value="America/New_York">America/New_York</MenuItem>
                    </TextField>
                </Grid>
                <Grid item xs={12} md={6}>
                    <TextField
                        fullWidth
                        type="number"
                        label="Delay Between Calls (sec)"
                        value={details.delay_between_calls}
                        onChange={(e) => onChange({ ...details, delay_between_calls: Number(e.target.value || 0) })}
                        inputProps={{ min: 5, max: 300 }}
                    />
                </Grid>
                <Grid item xs={12} md={6}>
                    <TextField
                        fullWidth
                        label="Caller ID (optional)"
                        value={details.caller_id}
                        onChange={(e) => onChange({ ...details, caller_id: e.target.value })}
                        placeholder="+91XXXXXXXXXX"
                    />
                </Grid>
                <Grid item xs={12} md={6}>
                    <TextField
                        fullWidth
                        label="Agent Phone *"
                        value={details.agent_phone}
                        onChange={(e) => onChange({ ...details, agent_phone: e.target.value })}
                        placeholder="+91XXXXXXXXXX"
                    />
                </Grid>
                <Grid item xs={12}>
                    <TextField
                        fullWidth
                        multiline
                        rows={3}
                        label="Description (optional)"
                        value={details.description}
                        onChange={(e) => onChange({ ...details, description: e.target.value })}
                    />
                </Grid>
                <Grid item xs={12}>
                    <Typography variant="subtitle2" mb={1}>Assigned Agent *</Typography>
                    {loadingAgents ? (
                        <CircularProgress size={20} />
                    ) : (
                        <Select
                            fullWidth
                            value={details.agent_id}
                            onChange={(e) => onChange({ ...details, agent_id: e.target.value })}
                        >
                            <MenuItem value=""><em>Select agent…</em></MenuItem>
                            {agents.map((agent) => (
                                <MenuItem key={agent.id} value={agent.id}>
                                    {agent.display_name} ({agent.status})
                                </MenuItem>
                            ))}
                        </Select>
                    )}
                </Grid>
            </Grid>
        </Box>
    );
}

function parseManualLeads(text) {
    return text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
            const [first = '', second = ''] = line.split(',').map((value) => value.trim());
            if (second) return { full_name: first, phone_e164: second };
            return { phone_e164: first };
        });
}

function AddContactsStep({
    inputMode,
    setInputMode,
    csvFile,
    setCsvFile,
    manualLeadsText,
    setManualLeadsText,
}) {
    const onDrop = (files) => setCsvFile(files?.[0] || null);
    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: { 'text/csv': ['.csv'] },
        maxFiles: 1,
    });
    const parsedManualCount = useMemo(() => parseManualLeads(manualLeadsText).length, [manualLeadsText]);

    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Add Contacts</Typography>
            <Typography color="text.secondary" variant="body2" mb={2}>
                Upload CSV or paste manual leads. Manual format: `Name,+91...` or `+91...` per line.
            </Typography>
            <Alert severity="info" sx={{ mb: 2 }}>
                CSV header supported: <strong>Deal Name,Name,Designation,Email,Phone number</strong>
            </Alert>

            <Tabs
                value={inputMode}
                onChange={(_, value) => setInputMode(value)}
                sx={{ mb: 2, '& .MuiTabs-indicator': { bgcolor: '#0142a2' }, '& .MuiTab-root': { textTransform: 'none' } }}
            >
                <Tab value="csv" label="CSV Upload" />
                <Tab value="manual" label="Manual Leads" />
            </Tabs>

            {inputMode === 'csv' ? (
                <Box
                    {...getRootProps()}
                    sx={{
                        border: `2px dashed ${isDragActive ? '#0142a2' : 'rgba(1,66,162,0.35)'}`,
                        borderRadius: 3,
                        p: 5,
                        textAlign: 'center',
                        cursor: 'pointer',
                        bgcolor: isDragActive ? 'rgba(1,66,162,0.08)' : 'rgba(1,66,162,0.03)',
                    }}
                >
                    <input {...getInputProps()} />
                    <CloudUpload sx={{ fontSize: 54, color: '#0142a2', mb: 1 }} />
                    <Typography variant="body1" fontWeight={600} mb={1}>
                        {isDragActive ? 'Drop CSV here' : 'Drag & drop CSV file here'}
                    </Typography>
                    <Typography color="text.secondary" variant="body2">Click to choose a `.csv` file</Typography>
                    {csvFile ? (
                        <Chip label={`Selected: ${csvFile.name}`} sx={{ mt: 2, bgcolor: 'rgba(16,185,129,0.12)', color: '#10b981' }} />
                    ) : null}
                </Box>
            ) : (
                <TextField
                    fullWidth
                    multiline
                    rows={10}
                    value={manualLeadsText}
                    onChange={(e) => setManualLeadsText(e.target.value)}
                    placeholder={'John Doe,+919999999999\n+918888888888'}
                    helperText={`${parsedManualCount} lead(s) parsed`}
                />
            )}
        </Box>
    );
}

function ReviewStep({ dialingMode, details, inputMode, csvFile, manualLeadsText, submitResult, createdCampaign }) {
    const manualCount = parseManualLeads(manualLeadsText).length;
    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={2}>Review</Typography>
            <Grid container spacing={2}>
                <Grid item xs={12} md={6}>
                    <Card variant="outlined" sx={{ borderColor: 'rgba(1,66,162,0.2)' }}>
                        <CardContent>
                            <Typography variant="subtitle2" color="text.secondary">Campaign</Typography>
                            <Typography variant="h6" fontWeight={700}>{details.name || '-'}</Typography>
                            <Typography variant="body2" color="text.secondary">Mode: {dialingMode}</Typography>
                            <Typography variant="body2" color="text.secondary">
                                Agent: {details.agent_id || '-'} · Phone: {details.agent_phone || '-'}
                            </Typography>
                            {createdCampaign?.id ? (
                                <Typography variant="body2" color="text.secondary">Campaign ID: {createdCampaign.id}</Typography>
                            ) : null}
                        </CardContent>
                    </Card>
                </Grid>
                <Grid item xs={12} md={6}>
                    <Card variant="outlined" sx={{ borderColor: 'rgba(1,66,162,0.2)' }}>
                        <CardContent>
                            <Typography variant="subtitle2" color="text.secondary">Contacts</Typography>
                            <Typography variant="h6" fontWeight={700}>
                                {inputMode === 'csv' ? 'CSV Upload' : 'Manual Leads'}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                                {inputMode === 'csv' ? (csvFile?.name || 'No file selected') : `${manualCount} leads parsed`}
                            </Typography>
                            {submitResult ? (
                                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                                    Created {submitResult.createdCount} · Existing {submitResult.existingCount} · Invalid {submitResult.invalidCount}
                                </Typography>
                            ) : null}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
            <Alert severity="success" sx={{ mt: 2 }}>
                Campaign created with queue leads. You can start queue calling from campaign detail or directly run in dialer.
            </Alert>
        </Box>
    );
}

export default function CampaignCreatePage() {
    const navigate = useNavigate();
    const [activeStep, setActiveStep] = useState(0);
    const [dialingMode, setDialingMode] = useState('power');
    const [details, setDetails] = useState({
        name: '',
        timezone: 'Asia/Kolkata',
        delay_between_calls: 15,
        caller_id: '',
        description: '',
        agent_id: '',
        agent_phone: '',
    });
    const [inputMode, setInputMode] = useState('csv');
    const [csvFile, setCsvFile] = useState(null);
    const [manualLeadsText, setManualLeadsText] = useState('');
    const [submitResult, setSubmitResult] = useState(null);
    const [createdCampaign, setCreatedCampaign] = useState(null);
    const [submitting, setSubmitting] = useState(false);
    const [agents, setAgents] = useState([]);
    const [loadingAgents, setLoadingAgents] = useState(true);

    useEffect(() => {
        let mounted = true;
        api.get('/agents/')
            .then((res) => {
                if (!mounted) return;
                const list = Array.isArray(res.data?.agents) ? res.data.agents : [];
                setAgents(list);
            })
            .catch(() => toast.error('Unable to fetch agents'))
            .finally(() => mounted && setLoadingAgents(false));
        return () => { mounted = false; };
    }, []);

    const canProceed = () => {
        if (activeStep === 1) {
            return Boolean(details.name.trim() && details.agent_id && details.agent_phone.trim());
        }
        if (activeStep === 2) {
            if (inputMode === 'csv') return Boolean(csvFile);
            return parseManualLeads(manualLeadsText).length > 0;
        }
        return true;
    };

    const handleSubmit = async () => {
        if (!details.name.trim()) {
            toast.error('Campaign name is required');
            return;
        }
        if (!details.agent_id || !details.agent_phone.trim()) {
            toast.error('Assigned agent and agent phone are required');
            return;
        }

        setSubmitting(true);
        try {
            const campaignPayload = {
                name: details.name.trim(),
                description: details.description,
                dialing_mode: dialingMode,
                assigned_agent: Number(details.agent_id),
                agent_phone: details.agent_phone.trim(),
                caller_id: details.caller_id.trim(),
                delay_between_calls: details.delay_between_calls,
                max_retries: 0,
                metadata: { timezone: details.timezone },
            };
            const campaignRes = await api.post('/campaigns/', campaignPayload);
            const campaign = campaignRes.data || {};
            const campaignId = campaign.id;
            if (!campaignId) {
                throw new Error('Campaign was not created');
            }

            let createdCount = 0;
            let existingCount = 0;
            let invalidCount = 0;

            if (inputMode === 'csv') {
                if (!csvFile) throw new Error('Please upload a CSV file');
                const formData = new FormData();
                formData.append('file', csvFile);
                formData.append('campaign_id', String(campaignId));
                formData.append('campaign_name', details.name.trim());
                formData.append('timezone', details.timezone);
                formData.append('dialing_mode', dialingMode);
                formData.append('delay_between_calls', String(details.delay_between_calls));
                formData.append('max_retries', '0');
                formData.append('caller_id', details.caller_id || '');
                formData.append('description', details.description || '');
                formData.append('agent_id', details.agent_id ? String(details.agent_id) : '');

                const { data } = await api.post('/leads/upload/', formData, {
                    headers: { 'Content-Type': 'multipart/form-data' },
                });
                createdCount += Number(data?.created_count || 0);
                existingCount += Number(data?.duplicate_existing_count || 0);
                invalidCount += Number(data?.invalid_count || 0);
            } else {
                const leads = parseManualLeads(manualLeadsText);
                if (!leads.length) throw new Error('Please provide at least one manual lead');
                const metadata = {
                    dialing_mode: dialingMode,
                    delay_between_calls: details.delay_between_calls,
                    max_retries: 0,
                    caller_id: details.caller_id,
                    description: details.description,
                    agent_id: details.agent_id || null,
                };
                const { data } = await api.post('/leads/manual/', {
                    campaign_id: campaignId,
                    campaign_name: details.name.trim(),
                    timezone: details.timezone,
                    metadata,
                    leads,
                });
                createdCount += Number(data?.created_count || 0);
                existingCount += Number(data?.duplicate_existing_count || 0);
                invalidCount += Number(data?.invalid_count || 0);
            }

            setCreatedCampaign(campaign);
            setSubmitResult({ createdCount, existingCount, invalidCount });
            toast.success(`Campaign created: ${createdCount} leads attached to queue`);
            setActiveStep(3);
        } catch (error) {
            toast.error(error?.response?.data?.error || error?.response?.data?.detail || error.message || 'Failed to create campaign');
        } finally {
            setSubmitting(false);
        }
    };

    const handleStartCampaign = async () => {
        if (!createdCampaign?.id) return;
        try {
            await api.post(`/campaigns/${createdCampaign.id}/start/`);
            toast.success('Campaign started');
            navigate(`/campaigns/${createdCampaign.id}`);
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to start campaign');
        }
    };

    return (
        <Box>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
                <Button startIcon={<ArrowBack />} onClick={() => navigate('/campaigns')} sx={{ color: '#64748b' }}>
                    Back
                </Button>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Create Campaign</Typography>
                    <Typography color="text.secondary" variant="body2">
                        Queue-based calling campaign setup
                    </Typography>
                </Box>
            </Box>

            <Card>
                <CardContent sx={{ p: 4 }}>
                    <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
                        {STEPS.map((label) => (
                            <Step key={label}><StepLabel>{label}</StepLabel></Step>
                        ))}
                    </Stepper>

                    <Box sx={{ minHeight: 360 }}>
                        {activeStep === 0 && <DialingModeStep mode={dialingMode} onChange={setDialingMode} />}
                        {activeStep === 1 && (
                            <CampaignDetailsStep
                                details={details}
                                onChange={setDetails}
                                agents={agents}
                                loadingAgents={loadingAgents}
                            />
                        )}
                        {activeStep === 2 && (
                            <AddContactsStep
                                inputMode={inputMode}
                                setInputMode={setInputMode}
                                csvFile={csvFile}
                                setCsvFile={setCsvFile}
                                manualLeadsText={manualLeadsText}
                                setManualLeadsText={setManualLeadsText}
                            />
                        )}
                        {activeStep === 3 && (
                            <ReviewStep
                                dialingMode={dialingMode}
                                details={details}
                                inputMode={inputMode}
                                csvFile={csvFile}
                                manualLeadsText={manualLeadsText}
                                submitResult={submitResult}
                                createdCampaign={createdCampaign}
                            />
                        )}
                    </Box>

                    <Divider sx={{ my: 3, borderColor: 'rgba(1,66,162,0.1)' }} />

                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                        <Button
                            disabled={activeStep === 0 || submitting}
                            onClick={() => setActiveStep((step) => Math.max(0, step - 1))}
                            startIcon={<ArrowBack />}
                            sx={{ color: '#94a3b8' }}
                        >
                            Back
                        </Button>

                        {activeStep < 2 ? (
                            <Button
                                variant="contained"
                                disabled={!canProceed() || submitting}
                                onClick={() => setActiveStep((step) => step + 1)}
                                endIcon={<ArrowForward />}
                                sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                            >
                                Next
                            </Button>
                        ) : activeStep === 2 ? (
                            <Button
                                variant="contained"
                                disabled={!canProceed() || submitting}
                                onClick={handleSubmit}
                                startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : <Check />}
                                sx={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
                            >
                                {submitting ? 'Creating…' : 'Create Campaign'}
                            </Button>
                        ) : (
                            <Box sx={{ display: 'flex', gap: 1 }}>
                                <Button
                                    variant="outlined"
                                    onClick={() => createdCampaign?.id && navigate(`/campaigns/${createdCampaign.id}`)}
                                    sx={{ borderColor: '#0142a2', color: '#1a5bc4' }}
                                    disabled={!createdCampaign?.id}
                                >
                                    Open Campaign
                                </Button>
                                <Button
                                    variant="contained"
                                    startIcon={<PlayArrow />}
                                    onClick={handleStartCampaign}
                                    sx={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
                                    disabled={!createdCampaign?.id}
                                >
                                    Start Queue
                                </Button>
                                <Button
                                    variant="contained"
                                    onClick={() => createdCampaign?.id && navigate(`/dial?campaign_id=${createdCampaign.id}`)}
                                    sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                                    disabled={!createdCampaign?.id}
                                >
                                    Open Dialer
                                </Button>
                            </Box>
                        )}
                    </Box>
                </CardContent>
            </Card>
        </Box>
    );
}
