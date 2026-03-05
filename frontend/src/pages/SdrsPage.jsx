import React, { useEffect, useMemo, useState } from 'react';
import {
    Alert,
    Box,
    Button,
    Card,
    CardContent,
    Chip,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    Grid,
    IconButton,
    InputLabel,
    MenuItem,
    Select,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Tooltip,
    Typography,
} from '@mui/material';
import {
    Add,
    DeleteOutline,
    Edit,
    Refresh,
} from '@mui/icons-material';
import api from '../services/api';
import toast from 'react-hot-toast';

const STATUS_OPTIONS = ['available', 'ringing', 'busy', 'wrap_up', 'offline'];

const STATUS_COLORS = {
    available: { bg: '#10b98125', text: '#10b981' },
    ringing: { bg: '#3b82f625', text: '#3b82f6' },
    busy: { bg: '#f59e0b25', text: '#f59e0b' },
    wrap_up: { bg: '#8b5cf625', text: '#8b5cf6' },
    offline: { bg: '#64748b25', text: '#94a3b8' },
};

const EMPTY_FORM = {
    display_name: '',
    username: '',
    email: '',
    status: 'offline',
    password: '',
};

function SdrDialog({
    open,
    title,
    saving,
    form,
    onChange,
    onClose,
    onSubmit,
    includePassword = true,
}) {
    return (
        <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
            <DialogTitle>{title}</DialogTitle>
            <DialogContent>
                <Grid container spacing={2} sx={{ mt: 0.5 }}>
                    <Grid item xs={12} sm={6}>
                        <TextField
                            label="SDR Name"
                            value={form.display_name}
                            onChange={(e) => onChange('display_name', e.target.value)}
                            fullWidth
                            required
                        />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                        <FormControl fullWidth>
                            <InputLabel>Status</InputLabel>
                            <Select
                                label="Status"
                                value={form.status}
                                onChange={(e) => onChange('status', e.target.value)}
                            >
                                {STATUS_OPTIONS.map((status) => (
                                    <MenuItem key={status} value={status}>{status}</MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                    </Grid>
                    <Grid item xs={12} sm={6}>
                        <TextField
                            label="Username"
                            value={form.username}
                            onChange={(e) => onChange('username', e.target.value)}
                            fullWidth
                            helperText="Optional. Auto-generated if empty."
                        />
                    </Grid>
                    <Grid item xs={12} sm={6}>
                        <TextField
                            label="Email"
                            type="email"
                            value={form.email}
                            onChange={(e) => onChange('email', e.target.value)}
                            fullWidth
                        />
                    </Grid>
                    {includePassword && (
                        <Grid item xs={12}>
                            <TextField
                                label="Password"
                                type="password"
                                value={form.password}
                                onChange={(e) => onChange('password', e.target.value)}
                                fullWidth
                                helperText="Optional. Leave empty to create/update without login password."
                            />
                        </Grid>
                    )}
                </Grid>
            </DialogContent>
            <DialogActions>
                <Button onClick={onClose} disabled={saving}>Cancel</Button>
                <Button onClick={onSubmit} variant="contained" disabled={saving}>
                    {saving ? 'Saving...' : 'Save'}
                </Button>
            </DialogActions>
        </Dialog>
    );
}

export default function SdrsPage() {
    const [sdrs, setSdrs] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    const [createOpen, setCreateOpen] = useState(false);
    const [editOpen, setEditOpen] = useState(false);
    const [createForm, setCreateForm] = useState(EMPTY_FORM);
    const [editForm, setEditForm] = useState(EMPTY_FORM);
    const [editingSdr, setEditingSdr] = useState(null);

    const [saving, setSaving] = useState(false);
    const [deletingId, setDeletingId] = useState(null);

    const stats = useMemo(() => {
        const available = sdrs.filter((sdr) => sdr.status === 'available').length;
        const busy = sdrs.filter((sdr) => sdr.status === 'busy').length;
        return {
            total: sdrs.length,
            available,
            busy,
        };
    }, [sdrs]);

    const fetchSdrs = async ({ silent = false } = {}) => {
        if (!silent) {
            setLoading(true);
        }
        try {
            const { data } = await api.get('/agents/');
            setSdrs(Array.isArray(data?.agents) ? data.agents : []);
            setError('');
        } catch (e) {
            setError(e?.response?.data?.error || 'Failed to load SDRs');
            if (!silent) {
                toast.error(e?.response?.data?.error || 'Failed to load SDRs');
            }
        } finally {
            if (!silent) {
                setLoading(false);
            }
        }
    };

    useEffect(() => {
        fetchSdrs();
    }, []);

    const onCreateChange = (field, value) => {
        setCreateForm((prev) => ({ ...prev, [field]: value }));
    };

    const onEditChange = (field, value) => {
        setEditForm((prev) => ({ ...prev, [field]: value }));
    };

    const handleCreate = async () => {
        if (!createForm.display_name.trim()) {
            toast.error('SDR name is required');
            return;
        }

        setSaving(true);
        try {
            await api.post('/agents/create/', createForm);
            toast.success('SDR created');
            setCreateOpen(false);
            setCreateForm(EMPTY_FORM);
            fetchSdrs({ silent: true });
        } catch (e) {
            toast.error(e?.response?.data?.error || 'Failed to create SDR');
        } finally {
            setSaving(false);
        }
    };

    const openEdit = (sdr) => {
        setEditingSdr(sdr);
        setEditForm({
            display_name: sdr.display_name || '',
            username: sdr.username || '',
            email: sdr.email || '',
            status: sdr.status || 'offline',
            password: '',
        });
        setEditOpen(true);
    };

    const handleEdit = async () => {
        if (!editingSdr) return;
        if (!editForm.display_name.trim()) {
            toast.error('SDR name is required');
            return;
        }

        setSaving(true);
        try {
            await api.post(`/agents/${editingSdr.id}/update/`, editForm);
            toast.success('SDR updated');
            setEditOpen(false);
            setEditingSdr(null);
            fetchSdrs({ silent: true });
        } catch (e) {
            toast.error(e?.response?.data?.error || 'Failed to update SDR');
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (sdr) => {
        const ok = window.confirm(`Delete SDR "${sdr.display_name}"?`);
        if (!ok) return;

        setDeletingId(sdr.id);
        try {
            await api.post(`/agents/${sdr.id}/delete/`);
            toast.success('SDR deleted');
            fetchSdrs({ silent: true });
        } catch (e) {
            const code = e?.response?.data?.error;
            if (code === 'agent_call_in_progress') {
                toast.error('Cannot delete while SDR has an active call');
            } else {
                toast.error(code || 'Failed to delete SDR');
            }
        } finally {
            setDeletingId(null);
        }
    };

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3, gap: 1, flexWrap: 'wrap' }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>SDRs</Typography>
                    <Typography color="text.secondary" variant="body2">Create and manage SDR users for dialing campaigns</Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button variant="outlined" startIcon={<Refresh />} onClick={() => fetchSdrs()}>
                        Refresh
                    </Button>
                    <Button variant="contained" startIcon={<Add />} onClick={() => setCreateOpen(true)}>
                        Create SDR
                    </Button>
                </Box>
            </Box>

            <Grid container spacing={2} sx={{ mb: 2 }}>
                <Grid item xs={12} sm={4}>
                    <Card><CardContent>
                        <Typography color="text.secondary" variant="body2">Total SDRs</Typography>
                        <Typography variant="h5" fontWeight={700}>{stats.total}</Typography>
                    </CardContent></Card>
                </Grid>
                <Grid item xs={12} sm={4}>
                    <Card><CardContent>
                        <Typography color="text.secondary" variant="body2">Available</Typography>
                        <Typography variant="h5" fontWeight={700} color="#10b981">{stats.available}</Typography>
                    </CardContent></Card>
                </Grid>
                <Grid item xs={12} sm={4}>
                    <Card><CardContent>
                        <Typography color="text.secondary" variant="body2">Busy</Typography>
                        <Typography variant="h5" fontWeight={700} color="#f59e0b">{stats.busy}</Typography>
                    </CardContent></Card>
                </Grid>
            </Grid>

            {error ? <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert> : null}

            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Name</TableCell>
                                <TableCell>Username</TableCell>
                                <TableCell>Email</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell align="right">Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {!loading && sdrs.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={5} align="center" sx={{ py: 4, color: '#64748b' }}>
                                        No SDRs found. Create your first SDR.
                                    </TableCell>
                                </TableRow>
                            ) : (
                                sdrs.map((sdr) => {
                                    const colorCfg = STATUS_COLORS[sdr.status] || STATUS_COLORS.offline;
                                    return (
                                        <TableRow key={sdr.id} hover>
                                            <TableCell>
                                                <Typography fontWeight={600}>{sdr.display_name}</Typography>
                                            </TableCell>
                                            <TableCell>
                                                <Typography fontSize="0.85rem" color="text.secondary">{sdr.username || '—'}</Typography>
                                            </TableCell>
                                            <TableCell>
                                                <Typography fontSize="0.85rem" color="text.secondary">{sdr.email || '—'}</Typography>
                                            </TableCell>
                                            <TableCell>
                                                <Chip
                                                    label={sdr.status}
                                                    size="small"
                                                    sx={{ bgcolor: colorCfg.bg, color: colorCfg.text }}
                                                />
                                            </TableCell>
                                            <TableCell align="right">
                                                <Tooltip title="Edit SDR">
                                                    <span>
                                                        <IconButton size="small" onClick={() => openEdit(sdr)}>
                                                            <Edit fontSize="small" />
                                                        </IconButton>
                                                    </span>
                                                </Tooltip>
                                                <Tooltip title="Delete SDR">
                                                    <span>
                                                        <IconButton
                                                            size="small"
                                                            color="error"
                                                            onClick={() => handleDelete(sdr)}
                                                            disabled={deletingId === sdr.id}
                                                        >
                                                            <DeleteOutline fontSize="small" />
                                                        </IconButton>
                                                    </span>
                                                </Tooltip>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })
                            )}
                        </TableBody>
                    </Table>
                </TableContainer>
            </Card>

            <SdrDialog
                open={createOpen}
                title="Create SDR"
                form={createForm}
                saving={saving}
                onChange={onCreateChange}
                onClose={() => {
                    setCreateOpen(false);
                    setCreateForm(EMPTY_FORM);
                }}
                onSubmit={handleCreate}
                includePassword
            />

            <SdrDialog
                open={editOpen}
                title="Edit SDR"
                form={editForm}
                saving={saving}
                onChange={onEditChange}
                onClose={() => {
                    setEditOpen(false);
                    setEditingSdr(null);
                }}
                onSubmit={handleEdit}
                includePassword
            />
        </Box>
    );
}
