import React, { useCallback, useEffect, useState } from 'react';
import {
    Alert, Avatar, Box, Card, CardContent, Typography, Table, TableBody, TableCell,
    TableContainer, TableHead, TableRow, Chip, InputAdornment, TextField, Pagination,
    Button, CircularProgress, IconButton, Skeleton, Tooltip, Checkbox
} from '@mui/material';
import { Add, Search, Edit, DeleteOutline, Phone, FileDownload, People } from '@mui/icons-material';
import api from '../services/api';
import toast from 'react-hot-toast';
import { CALL_STATUS_COLORS as STATUS_COLORS, normalizeCallStatus, formatCallStatus } from '../lib/callStatus';
import { shortDateTime } from '../lib/formatDate';
import { useNavigate } from 'react-router-dom';
import ContactFormDialog from '../components/ContactFormDialog';
import useConfirm from '../lib/useConfirm';
import useDebounce from '../lib/useDebounce';

const PAGE_SIZE = 20;

export default function ContactsPage() {
    const [contacts, setContacts] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState('');
    const debouncedSearch = useDebounce(search, 300);
    const [page, setPage] = useState(1);
    const [count, setCount] = useState(0);
    const [createOpen, setCreateOpen] = useState(false);
    const [creating, setCreating] = useState(false);
    const [editOpen, setEditOpen] = useState(false);
    const [updating, setUpdating] = useState(false);
    const [editingContact, setEditingContact] = useState(null);
    const [deletingId, setDeletingId] = useState(null);
    const [selectedIds, setSelectedIds] = useState([]);
    const navigate = useNavigate();
    const [confirm, ConfirmEl] = useConfirm();
    const [form, setForm] = useState({ full_name: '', phone_e164: '', email: '', company_name: '' });
    const [editForm, setEditForm] = useState({ full_name: '', phone_e164: '', email: '', company_name: '' });

    const fetchContacts = useCallback(async () => {
        setLoading(true);
        try {
            let path = `/leads/?page=${page}&page_size=${PAGE_SIZE}`;
            if (debouncedSearch.trim()) path += `&search=${encodeURIComponent(debouncedSearch.trim())}`;
            const { data } = await api.get(path);
            setContacts(Array.isArray(data.results) ? data.results : []);
            setCount(Number(data.count || 0));
        } catch (e) {
            toast.error(e.response?.data?.error || e.message || 'Failed to load contacts');
        } finally {
            setLoading(false);
        }
    }, [page, debouncedSearch]);

    useEffect(() => { fetchContacts(); }, [fetchContacts]);
    useEffect(() => { setSelectedIds([]); }, [search]);

    function refreshAfterDelete(deletedCount = 0) {
        const nextCount = Math.max(0, count - Math.max(0, Number(deletedCount || 0)));
        const maxPage = Math.max(1, Math.ceil(nextCount / PAGE_SIZE));
        if (page > maxPage) setPage(maxPage); else fetchContacts();
    }

    async function handleCreateContact() {
        const fullName = form.full_name.trim();
        const phone = form.phone_e164.trim();
        if (!fullName || !phone) { toast.error('Name and phone are required'); return; }
        setCreating(true);
        try {
            await api.post('/leads/manual/', { full_name: fullName, phone_e164: phone, email: form.email.trim(), company_name: form.company_name.trim() });
            toast.success('Contact created');
            setCreateOpen(false);
            setForm({ full_name: '', phone_e164: '', email: '', company_name: '' });
            if (page !== 1) setPage(1); else fetchContacts();
        } catch (e) { toast.error(e.response?.data?.error || e.message || 'Failed to create contact'); }
        finally { setCreating(false); }
    }

    function openEditContact(contact) {
        setEditingContact(contact);
        setEditForm({ full_name: contact.full_name || contact.name || '', phone_e164: contact.phone_e164 || contact.phone || '', email: contact.email || '', company_name: contact.company_name || contact.company || '' });
        setEditOpen(true);
    }

    async function handleUpdateContact() {
        if (!editingContact) return;
        const fullName = editForm.full_name.trim();
        const phone = editForm.phone_e164.trim();
        if (!fullName || !phone) { toast.error('Name and phone are required'); return; }
        setUpdating(true);
        try {
            await api.post(`/leads/${editingContact.id}/update/`, { full_name: fullName, phone_e164: phone, email: editForm.email.trim(), company_name: editForm.company_name.trim() });
            toast.success('Contact updated');
            setEditOpen(false);
            setEditingContact(null);
            fetchContacts();
        } catch (e) { toast.error(e.response?.data?.error || e.message || 'Failed to update contact'); }
        finally { setUpdating(false); }
    }

    async function handleDeleteContact(contact) {
        const contactName = contact?.full_name || contact?.name || `Contact #${contact?.id || ''}`;
        const ok = await confirm({ title: 'Delete Contact', body: `"${contactName}" (${contact?.phone || contact?.phone_e164 || ''}) will be permanently deleted.`, confirmLabel: 'Delete' });
        if (!ok) return;
        setDeletingId(contact.id);
        try {
            await api.post(`/leads/${contact.id}/delete/`);
            toast.success('Contact deleted');
            setSelectedIds((prev) => prev.filter((id) => id !== contact.id));
            refreshAfterDelete(1);
        } catch (e) {
            const err = e.response?.data?.error || e.message || '';
            toast.error(String(err).includes('call_history') ? 'Cannot delete contact with call history' : String(err).includes('call_in_progress') ? 'Active call — try later' : (err || 'Failed to delete'));
        } finally { setDeletingId(null); }
    }

    function toggleRowSelection(contactId, checked) {
        setSelectedIds((prev) => checked ? (prev.includes(contactId) ? prev : [...prev, contactId]) : prev.filter((id) => id !== contactId));
    }
    function toggleSelectAll(checked) {
        const visibleIds = contacts.map((c) => c.id);
        setSelectedIds((prev) => checked ? Array.from(new Set([...prev, ...visibleIds])) : prev.filter((id) => !visibleIds.includes(id)));
    }

    async function handleBulkDelete() {
        if (!selectedIds.length) return;
        const ok = await confirm({ title: 'Bulk Delete', body: `${selectedIds.length} selected contact${selectedIds.length === 1 ? '' : 's'} will be permanently deleted.`, confirmLabel: `Delete ${selectedIds.length}` });
        if (!ok) return;
        try {
            const { data } = await api.post('/leads/bulk-delete/', { lead_ids: selectedIds });
            const deleted = Number(data?.deleted || 0);
            const blocked = Number((data?.blocked_in_progress || []).length) + Number((data?.blocked_with_history || []).length);
            const parts = [];
            if (deleted > 0) parts.push(`Deleted ${deleted}`);
            if (blocked > 0) parts.push(`${blocked} blocked`);
            toast[deleted > 0 ? 'success' : 'error'](parts.join(' · ') || 'No contacts deleted');
            setSelectedIds((prev) => prev.filter((id) => !(data?.deleted_ids || []).includes(id)));
            refreshAfterDelete(deleted);
        } catch (e) { toast.error(e.response?.data?.error || 'Failed bulk delete'); }
    }

    async function handleBulkDeleteFiltered() {
        const text = search.trim();
        if (!text) { toast.error('Enter search text first'); return; }
        const ok = await confirm({ title: 'Delete Filtered', body: `All contacts matching "${text}" will be permanently deleted.`, confirmLabel: 'Delete All Matching' });
        if (!ok) return;
        try {
            const { data } = await api.post('/leads/bulk-delete-filtered/', { search: text });
            const deleted = Number(data?.deleted || 0);
            toast[deleted > 0 ? 'success' : 'error'](deleted > 0 ? `Deleted ${deleted} contacts` : 'No contacts deleted');
            setSelectedIds([]);
            setPage(1);
            if (page === 1) fetchContacts();
        } catch (e) { toast.error(e.response?.data?.error || 'Failed filtered delete'); }
    }

    const visibleIds = contacts.map((c) => c.id);
    const selectedVisibleCount = visibleIds.filter((id) => selectedIds.includes(id)).length;
    const allVisibleSelected = contacts.length > 0 && selectedVisibleCount === contacts.length;

    return (
        <Box>
            {/* Header */}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                <Box>
                    <Typography variant="h4" fontWeight={800}>Contacts</Typography>
                    <Typography color="text.secondary" variant="body2">{count.toLocaleString()} contacts across all campaigns</Typography>
                </Box>
                <Button variant="contained" startIcon={<Add />} onClick={() => setCreateOpen(true)}
                    sx={{ background: 'linear-gradient(135deg, #0142a2, #1a5bc4)' }}>
                    Create Contact
                </Button>
            </Box>

            {/* Toolbar: search + bulk actions */}
            <Box sx={{ display: 'flex', gap: 1.5, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
                <TextField
                    placeholder="Search by name, phone, company..."
                    value={search}
                    onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                    size="small"
                    InputProps={{ startAdornment: <InputAdornment position="start"><Search sx={{ color: '#94a3b8', fontSize: 18 }} /></InputAdornment> }}
                    sx={{ width: 300 }}
                />
                <Box sx={{ flex: 1 }} />
                {selectedIds.length > 0 && (
                    <Chip
                        label={`${selectedIds.length} selected`}
                        onDelete={() => setSelectedIds([])}
                        sx={{ bgcolor: 'rgba(1,66,162,0.1)', color: '#1a5bc4', fontWeight: 600 }}
                    />
                )}
                <Tooltip title={search.trim() ? `Delete all contacts matching "${search.trim()}"` : 'Enter search text first'}>
                    <span>
                        <Button size="small" variant="outlined" color="warning" onClick={handleBulkDeleteFiltered} disabled={!search.trim()}
                            sx={{ fontSize: '0.75rem' }}>
                            Delete All Matching
                        </Button>
                    </span>
                </Tooltip>
                <Button size="small" variant="outlined" color="error" onClick={handleBulkDelete} disabled={selectedIds.length === 0}
                    sx={{ fontSize: '0.75rem' }}>
                    Delete Selected ({selectedIds.length})
                </Button>
            </Box>

            {/* Table */}
            <Card>
                <TableContainer>
                    <Table size="small">
                        <TableHead>
                            <TableRow>
                                <TableCell padding="checkbox">
                                    <Checkbox size="small" checked={allVisibleSelected}
                                        indeterminate={selectedVisibleCount > 0 && !allVisibleSelected}
                                        onChange={(e) => toggleSelectAll(e.target.checked)} />
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
                            {loading ? Array.from({ length: 5 }).map((_, i) => (
                                <TableRow key={i}>{Array.from({ length: 9 }).map((_, j) => <TableCell key={j}><Skeleton /></TableCell>)}</TableRow>
                            )) : contacts.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={9} align="center" sx={{ py: 6 }}>
                                        <People sx={{ fontSize: 40, color: '#cbd5e1', mb: 1 }} />
                                        <Typography color="text.secondary">
                                            {debouncedSearch ? 'No contacts match your search' : 'No contacts yet. Create your first contact or import from a campaign.'}
                                        </Typography>
                                    </TableCell>
                                </TableRow>
                            ) : contacts.map((c) => {
                                const statusKey = normalizeCallStatus(c.status);
                                const statusColor = STATUS_COLORS[statusKey] || STATUS_COLORS[c.status] || '#64748b';
                                return (
                                    <TableRow key={c.id} hover sx={{
                                        borderLeft: `3px solid ${statusColor}`,
                                        bgcolor: selectedIds.includes(c.id) ? 'rgba(1,66,162,0.04)' : 'transparent',
                                    }}>
                                        <TableCell padding="checkbox">
                                            <Checkbox size="small" checked={selectedIds.includes(c.id)}
                                                onChange={(e) => toggleRowSelection(c.id, e.target.checked)} />
                                        </TableCell>
                                        <TableCell>
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                <Avatar sx={{ width: 28, height: 28, fontSize: '0.7rem', bgcolor: '#0142a2' }}>
                                                    {(c.name || '?')[0].toUpperCase()}
                                                </Avatar>
                                                <Typography fontWeight={600} fontSize="0.85rem">{c.name}</Typography>
                                            </Box>
                                        </TableCell>
                                        <TableCell>
                                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                                <Typography fontSize="0.85rem" fontFamily="monospace">{c.phone}</Typography>
                                                <Tooltip title={`Call ${c.phone}`}>
                                                    <IconButton size="small" onClick={(e) => { e.stopPropagation(); navigate(`/dial?phone=${encodeURIComponent(c.phone)}`); }}
                                                        sx={{ color: '#10b981', p: 0.25 }}>
                                                        <Phone sx={{ fontSize: 14 }} />
                                                    </IconButton>
                                                </Tooltip>
                                            </Box>
                                        </TableCell>
                                        <TableCell><Typography fontSize="0.85rem" color="text.secondary">{c.email || '—'}</Typography></TableCell>
                                        <TableCell><Typography fontSize="0.85rem">{c.company || '—'}</Typography></TableCell>
                                        <TableCell>
                                            <Chip label={formatCallStatus(c.status)} size="small"
                                                sx={{ bgcolor: `${statusColor}15`, color: statusColor, fontSize: '0.65rem', fontWeight: 600 }} />
                                        </TableCell>
                                        <TableCell><Typography fontSize="0.85rem">{c.retry_count}</Typography></TableCell>
                                        <TableCell><Typography fontSize="0.72rem" color="text.secondary">{c.last_called_at ? shortDateTime(c.last_called_at) : '—'}</Typography></TableCell>
                                        <TableCell align="right">
                                            <Tooltip title="Edit"><span>
                                                <IconButton size="small" onClick={() => openEditContact(c)}><Edit fontSize="small" /></IconButton>
                                            </span></Tooltip>
                                            <Tooltip title="Delete"><span>
                                                <IconButton size="small" color="error" onClick={() => handleDeleteContact(c)} disabled={deletingId === c.id}>
                                                    {deletingId === c.id ? <CircularProgress size={16} /> : <DeleteOutline fontSize="small" />}
                                                </IconButton>
                                            </span></Tooltip>
                                        </TableCell>
                                    </TableRow>
                                );
                            })}
                        </TableBody>
                    </Table>
                </TableContainer>
                {count > PAGE_SIZE && (
                    <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 2, p: 2 }}>
                        <Typography variant="caption" color="text.secondary">
                            Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, count)} of {count}
                        </Typography>
                        <Pagination count={Math.ceil(count / PAGE_SIZE)} page={page} onChange={(_, v) => setPage(v)}
                            sx={{ '& .MuiPaginationItem-root': { color: '#94a3b8' }, '& .Mui-selected': { bgcolor: 'rgba(1,66,162,0.2)', color: '#1a5bc4' } }} />
                    </Box>
                )}
            </Card>

            <ContactFormDialog open={createOpen} onClose={() => setCreateOpen(false)} title="Create Contact"
                form={form} onChange={setForm} onSubmit={handleCreateContact} submitting={creating} submitLabel="Create" />
            <ContactFormDialog open={editOpen} onClose={() => setEditOpen(false)} title="Update Contact"
                form={editForm} onChange={setEditForm} onSubmit={handleUpdateContact} submitting={updating} submitLabel="Update" />
            {ConfirmEl}
        </Box>
    );
}
