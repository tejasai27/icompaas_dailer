import React, { useCallback, useEffect, useState } from 'react';
import {
    Box, Card, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Chip, InputAdornment, TextField, Pagination,
    Button, Dialog, DialogTitle, DialogContent, DialogActions, Grid
} from '@mui/material';
import { Add, Search } from '@mui/icons-material';
import { request } from '../lib/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
    pending: '#64748b', calling: '#3b82f6', answered: '#10b981',
    'no-answer': '#f59e0b', no_answer: '#f59e0b', busy: '#f59e0b', failed: '#ef4444', completed: '#6366f1'
};

export default function ContactsPage() {
    const [contacts, setContacts] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [count, setCount] = useState(0);
    const [createOpen, setCreateOpen] = useState(false);
    const [creating, setCreating] = useState(false);
    const [form, setForm] = useState({
        full_name: '',
        phone_e164: '',
        email: '',
        company_name: '',
    });

    const fetchContacts = useCallback(async () => {
        setLoading(true);
        try {
            let path = `/api/v1/dialer/leads/?page=${page}&page_size=20`;
            if (search.trim()) {
                path += `&search=${encodeURIComponent(search.trim())}`;
            }
            const data = await request(path);
            setContacts(Array.isArray(data.results) ? data.results : []);
            setCount(Number(data.count || 0));
        } catch (e) {
            toast.error(e.message || 'Failed to load contacts');
        } finally {
            setLoading(false);
        }
    }, [page, search]);

    useEffect(() => {
        fetchContacts();
    }, [fetchContacts]);

    async function handleCreateContact() {
        const fullName = form.full_name.trim();
        const phone = form.phone_e164.trim();
        if (!fullName || !phone) {
            toast.error('Name and phone are required');
            return;
        }

        setCreating(true);
        try {
            await request('/api/v1/dialer/leads/manual/', {
                method: 'POST',
                body: JSON.stringify({
                    full_name: fullName,
                    phone_e164: phone,
                    email: form.email.trim(),
                    company_name: form.company_name.trim(),
                }),
            });
            toast.success('Contact created');
            setCreateOpen(false);
            setForm({ full_name: '', phone_e164: '', email: '', company_name: '' });
            if (page !== 1) {
                setPage(1);
            } else {
                fetchContacts();
            }
        } catch (e) {
            toast.error(e.message || 'Failed to create contact');
        } finally {
            setCreating(false);
        }
    }

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Contacts</Typography>
                    <Typography color="text.secondary" variant="body2">{count} contacts across all campaigns</Typography>
                </Box>
                <Button
                    variant="contained"
                    startIcon={<Add />}
                    onClick={() => setCreateOpen(true)}
                    sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)' }}
                >
                    Create Contact
                </Button>
            </Box>

            <Box sx={{ mb: 3 }}>
                <TextField
                    placeholder="Search by name, phone, company…"
                    value={search}
                    onChange={e => { setSearch(e.target.value); setPage(1); }}
                    size="small"
                    InputProps={{
                        startAdornment: <InputAdornment position="start"><Search sx={{ color: '#64748b', fontSize: 18 }} /></InputAdornment>
                    }}
                    sx={{ width: 320 }}
                />
            </Box>

            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell>Name</TableCell>
                                <TableCell>Phone</TableCell>
                                <TableCell>Email</TableCell>
                                <TableCell>Company</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Retries</TableCell>
                                <TableCell>Last Called</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {loading ? (
                                <TableRow>
                                    <TableCell colSpan={7} align="center" sx={{ py: 4, color: '#94a3b8' }}>
                                        Loading contacts...
                                    </TableCell>
                                </TableRow>
                            ) : contacts.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={7} align="center" sx={{ py: 4, color: '#94a3b8' }}>
                                        No contacts found
                                    </TableCell>
                                </TableRow>
                            ) : null}
                            {contacts.map(c => (
                                <TableRow key={c.id} hover>
                                    <TableCell>
                                        <Typography fontWeight={500} fontSize="0.875rem">{c.name}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem" fontFamily="monospace">{c.phone}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem" color="text.secondary">{c.email || '—'}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem">{c.company || '—'}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Chip label={c.status} size="small"
                                            sx={{ bgcolor: `${STATUS_COLORS[c.status] || '#64748b'}25`, color: STATUS_COLORS[c.status] || '#94a3b8', fontSize: '0.7rem' }} />
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.875rem">{c.retry_count}</Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography fontSize="0.75rem" color="text.secondary">
                                            {c.last_called_at ? new Date(c.last_called_at).toLocaleString() : '—'}
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
                {count > 20 && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                        <Pagination count={Math.ceil(count / 20)} page={page} onChange={(_, v) => setPage(v)}
                            sx={{ '& .MuiPaginationItem-root': { color: '#94a3b8' }, '& .Mui-selected': { bgcolor: 'rgba(99,102,241,0.2)', color: '#818cf8' } }} />
                    </Box>
                )}
            </Card>

            <Dialog
                open={createOpen}
                onClose={() => !creating && setCreateOpen(false)}
                fullWidth
                maxWidth="sm"
                PaperProps={{ sx: { bgcolor: '#1a1a2e', border: '1px solid rgba(99,102,241,0.2)' } }}
            >
                <DialogTitle>Create Contact</DialogTitle>
                <DialogContent>
                    <Grid container spacing={2} sx={{ mt: 0.5 }}>
                        <Grid item xs={12}>
                            <TextField
                                fullWidth
                                required
                                label="Full Name"
                                value={form.full_name}
                                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                            />
                        </Grid>
                        <Grid item xs={12} sm={6}>
                            <TextField
                                fullWidth
                                required
                                label="Phone (E.164)"
                                placeholder="+9199XXXXXXXX"
                                value={form.phone_e164}
                                onChange={(e) => setForm({ ...form, phone_e164: e.target.value })}
                            />
                        </Grid>
                        <Grid item xs={12} sm={6}>
                            <TextField
                                fullWidth
                                label="Email"
                                value={form.email}
                                onChange={(e) => setForm({ ...form, email: e.target.value })}
                            />
                        </Grid>
                        <Grid item xs={12}>
                            <TextField
                                fullWidth
                                label="Company"
                                value={form.company_name}
                                onChange={(e) => setForm({ ...form, company_name: e.target.value })}
                            />
                        </Grid>
                    </Grid>
                </DialogContent>
                <DialogActions sx={{ px: 3, pb: 2 }}>
                    <Button onClick={() => setCreateOpen(false)} disabled={creating}>
                        Cancel
                    </Button>
                    <Button
                        variant="contained"
                        onClick={handleCreateContact}
                        disabled={creating}
                        sx={{ background: 'linear-gradient(135deg, #6366f1, #818cf8)' }}
                    >
                        {creating ? 'Creating...' : 'Create'}
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
