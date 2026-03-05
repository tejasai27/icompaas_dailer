import React, { useState } from 'react';
import {
    Box, Card, CardContent, TextField, Button, Typography,
    InputAdornment, IconButton, CircularProgress, Divider
} from '@mui/material';
import { Visibility, VisibilityOff, Phone, Lock, Person } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import useAuth from '../context/useAuth';
import toast from 'react-hot-toast';

export default function LoginPage() {
    const [form, setForm] = useState({ username: '', password: '' });
    const [showPw, setShowPw] = useState(false);
    const [loading, setLoading] = useState(false);
    const { login } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e) => {
        e.preventDefault();
        setLoading(true);
        try {
            await login(form.username, form.password);
            toast.success('Welcome back!');
            navigate('/dashboard');
        } catch (err) {
            toast.error(err.response?.data?.detail || 'Invalid credentials');
        } finally {
            setLoading(false);
        }
    };

    return (
        <Box sx={{
            minHeight: '100vh',
            background: 'linear-gradient(135deg, #0142a2 0%, #1a5bc4 40%, #0d9488 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            p: 2,
            position: 'relative',
            overflow: 'hidden',
        }}>
            {/* Background decorations */}
            <Box sx={{
                position: 'absolute', top: '-10%', right: '-5%',
                width: 400, height: 400, borderRadius: '50%',
                background: 'rgba(255,255,255,0.05)',
                pointerEvents: 'none',
            }} />
            <Box sx={{
                position: 'absolute', bottom: '-15%', left: '-8%',
                width: 500, height: 500, borderRadius: '50%',
                background: 'rgba(255,255,255,0.04)',
                pointerEvents: 'none',
            }} />

            <Card sx={{
                width: '100%', maxWidth: 420,
                bgcolor: '#f0f4f9',
                boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
                border: 'none',
                borderRadius: 3,
                position: 'relative',
                zIndex: 1,
            }}>
                <CardContent sx={{ p: 4 }}>
                    {/* Logo */}
                    <Box sx={{ textAlign: 'center', mb: 4 }}>
                        <Box sx={{
                            width: 64, height: 64, borderRadius: '16px', mx: 'auto', mb: 2,
                            background: '#0142a2',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            boxShadow: '0 8px 24px rgba(1,66,162,0.35)',
                        }}>
                            <Phone sx={{ fontSize: 30, color: '#fff' }} />
                        </Box>
                        <Typography variant="h5" fontWeight={800} sx={{ color: '#0142a2', letterSpacing: '-0.02em' }}>
                            iCompaas Power Dialer
                        </Typography>
                        <Typography color="text.secondary" variant="body2" mt={0.5}>
                            Sales Automation Platform
                        </Typography>
                    </Box>

                    <Typography variant="h6" fontWeight={700} mb={0.5} color="text.primary">
                        Sign in to your account
                    </Typography>
                    <Typography variant="body2" color="text.secondary" mb={3}>
                        Enter your credentials to continue
                    </Typography>

                    <form onSubmit={handleSubmit}>
                        <TextField
                            fullWidth
                            label="Username"
                            value={form.username}
                            onChange={e => setForm({ ...form, username: e.target.value })}
                            InputProps={{
                                startAdornment: (
                                    <InputAdornment position="start">
                                        <Person sx={{ color: '#64748b', fontSize: 20 }} />
                                    </InputAdornment>
                                )
                            }}
                            sx={{ mb: 2 }}
                            required
                        />
                        <TextField
                            fullWidth
                            label="Password"
                            type={showPw ? 'text' : 'password'}
                            value={form.password}
                            onChange={e => setForm({ ...form, password: e.target.value })}
                            InputProps={{
                                startAdornment: (
                                    <InputAdornment position="start">
                                        <Lock sx={{ color: '#64748b', fontSize: 20 }} />
                                    </InputAdornment>
                                ),
                                endAdornment: (
                                    <InputAdornment position="end">
                                        <IconButton size="small" onClick={() => setShowPw(!showPw)}>
                                            {showPw ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                                        </IconButton>
                                    </InputAdornment>
                                )
                            }}
                            sx={{ mb: 3 }}
                            required
                        />
                        <Button
                            fullWidth
                            type="submit"
                            variant="contained"
                            size="large"
                            disabled={loading}
                            sx={{
                                py: 1.5,
                                bgcolor: '#0142a2',
                                '&:hover': { bgcolor: '#1a5bc4' },
                                boxShadow: '0 4px 14px rgba(1,66,162,0.35)',
                                borderRadius: 2,
                                fontSize: '0.95rem',
                                fontWeight: 700,
                            }}
                        >
                            {loading ? <CircularProgress size={22} sx={{ color: '#fff' }} /> : 'Sign In'}
                        </Button>
                    </form>

                    <Divider sx={{ my: 3, borderColor: '#e2e8f0' }}>
                        <Typography variant="caption" color="text.secondary">Quick Access</Typography>
                    </Divider>

                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        {[
                            { label: 'Admin Demo', username: 'admin', password: 'admin123' },
                            { label: 'Agent Demo', username: 'agent1', password: 'agent123' },
                        ].map(({ label, username, password }) => (
                            <Button
                                key={label}
                                size="small"
                                variant="outlined"
                                sx={{
                                    borderColor: '#e2e8f0',
                                    color: '#64748b',
                                    fontSize: '0.78rem',
                                    borderRadius: 2,
                                    '&:hover': { borderColor: '#0142a2', color: '#0142a2', bgcolor: 'rgba(1,66,162,0.04)' },
                                }}
                                onClick={() => setForm({ username, password })}
                            >
                                {label}
                            </Button>
                        ))}
                    </Box>
                </CardContent>
            </Card>
        </Box>
    );
}
