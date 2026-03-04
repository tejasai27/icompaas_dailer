import React, { useState, useEffect, useCallback } from 'react';
import {
    Box, Card, CardContent, Typography, Button, Stepper,
    Step, StepLabel, TextField, Select, MenuItem, FormControl,
    InputLabel, Grid, Chip, FormHelperText, CircularProgress,
    Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
    Alert, Divider, LinearProgress
} from '@mui/material';
import {
    ArrowBack, ArrowForward, Check, Upload, CloudUpload,
    Phone, Settings, Person, FlashOn
} from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import { useDropzone } from 'react-dropzone';
import api from '../services/api';
import toast from 'react-hot-toast';

const STEPS = ['Dialing Mode', 'Upload Contacts', 'Map Fields', 'Campaign Settings'];

// Step 1: Dialing Mode
function DialingModeStep({ mode, onChange }) {
    const modes = [
        {
            id: 'power',
            icon: '⚡',
            title: 'Power Dialer',
            desc: 'Call one contact at a time sequentially. Agent is connected when contact answers.',
            features: ['Sequential calling', 'Agent-ready connection', 'Auto-retry on no-answer', 'Guaranteed agent presence'],
            recommended: true,
        },
        {
            id: 'dynamic',
            icon: '🔀',
            title: 'Dynamic Dialer',
            desc: 'Simultaneously dial multiple contacts. Connect the first to answer to the agent.',
            features: ['Multiple simultaneous calls', 'Higher call volume', 'Higher connect rate', 'Best for large lists'],
            recommended: false,
        },
    ];

    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Select Dialing Mode</Typography>
            <Typography color="text.secondary" variant="body2" mb={3}>
                Choose how contacts will be dialed in this campaign.
            </Typography>
            <Grid container spacing={2}>
                {modes.map((m) => (
                    <Grid item xs={12} md={6} key={m.id}>
                        <Box
                            onClick={() => onChange(m.id)}
                            sx={{
                                p: 3, borderRadius: 3, cursor: 'pointer',
                                border: `2px solid ${mode === m.id ? '#6366f1' : 'rgba(99,102,241,0.15)'}`,
                                bgcolor: mode === m.id ? 'rgba(99,102,241,0.1)' : 'rgba(255,255,255,0.02)',
                                transition: 'all 0.2s',
                                position: 'relative',
                                '&:hover': { border: '2px solid rgba(99,102,241,0.4)' },
                            }}
                        >
                            {m.recommended && (
                                <Chip label="Recommended" size="small"
                                    sx={{ position: 'absolute', top: 12, right: 12, bgcolor: '#10b98125', color: '#10b981', fontSize: '0.65rem' }} />
                            )}
                            <Typography fontSize="2rem" mb={1}>{m.icon}</Typography>
                            <Typography variant="h6" fontWeight={600} mb={0.5}>{m.title}</Typography>
                            <Typography variant="body2" color="text.secondary" mb={2}>{m.desc}</Typography>
                            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
                                {m.features.map(f => (
                                    <Box key={f} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Check sx={{ fontSize: 14, color: mode === m.id ? '#6366f1' : '#475569' }} />
                                        <Typography variant="caption" color={mode === m.id ? 'text.primary' : 'text.secondary'}>{f}</Typography>
                                    </Box>
                                ))}
                            </Box>
                        </Box>
                    </Grid>
                ))}
            </Grid>
        </Box>
    );
}

// Step 2: CSV Upload
function CSVUploadStep({ campaignId, onUploadComplete }) {
    const [uploading, setUploading] = useState(false);
    const [uploadResult, setUploadResult] = useState(null);

    const onDrop = useCallback(async (acceptedFiles) => {
        const file = acceptedFiles[0];
        if (!file) return;

        setUploading(true);
        const formData = new FormData();
        formData.append('file', file);
        formData.append('campaign_id', campaignId);

        try {
            const { data } = await api.post('/contacts/upload_csv/', formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            setUploadResult(data);
            onUploadComplete(data);
            toast.success(`CSV uploaded: ${data.headers.length} columns detected`);
        } catch (e) {
            toast.error(e.response?.data?.error || 'Upload failed');
        } finally {
            setUploading(false);
        }
    }, [campaignId, onUploadComplete]);

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: { 'text/csv': ['.csv'] },
        maxFiles: 1,
    });

    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Upload Contact List</Typography>
            <Typography color="text.secondary" variant="body2" mb={3}>
                Upload a CSV file containing your contacts. Required column: <strong>phone</strong>
            </Typography>

            {!uploadResult ? (
                <Box
                    {...getRootProps()}
                    sx={{
                        border: `2px dashed ${isDragActive ? '#6366f1' : 'rgba(99,102,241,0.3)'}`,
                        borderRadius: 3,
                        p: 6,
                        textAlign: 'center',
                        cursor: 'pointer',
                        bgcolor: isDragActive ? 'rgba(99,102,241,0.08)' : 'rgba(99,102,241,0.03)',
                        transition: 'all 0.2s',
                        '&:hover': { borderColor: '#6366f1', bgcolor: 'rgba(99,102,241,0.08)' },
                    }}
                >
                    <input {...getInputProps()} />
                    {uploading ? (
                        <CircularProgress sx={{ color: '#6366f1' }} />
                    ) : (
                        <>
                            <CloudUpload sx={{ fontSize: 56, color: '#4f46e5', mb: 2 }} />
                            <Typography variant="h6" fontWeight={600} mb={1}>
                                {isDragActive ? 'Drop your CSV here' : 'Drag & drop CSV file here'}
                            </Typography>
                            <Typography color="text.secondary" variant="body2" mb={2}>
                                or click to browse files
                            </Typography>
                            <Chip label="CSV files only" size="small"
                                sx={{ bgcolor: 'rgba(99,102,241,0.15)', color: '#818cf8' }} />
                        </>
                    )}
                </Box>
            ) : (
                <Box>
                    <Alert severity="success" sx={{ mb: 2, bgcolor: 'rgba(16,185,129,0.1)' }}>
                        ✅ CSV uploaded successfully! {uploadResult.preview_rows?.length} sample rows loaded.
                    </Alert>

                    <Typography variant="subtitle2" fontWeight={600} mb={1.5}>Detected Columns ({uploadResult.headers?.length})</Typography>
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mb: 3 }}>
                        {uploadResult.headers?.map(h => (
                            <Chip key={h} label={h} size="small"
                                sx={{ bgcolor: 'rgba(99,102,241,0.15)', color: '#818cf8' }} />
                        ))}
                    </Box>

                    <Typography variant="subtitle2" fontWeight={600} mb={1.5}>Preview (first 5 rows)</Typography>
                    <TableContainer sx={{ borderRadius: 2, border: '1px solid rgba(99,102,241,0.15)' }}>
                        <Table size="small">
                            <TableHead>
                                <TableRow>
                                    {uploadResult.headers?.map(h => <TableCell key={h}>{h}</TableCell>)}
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {uploadResult.preview_rows?.map((row, i) => (
                                    <TableRow key={i}>
                                        {uploadResult.headers?.map(h => (
                                            <TableCell key={h} sx={{ fontSize: '0.8rem' }}>{row[h] || '-'}</TableCell>
                                        ))}
                                    </TableRow>
                                ))}
                            </TableBody>
                        </Table>
                    </TableContainer>

                    <Button variant="text" sx={{ mt: 2, color: '#6366f1' }}
                        onClick={() => { setUploadResult(null); onUploadComplete(null); }}>
                        Upload different file
                    </Button>
                </Box>
            )}

            <Alert severity="info" sx={{ mt: 2, bgcolor: 'rgba(59,130,246,0.1)' }}>
                <Typography variant="caption">
                    <strong>Supported columns:</strong> name, phone, email, company, notes, and any custom fields
                </Typography>
            </Alert>
        </Box>
    );
}

// Step 3: Field Mapping
function FieldMappingStep({ uploadData, mapping, onChange }) {
    const contactFields = [
        { key: 'name', label: 'Contact Name', required: false },
        { key: 'phone', label: 'Phone Number', required: true },
        { key: 'email', label: 'Email Address', required: false },
        { key: 'company', label: 'Company', required: false },
        { key: 'notes', label: 'Notes', required: false },
    ];

    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Map CSV Columns</Typography>
            <Typography color="text.secondary" variant="body2" mb={3}>
                Tell us which CSV column maps to each contact field.
            </Typography>

            {uploadData?.suggested_mapping && (
                <Alert severity="success" sx={{ mb: 3, bgcolor: 'rgba(16,185,129,0.1)' }}>
                    We auto-detected {Object.keys(uploadData.suggested_mapping).length} field mappings. Review and adjust as needed.
                </Alert>
            )}

            <Grid container spacing={2}>
                {contactFields.map(field => (
                    <Grid item xs={12} sm={6} key={field.key}>
                        <FormControl fullWidth size="small">
                            <InputLabel>{field.label}{field.required ? ' *' : ''}</InputLabel>
                            <Select
                                value={mapping[field.key] || ''}
                                label={`${field.label}${field.required ? ' *' : ''}`}
                                onChange={e => onChange({ ...mapping, [field.key]: e.target.value })}
                            >
                                <MenuItem value=""><em>— Skip —</em></MenuItem>
                                {uploadData?.headers?.map(h => (
                                    <MenuItem key={h} value={h}>{h}</MenuItem>
                                ))}
                            </Select>
                            {field.required && !mapping[field.key] && (
                                <FormHelperText error>This field is required</FormHelperText>
                            )}
                        </FormControl>
                    </Grid>
                ))}
            </Grid>

            <Divider sx={{ my: 3, borderColor: 'rgba(99,102,241,0.1)' }} />

            <Typography variant="subtitle2" fontWeight={600} mb={1.5}>Mapping Preview</Typography>
            <TableContainer sx={{ borderRadius: 2, border: '1px solid rgba(99,102,241,0.15)' }}>
                <Table size="small">
                    <TableHead>
                        <TableRow>
                            <TableCell>Contact Field</TableCell>
                            <TableCell>CSV Column</TableCell>
                            <TableCell>Sample Data</TableCell>
                        </TableRow>
                    </TableHead>
                    <TableBody>
                        {contactFields.map(field => {
                            const csvCol = mapping[field.key];
                            const sample = csvCol && uploadData?.preview_rows?.[0]?.[csvCol];
                            return (
                                <TableRow key={field.key}>
                                    <TableCell>
                                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                            <Typography fontSize="0.875rem" fontWeight={500}>{field.label}</Typography>
                                            {field.required && <Chip label="required" size="small"
                                                sx={{ height: 16, fontSize: '0.65rem', bgcolor: 'rgba(239,68,68,0.15)', color: '#ef4444' }} />}
                                        </Box>
                                    </TableCell>
                                    <TableCell>
                                        {csvCol ? (
                                            <Chip label={csvCol} size="small"
                                                sx={{ bgcolor: 'rgba(99,102,241,0.15)', color: '#818cf8' }} />
                                        ) : <Typography color="text.disabled" fontSize="0.875rem">Not mapped</Typography>}
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.8rem" color="text.secondary">{sample || '—'}</Typography>
                                    </TableCell>
                                </TableRow>
                            );
                        })}
                    </TableBody>
                </Table>
            </TableContainer>
        </Box>
    );
}

// Step 4: Campaign Settings
function CampaignSettingsStep({ settings, onChange, agents }) {
    return (
        <Box>
            <Typography variant="h6" fontWeight={600} mb={1}>Campaign Settings</Typography>
            <Typography color="text.secondary" variant="body2" mb={3}>
                Configure agent assignment and dialing behavior.
            </Typography>

            <Grid container spacing={3}>
                <Grid item xs={12} sm={6}>
                    <TextField
                        fullWidth
                        label="Campaign Name *"
                        value={settings.name}
                        onChange={e => onChange({ ...settings, name: e.target.value })}
                        placeholder="e.g. Q1 Sales Outreach"
                    />
                </Grid>
                <Grid item xs={12} sm={6}>
                    <FormControl fullWidth>
                        <InputLabel>Assigned Agent *</InputLabel>
                        <Select
                            value={settings.agent}
                            label="Assigned Agent *"
                            onChange={e => onChange({ ...settings, agent: e.target.value })}
                        >
                            <MenuItem value=""><em>Select agent…</em></MenuItem>
                            {agents.map(a => (
                                <MenuItem key={a.id} value={a.id}>
                                    {a.full_name} {a.is_available ? '🟢' : '🔴'}
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>
                </Grid>
                <Grid item xs={12} sm={6}>
                    <TextField
                        fullWidth
                        type="number"
                        label="Delay Between Calls (seconds)"
                        value={settings.delay_between_calls}
                        onChange={e => onChange({ ...settings, delay_between_calls: parseInt(e.target.value) })}
                        inputProps={{ min: 5, max: 300 }}
                        helperText="Time to wait before dialing next contact"
                    />
                </Grid>
                <Grid item xs={12} sm={6}>
                    <TextField
                        fullWidth
                        type="number"
                        label="Retry Time (minutes)"
                        value={settings.retry_time}
                        onChange={e => onChange({ ...settings, retry_time: parseInt(e.target.value) })}
                        inputProps={{ min: 5, max: 1440 }}
                        helperText="Minutes to wait before retrying failed calls"
                    />
                </Grid>
                <Grid item xs={12} sm={6}>
                    <TextField
                        fullWidth
                        type="number"
                        label="Max Retries per Contact"
                        value={settings.max_retries}
                        onChange={e => onChange({ ...settings, max_retries: parseInt(e.target.value) })}
                        inputProps={{ min: 0, max: 10 }}
                    />
                </Grid>
                <Grid item xs={12} sm={6}>
                    <TextField
                        fullWidth
                        label="Caller ID (optional)"
                        value={settings.caller_id}
                        onChange={e => onChange({ ...settings, caller_id: e.target.value })}
                        placeholder="+1234567890"
                        helperText="Override caller ID for this campaign"
                    />
                </Grid>
                <Grid item xs={12}>
                    <TextField
                        fullWidth
                        multiline
                        rows={3}
                        label="Description (optional)"
                        value={settings.description}
                        onChange={e => onChange({ ...settings, description: e.target.value })}
                        placeholder="Campaign objectives and notes…"
                    />
                </Grid>
            </Grid>
        </Box>
    );
}

// Main wizard
export default function CampaignCreatePage() {
    const [activeStep, setActiveStep] = useState(0);
    const [dialingMode, setDialingMode] = useState('power');
    const [uploadData, setUploadData] = useState(null);
    const [tempCampaignId, setTempCampaignId] = useState(null);
    const [fieldMapping, setFieldMapping] = useState({});
    const [agents, setAgents] = useState([]);
    const [settings, setSettings] = useState({
        name: '', agent: '', delay_between_calls: 15,
        retry_time: 60, max_retries: 3, caller_id: '', description: '',
    });
    const [submitting, setSubmitting] = useState(false);
    const navigate = useNavigate();

    useEffect(() => {
        api.get('/auth/users/agents/').then(r => setAgents(r.data));
        // Create a temp draft campaign to use for CSV upload
        api.post('/campaigns/', {
            name: `Draft-${Date.now()}`, dialing_mode: 'power',
            delay_between_calls: 15, retry_time: 60, max_retries: 3,
        }).then(r => setTempCampaignId(r.data.id));
    }, []);

    useEffect(() => {
        if (uploadData?.suggested_mapping) {
            setFieldMapping(uploadData.suggested_mapping);
        }
    }, [uploadData]);

    const canProceed = () => {
        if (activeStep === 1 && !uploadData) return false;
        if (activeStep === 2 && !fieldMapping.phone) return false;
        if (activeStep === 3 && (!settings.name || !settings.agent)) return false;
        return true;
    };

    const handleNext = () => {
        if (activeStep === 2 && uploadData && fieldMapping.phone) {
            // Finalize import
            api.post('/contacts/import_csv/', {
                upload_id: uploadData.upload_id,
                field_mapping: fieldMapping,
            }).catch(e => toast.error('Import warning: ' + (e.response?.data?.error || e.message)));
        }
        setActiveStep(s => s + 1);
    };

    const handleFinish = async () => {
        if (!settings.name || !settings.agent) {
            toast.error('Campaign name and agent are required');
            return;
        }
        setSubmitting(true);
        try {
            await api.patch(`/campaigns/${tempCampaignId}/`, {
                name: settings.name,
                description: settings.description,
                dialing_mode: dialingMode,
                assigned_agent: settings.agent,
                delay_between_calls: settings.delay_between_calls,
                retry_time: settings.retry_time,
                max_retries: settings.max_retries,
                caller_id: settings.caller_id,
                status: 'draft',
            });
            toast.success('Campaign created successfully!');
            navigate(`/campaigns/${tempCampaignId}`);
        } catch (e) {
            toast.error(e.response?.data?.detail || 'Failed to create campaign');
        } finally {
            setSubmitting(false);
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
                    <Typography color="text.secondary" variant="body2">Set up your power dialing campaign</Typography>
                </Box>
            </Box>

            <Card>
                <CardContent sx={{ p: 4 }}>
                    <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
                        {STEPS.map((label) => (
                            <Step key={label}>
                                <StepLabel sx={{
                                    '& .MuiStepLabel-label': { color: '#94a3b8' },
                                    '& .MuiStepLabel-label.Mui-active': { color: '#f1f5f9' },
                                    '& .MuiStepLabel-label.Mui-completed': { color: '#6366f1' },
                                    '& .MuiStepIcon-root': { color: '#374151' },
                                    '& .MuiStepIcon-root.Mui-active': { color: '#6366f1' },
                                    '& .MuiStepIcon-root.Mui-completed': { color: '#10b981' },
                                }}>
                                    {label}
                                </StepLabel>
                            </Step>
                        ))}
                    </Stepper>

                    <Box sx={{ minHeight: 400 }}>
                        {activeStep === 0 && <DialingModeStep mode={dialingMode} onChange={setDialingMode} />}
                        {activeStep === 1 && tempCampaignId && (
                            <CSVUploadStep campaignId={tempCampaignId} onUploadComplete={setUploadData} />
                        )}
                        {activeStep === 2 && (
                            <FieldMappingStep uploadData={uploadData} mapping={fieldMapping} onChange={setFieldMapping} />
                        )}
                        {activeStep === 3 && (
                            <CampaignSettingsStep settings={settings} onChange={setSettings} agents={agents} />
                        )}
                    </Box>

                    <Divider sx={{ my: 3, borderColor: 'rgba(99,102,241,0.1)' }} />

                    <Box sx={{ display: 'flex', justifyContent: 'space-between' }}>
                        <Button
                            disabled={activeStep === 0}
                            onClick={() => setActiveStep(s => s - 1)}
                            startIcon={<ArrowBack />}
                            sx={{ color: '#94a3b8' }}
                        >
                            Back
                        </Button>

                        {activeStep < STEPS.length - 1 ? (
                            <Button
                                variant="contained"
                                onClick={handleNext}
                                disabled={!canProceed()}
                                endIcon={<ArrowForward />}
                                sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)' }}
                            >
                                Next
                            </Button>
                        ) : (
                            <Button
                                variant="contained"
                                onClick={handleFinish}
                                disabled={submitting || !canProceed()}
                                startIcon={submitting ? <CircularProgress size={16} color="inherit" /> : <Check />}
                                sx={{ background: 'linear-gradient(135deg, #10b981, #059669)' }}
                            >
                                {submitting ? 'Creating…' : 'Create Campaign'}
                            </Button>
                        )}
                    </Box>
                </CardContent>
            </Card>
        </Box>
    );
}
