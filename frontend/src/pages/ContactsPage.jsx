import React, { useCallback, useEffect, useState } from 'react';
import {
    Box, Card, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Chip, InputAdornment, TextField, Pagination,
    Button, Dialog, DialogTitle, DialogContent, DialogActions, Grid, IconButton, Tooltip, Checkbox
} from '@mui/material';
import { Add, Search, Edit, DeleteOutline } from '@mui/icons-material';
import { request } from '../lib/api';
import toast from 'react-hot-toast';

const STATUS_COLORS = {
    pending: '#64748b', calling: '#3b82f6', answered: '#10b981',
    'no-answer': '#f59e0b', no_answer: '#f59e0b', busy: '#f59e0b', failed: '#ef4444', completed: '#0142a2'
};
const PAGE_SIZE = 20;

export default function ContactsPage() {
    const [contacts, setContacts] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const [page, setPage] = useState(1);
    const [count, setCount] = useState(0);
    const [createOpen, setCreateOpen] = useState(false);
    const [creating, setCreating] = useState(false);
    const [editOpen, setEditOpen] = useState(false);
    const [updating, setUpdating] = useState(false);
    const [editingContact, setEditingContact] = useState(null);
    const [deletingId, setDeletingId] = useState(null);
    const [selectedIds, setSelectedIds] = useState([]);
    const [form, setForm] = useState({
        full_name: '',
        phone_e164: '',
        email: '',
        company_name: '',
    });
    const [editForm, setEditForm] = useState({
        full_name: '',
        phone_e164: '',
        email: '',
        company_name: '',
    });

    const fetchContacts = useCallback(async () => {
        setLoading(true);
        try {
            let path = `/api/v1/dialer/leads/?page=${page}&page_size=${PAGE_SIZE}`;
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

    useEffect(() => {
        setSelectedIds([]);
    }, [search]);

    function refreshAfterDelete(deletedCount = 0) {
        const safeDeleted = Math.max(0, Number(deletedCount || 0));
        const nextCount = Math.max(0, Number(count || 0) - safeDeleted);
        const maxPage = Math.max(1, Math.ceil(nextCount / PAGE_SIZE));
        if (page > maxPage) {
            setPage(maxPage);
        } else {
            fetchContacts();
        }
    }

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

    function openEditContact(contact) {
        setEditingContact(contact);
        setEditForm({
            full_name: contact.full_name || contact.name || '',
            phone_e164: contact.phone_e164 || contact.phone || '',
            email: contact.email || '',
            company_name: contact.company_name || contact.company || '',
        });
        setEditOpen(true);
    }

    async function handleUpdateContact() {
        if (!editingContact) return;

        const fullName = editForm.full_name.trim();
        const phone = editForm.phone_e164.trim();
        if (!fullName || !phone) {
            toast.error('Name and phone are required');
            return;
        }

        setUpdating(true);
        try {
            await request(`/api/v1/dialer/leads/${editingContact.id}/update/`, {
                method: 'POST',
                body: JSON.stringify({
                    full_name: fullName,
                    phone_e164: phone,
                    email: editForm.email.trim(),
                    company_name: editForm.company_name.trim(),
                }),
            });
            toast.success('Contact updated');
            setEditOpen(false);
            setEditingContact(null);
            fetchContacts();
        } catch (e) {
            toast.error(e.message || 'Failed to update contact');
        } finally {
            setUpdating(false);
        }
    }

    async function handleDeleteContact(contact) {
        const contactName = contact?.full_name || contact?.name || `Contact #${contact?.id || ''}`;
        const ok = window.confirm(`Delete "${contactName}"?`);
        if (!ok) return;

        setDeletingId(contact.id);
        try {
            await request(`/api/v1/dialer/leads/${contact.id}/delete/`, {
                method: 'POST',
            });
            toast.success('Contact deleted');
            setSelectedIds((prev) => prev.filter((id) => id !== contact.id));
            refreshAfterDelete(1);
        } catch (e) {
            if (String(e.message || '').includes('contact_has_call_history')) {
                toast.error('Cannot delete contact with call history');
            } else if (String(e.message || '').includes('contact_call_in_progress')) {
                toast.error('Cannot delete contact while call is in progress');
            } else {
                toast.error(e.message || 'Failed to delete contact');
            }
        } finally {
            setDeletingId(null);
        }
    }

    function toggleRowSelection(contactId, checked) {
        setSelectedIds((prev) => {
            if (checked) {
                return prev.includes(contactId) ? prev : [...prev, contactId];
            }
            return prev.filter((id) => id !== contactId);
        });
    }

    function toggleSelectAll(checked) {
        const visibleIds = contacts.map((c) => c.id);
        setSelectedIds((prev) => {
            if (checked) {
                return Array.from(new Set([...prev, ...visibleIds]));
            }
            return prev.filter((id) => !visibleIds.includes(id));
        });
    }

    async function handleBulkDelete() {
        if (!selectedIds.length) return;
        const ok = window.confirm(`Delete ${selectedIds.length} selected contacts?`);
        if (!ok) return;

        try {
            const data = await request('/api/v1/dialer/leads/bulk-delete/', {
                method: 'POST',
                body: JSON.stringify({ lead_ids: selectedIds }),
            });

            const deleted = Number(data?.deleted || 0);
            const blockedInProgress = Number((data?.blocked_in_progress || []).length);
            const blockedWithHistory = Number((data?.blocked_with_history || []).length);
            const missing = Number((data?.missing_ids || []).length);

            if (deleted > 0) {
                toast.success(`Deleted ${deleted} contact${deleted === 1 ? '' : 's'}`);
            } else {
                toast.error('No contacts deleted');
            }
            if (blockedInProgress > 0) {
                toast.error(`${blockedInProgress} contact${blockedInProgress === 1 ? '' : 's'} have active calls`);
            }
            if (blockedWithHistory > 0) {
                toast.error(`${blockedWithHistory} contact${blockedWithHistory === 1 ? '' : 's'} have call history`);
            }
            if (missing > 0) {
                toast.error(`${missing} contact${missing === 1 ? '' : 's'} already removed`);
            }

            const deletedIds = Array.isArray(data?.deleted_ids) ? data.deleted_ids : [];
            setSelectedIds((prev) => prev.filter((id) => !deletedIds.includes(id)));
            refreshAfterDelete(deleted);
        } catch (e) {
            toast.error(e.message || 'Failed bulk delete');
        }
    }

    async function handleBulkDeleteFiltered() {
        const text = search.trim();
        if (!text) {
            toast.error('Enter search text to use filtered delete');
            return;
        }

        const ok = window.confirm(`Delete all contacts matching search "${text}"?`);
        if (!ok) return;

        try {
            const data = await request('/api/v1/dialer/leads/bulk-delete-filtered/', {
                method: 'POST',
                body: JSON.stringify({ search: text }),
            });

            const deleted = Number(data?.deleted || 0);
            const blockedInProgress = Number((data?.blocked_in_progress || []).length);
            const blockedWithHistory = Number((data?.blocked_with_history || []).length);
            const missing = Number((data?.missing_ids || []).length);

            if (deleted > 0) {
                toast.success(`Deleted ${deleted} filtered contact${deleted === 1 ? '' : 's'}`);
            } else {
                toast.error('No filtered contacts deleted');
            }
            if (blockedInProgress > 0) {
                toast.error(`${blockedInProgress} filtered contact${blockedInProgress === 1 ? '' : 's'} have active calls`);
            }
            if (blockedWithHistory > 0) {
                toast.error(`${blockedWithHistory} filtered contact${blockedWithHistory === 1 ? '' : 's'} have call history`);
            }
            if (missing > 0) {
                toast.error(`${missing} filtered contact${missing === 1 ? '' : 's'} already removed`);
            }

            setSelectedIds([]);
            setPage(1);
            if (page === 1) {
                fetchContacts();
            }
        } catch (e) {
            toast.error(e.message || 'Failed filtered bulk delete');
        }
    }

    const visibleIds = contacts.map((c) => c.id);
    const selectedVisibleCount = visibleIds.filter((id) => selectedIds.includes(id)).length;
    const allVisibleSelected = contacts.length > 0 && selectedVisibleCount === contacts.length;

    return (
        <Box>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                <Box>
                    <Typography variant="h4" fontWeight={700}>Contacts</Typography>
                    <Typography color="text.secondary" variant="body2">{count} contacts across all campaigns</Typography>
                </Box>
                <Box sx={{ display: 'flex', gap: 1 }}>
                    <Button
                        variant="outlined"
                        color="warning"
                        onClick={handleBulkDeleteFiltered}
                        disabled={!search.trim()}
                    >
                        Delete Filtered ({search.trim() ? count : 0})
                    </Button>
                    <Button
                        variant="outlined"
                        color="error"
                        onClick={handleBulkDelete}
                        disabled={selectedIds.length === 0}
                    >
                        Delete Selected ({selectedIds.length})
                    </Button>
                    <Button
                        variant="contained"
                        startIcon={<Add />}
                        onClick={() => setCreateOpen(true)}
                        sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                    >
                        Create Contact
                    </Button>
                </Box>
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
                                <TableCell padding="checkbox">
                                    <Checkbox
                                        size="small"
                                        checked={allVisibleSelected}
                                        indeterminate={selectedVisibleCount > 0 && !allVisibleSelected}
                                        onChange={(e) => toggleSelectAll(e.target.checked)}
                                    />
                                </TableCell>
                                <TableCell>Name</TableCell>
                                <TableCell>Phone</TableCell>
                                <TableCell>Email</TableCell>
                                <TableCell>Company</TableCell>
                                <TableCell>Status</TableCell>
                                <TableCell>Retries</TableCell>
                                <TableCell>Last Called</TableCell>
                                <TableCell align="right">Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {loading ? (
                                <TableRow>
                                    <TableCell colSpan={9} align="center" sx={{ py: 4, color: '#94a3b8' }}>
                                        Loading contacts...
                                    </TableCell>
                                </TableRow>
                            ) : contacts.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={9} align="center" sx={{ py: 4, color: '#94a3b8' }}>
                                        No contacts found
                                    </TableCell>
                                </TableRow>
                            ) : null}
                            {contacts.map(c => (
                                <TableRow key={c.id} hover>
                                    <TableCell padding="checkbox">
                                        <Checkbox
                                            size="small"
                                            checked={selectedIds.includes(c.id)}
                                            onChange={(e) => toggleRowSelection(c.id, e.target.checked)}
                                        />
                                    </TableCell>
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
                                    <TableCell align="right">
                                        <Tooltip title="Edit Contact">
                                            <span>
                                                <IconButton size="small" onClick={() => openEditContact(c)}>
                                                    <Edit fontSize="small" />
                                                </IconButton>
                                            </span>
                                        </Tooltip>
                                        <Tooltip title="Delete Contact">
                                            <span>
                                                <IconButton
                                                    size="small"
                                                    color="error"
                                                    onClick={() => handleDeleteContact(c)}
                                                    disabled={deletingId === c.id}
                                                >
                                                    <DeleteOutline fontSize="small" />
                                                </IconButton>
                                            </span>
                                        </Tooltip>
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
                {count > PAGE_SIZE && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', p: 2 }}>
                        <Pagination count={Math.ceil(count / PAGE_SIZE)} page={page} onChange={(_, v) => setPage(v)}
                            sx={{ '& .MuiPaginationItem-root': { color: '#94a3b8' }, '& .Mui-selected': { bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' } }} />
                    </Box>
                )}
            </Card>

            <Dialog
                open={createOpen}
                onClose={() => !creating && setCreateOpen(false)}
                fullWidth
                maxWidth="sm"
                PaperProps={{ sx: { bgcolor: '#f0f4f9', border: '1px solid rgba(1,66,162,0.2)' } }}
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
                        sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                    >
                        {creating ? 'Creating...' : 'Create'}
                    </Button>
                </DialogActions>
            </Dialog>

            <Dialog
                open={editOpen}
                onClose={() => !updating && setEditOpen(false)}
                fullWidth
                maxWidth="sm"
                PaperProps={{ sx: { bgcolor: '#f0f4f9', border: '1px solid rgba(1,66,162,0.2)' } }}
            >
                <DialogTitle>Update Contact</DialogTitle>
                <DialogContent>
                    <Grid container spacing={2} sx={{ mt: 0.5 }}>
                        <Grid item xs={12}>
                            <TextField
                                fullWidth
                                required
                                label="Full Name"
                                value={editForm.full_name}
                                onChange={(e) => setEditForm({ ...editForm, full_name: e.target.value })}
                            />
                        </Grid>
                        <Grid item xs={12} sm={6}>
                            <TextField
                                fullWidth
                                required
                                label="Phone (E.164)"
                                placeholder="+9199XXXXXXXX"
                                value={editForm.phone_e164}
                                onChange={(e) => setEditForm({ ...editForm, phone_e164: e.target.value })}
                            />
                        </Grid>
                        <Grid item xs={12} sm={6}>
                            <TextField
                                fullWidth
                                label="Email"
                                value={editForm.email}
                                onChange={(e) => setEditForm({ ...editForm, email: e.target.value })}
                            />
                        </Grid>
                        <Grid item xs={12}>
                            <TextField
                                fullWidth
                                label="Company"
                                value={editForm.company_name}
                                onChange={(e) => setEditForm({ ...editForm, company_name: e.target.value })}
                            />
                        </Grid>
                    </Grid>
                </DialogContent>
                <DialogActions sx={{ px: 3, pb: 2 }}>
                    <Button onClick={() => setEditOpen(false)} disabled={updating}>
                        Cancel
                    </Button>
                    <Button
                        variant="contained"
                        onClick={handleUpdateContact}
                        disabled={updating}
                        sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}
                    >
                        {updating ? 'Updating...' : 'Update'}
                    </Button>
                </DialogActions>
            </Dialog>
        </Box>
    );
}
