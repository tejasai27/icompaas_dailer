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
            background: 'radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.15) 0%, transparent 60%), radial-gradient(ellipse at 80% 50%, rgba(16,185,129,0.1) 0%, transparent 60%), #0f0f1a',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            p: 2,
        }}>
            {/* Animated orbs */}
            <Box sx={{
                position: 'fixed', top: '20%', left: '10%',
                width: 300, height: 300, borderRadius: '50%',
                background: 'radial-gradient(circle, rgba(99,102,241,0.1), transparent)',
                filter: 'blur(40px)', pointerEvents: 'none',
                animation: 'pulse 4s ease-in-out infinite',
                '@keyframes pulse': {
                    '0%, 100%': { opacity: 0.6, transform: 'scale(1)' },
                    '50%': { opacity: 1, transform: 'scale(1.1)' },
                }
            }} />

            <Card sx={{
                width: '100%', maxWidth: 420,
                bgcolor: 'rgba(26,26,46,0.9)',
                backdropFilter: 'blur(20px)',
                border: '1px solid rgba(99,102,241,0.2)',
                boxShadow: '0 25px 50px rgba(0,0,0,0.5)',
            }}>
                <CardContent sx={{ p: 4 }}>
                    {/* Logo */}
                    <Box sx={{ textAlign: 'center', mb: 4 }}>
                        <Box sx={{
                            width: 64, height: 64, borderRadius: 3, mx: 'auto', mb: 2,
                            background: 'linear-gradient(135deg, #6366f1, #818cf8)',
                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                            boxShadow: '0 0 30px rgba(99,102,241,0.4)',
                        }}>
                            <Phone sx={{ fontSize: 30, color: '#fff' }} />
                        </Box>
                        <Typography variant="h4" fontWeight={700} sx={{
                            background: 'linear-gradient(90deg, #6366f1, #818cf8)',
                            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
                        }}>
                            PowerDialer
                        </Typography>
                        <Typography color="text.secondary" variant="body2" mt={0.5}>
                            Sales Automation Platform
                        </Typography>
                    </Box>

                    <Typography variant="h6" fontWeight={600} mb={0.5}>Sign in</Typography>
                    <Typography variant="body2" color="text.secondary" mb={3}>
                        Enter your credentials to access the dialer
                    </Typography>

                    <form onSubmit={handleSubmit}>
                        <TextField
                            fullWidth
                            label="Username"
                            value={form.username}
                            onChange={e => setForm({ ...form, username: e.target.value })}
                            InputProps={{
                                startAdornment: <InputAdornment position="start"><Person sx={{ color: '#64748b', fontSize: 18 }} /></InputAdornment>
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
                                startAdornment: <InputAdornment position="start"><Lock sx={{ color: '#64748b', fontSize: 18 }} /></InputAdornment>,
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
                                background: 'linear-gradient(135deg, #6366f1, #818cf8)',
                                '&:hover': { background: 'linear-gradient(135deg, #4f46e5, #6366f1)' },
                                boxShadow: '0 4px 15px rgba(99,102,241,0.4)',
                            }}
                        >
                            {loading ? <CircularProgress size={22} color="inherit" /> : 'Sign In'}
                        </Button>
                    </form>

                    <Divider sx={{ my: 3, borderColor: 'rgba(99,102,241,0.2)' }}>
                        <Typography variant="caption" color="text.secondary">Demo Credentials</Typography>
                    </Divider>

                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        {[
                            { label: 'Admin', username: 'admin', password: 'admin123' },
                            { label: 'Agent', username: 'agent1', password: 'agent123' },
                        ].map(({ label, username, password }) => (
                            <Button
                                key={label}
                                size="small"
                                variant="outlined"
                                sx={{ borderColor: 'rgba(99,102,241,0.3)', color: '#818cf8', fontSize: '0.75rem' }}
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
