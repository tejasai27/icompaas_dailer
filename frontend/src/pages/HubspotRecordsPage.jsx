import React, { useEffect, useState } from 'react';
import {
    Box,
    Button,
    Card,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    FormControl,
    Grid,
    InputAdornment,
    InputLabel,
    MenuItem,
    Pagination,
    Select,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TextField,
    Typography,
    Chip,
} from '@mui/material';
import { Refresh, Search } from '@mui/icons-material';
import toast from 'react-hot-toast';
import api from '../services/api';

const STATUS_COLORS = {
    success: { bg: 'rgba(16,185,129,0.15)', color: '#10b981' },
    failed: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444' },
    pending: { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b' },
};

const PAGE_SIZE = 20;

function _prettyJson(value) {
    try {
        return JSON.stringify(value || {}, null, 2);
    } catch {
        return '{}';
    }
}

export default function HubspotRecordsPage() {
    const [records, setRecords] = useState([]);
    const [loading, setLoading] = useState(true);
    const [page, setPage] = useState(1);
    const [totalPages, setTotalPages] = useState(1);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('success');
    const [selected, setSelected] = useState(null);

    const fetchRecords = async () => {
        setLoading(true);
        try {
            const params = {
                page,
                page_size: PAGE_SIZE,
                include_payload: 1,
            };
            if (statusFilter) params.status = statusFilter;
            if (search) params.search = search;

            const { data } = await api.get('/integrations/hubspot/records/', { params });
            const rows = Array.isArray(data?.results) ? data.results : [];
            const count = Number(data?.count || rows.length || 0);
            setRecords(rows);
            setTotalPages(Math.max(1, Math.ceil(count / PAGE_SIZE)));
        } catch (error) {
            toast.error(error?.response?.data?.error || 'Failed to load HubSpot records');
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchRecords();
    }, [page, statusFilter, search]);

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>HubSpot Records</Typography>
                    <Typography color="text.secondary" variant="body2">
                        Logs of call and task records synced to HubSpot
                    </Typography>
                </Box>
                <Button
                    variant="outlined"
                    startIcon={<Refresh />}
                    disabled={loading}
                    onClick={() => fetchRecords()}
                >
                    Refresh
                </Button>
            </Box>

            <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                <TextField
                    size="small"
                    placeholder="Search contact, phone, campaign, error..."
                    value={search}
                    onChange={(event) => {
                        setPage(1);
                        setSearch(event.target.value);
                    }}
                    sx={{ width: 340 }}
                    InputProps={{
                        startAdornment: (
                            <InputAdornment position="start">
                                <Search sx={{ color: '#64748b', fontSize: 18 }} />
                            </InputAdornment>
                        ),
                    }}
                />
                <FormControl size="small" sx={{ width: 180 }}>
                    <InputLabel>Status</InputLabel>
                    <Select
                        value={statusFilter}
                        label="Status"
                        onChange={(event) => {
                            setPage(1);
                            setStatusFilter(event.target.value);
                        }}
                    >
                        <MenuItem value="">All</MenuItem>
                        <MenuItem value="success">Success</MenuItem>
                        <MenuItem value="failed">Failed</MenuItem>
                        <MenuItem value="pending">Pending</MenuItem>
                    </Select>
                </FormControl>
            </Box>

            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Time</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Reason</TableCell>
                                <TableCell>Contact</TableCell>
                                <TableCell>Campaign</TableCell>
                                <TableCell>Deal</TableCell>
                                <TableCell>HubSpot IDs</TableCell>
                                <TableCell>Error</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {records.length === 0 && (
                                <TableRow>
                                    <TableCell colSpan={8}>
                                        <Typography color="text.secondary" sx={{ py: 1.5 }}>
                                            {loading ? 'Loading HubSpot records...' : 'No HubSpot records found'}
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            )}
                            {records.map((row) => {
                                const color = STATUS_COLORS[row.status] || { bg: 'rgba(100,116,139,0.2)', color: '#94a3b8' };
                                return (
                                    <TableRow
                                        key={row.id}
                                        hover
                                        sx={{ cursor: 'pointer' }}
                                        onClick={() => setSelected(row)}
                                    >
                                        <TableCell>
                                            <Typography fontSize="0.78rem" color="text.secondary">
                                                {row.created_at ? new Date(row.created_at).toLocaleString() : '-'}
                                            </Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Chip
                                                size="small"
                                                label={row.status || '-'}
                                                sx={{ bgcolor: color.bg, color: color.color }}
                                            />
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.82rem">{row.reason || row.action || '-'}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.82rem" fontWeight={600}>{row.contact_name || '-'}</Typography>
                                            <Typography fontSize="0.75rem" color="text.secondary" fontFamily="monospace">
                                                {row.contact_phone || '-'}
                                            </Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.82rem">{row.campaign_name || '-'}</Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.78rem" fontFamily="monospace">
                                                {row.deal_id || '-'}
                                            </Typography>
                                            <Typography fontSize="0.75rem" color="text.secondary">
                                                {row.deal_name || '-'}
                                            </Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography fontSize="0.78rem" fontFamily="monospace">
                                                Call: {row.hubspot_call_id || '-'}
                                            </Typography>
                                            <Typography fontSize="0.78rem" fontFamily="monospace">
                                                Task: {row.hubspot_task_id || '-'}
                                            </Typography>
                                        </TableCell>
                                        <TableCell>
                                            <Typography
                                                fontSize="0.78rem"
                                                color={row.error_message ? '#ef4444' : 'text.secondary'}
                                                sx={{ maxWidth: 280 }}
                                                noWrap
                                            >
                                                {row.error_message || '-'}
                                            </Typography>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </TableContainer>
                {totalPages > 1 && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                        <Pagination count={totalPages} page={page} onChange={(_, value) => setPage(value)} />
                    </Box>
                )}
            </Card>

            {selected && (
                <Dialog open onClose={() => setSelected(null)} maxWidth="lg" fullWidth>
                    <DialogTitle>HubSpot Sync Record #{selected.id}</DialogTitle>
                    <DialogContent dividers>
                        <Grid container spacing={2} sx={{ mb: 2 }}>
                            {[
                                { label: 'Status', value: selected.status || '-' },
                                { label: 'Reason', value: selected.reason || '-' },
                                { label: 'Action', value: selected.action || '-' },
                                { label: 'Task Action', value: selected.task_action || '-' },
                                { label: 'Contact', value: selected.contact_name || '-' },
                                { label: 'Phone', value: selected.contact_phone || '-' },
                                { label: 'Campaign', value: selected.campaign_name || '-' },
                                { label: 'Deal ID', value: selected.deal_id || '-' },
                                { label: 'Deal Name', value: selected.deal_name || '-' },
                                { label: 'HubSpot Call ID', value: selected.hubspot_call_id || '-' },
                                { label: 'HubSpot Task ID', value: selected.hubspot_task_id || '-' },
                                { label: 'Error', value: selected.error_message || '-' },
                            ].map((item) => (
                                <Grid item xs={12} md={6} key={item.label}>
                                    <Typography variant="caption" color="text.secondary">{item.label}</Typography>
                                    <Typography fontSize="0.9rem" sx={{ wordBreak: 'break-word' }}>{item.value}</Typography>
                                </Grid>
                            ))}
                        </Grid>

                        <Typography variant="subtitle2" sx={{ mb: 1 }}>Request Payload</Typography>
                        <Box sx={{ p: 1.5, borderRadius: 1, bgcolor: '#0b1220', color: '#e2e8f0', mb: 2, overflowX: 'auto' }}>
                            <Typography component="pre" sx={{ m: 0, fontSize: '0.75rem', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                                {_prettyJson(selected.request_payload)}
                            </Typography>
                        </Box>

                        <Typography variant="subtitle2" sx={{ mb: 1 }}>Response Payload</Typography>
                        <Box sx={{ p: 1.5, borderRadius: 1, bgcolor: '#0b1220', color: '#e2e8f0', overflowX: 'auto' }}>
                            <Typography component="pre" sx={{ m: 0, fontSize: '0.75rem', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                                {_prettyJson(selected.response_payload)}
                            </Typography>
                        </Box>
                    </DialogContent>
                    <DialogActions>
                        <Button onClick={() => setSelected(null)}>Close</Button>
                    </DialogActions>
                </Dialog>
            )}
        </Box>
    );
}
