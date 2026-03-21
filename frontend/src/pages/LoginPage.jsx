import React, { useState } from 'react';
import {
    Box, Card, CardContent, Checkbox, TextField, Button, Typography,
    InputAdornment, IconButton, CircularProgress, Divider, FormControlLabel,
} from '@mui/material';
import { Visibility, VisibilityOff, Phone, Lock, Person, CheckCircle } from '@mui/icons-material';
import { useNavigate } from 'react-router-dom';
import useAuth from '../context/useAuth';
import toast from 'react-hot-toast';

const FEATURES = [
    'Queue-based power dialing',
    'HubSpot CRM integration',
    'AI call transcription',
    'Real-time salesfloor',
];

export default function LoginPage() {
    const [form, setForm] = useState({ username: '', password: '' });
    const [showPw, setShowPw] = useState(false);
    const [loading, setLoading] = useState(false);
    const { user, login } = useAuth();
    const navigate = useNavigate();

    React.useEffect(() => {
        if (user) navigate('/dashboard', { replace: true });
    }, [user, navigate]);

    const usernameValid = form.username.trim().length >= 1;
    const passwordValid = form.password.length >= 1;
    const canSubmit = usernameValid && passwordValid && !loading;

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (!canSubmit) return;
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
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            p: 2, position: 'relative', overflow: 'hidden',
        }}>
            {/* Background decorations */}
            <Box sx={{ position: 'absolute', top: '-10%', right: '-5%', width: 400, height: 400, borderRadius: '50%', background: 'rgba(255,255,255,0.05)', pointerEvents: 'none' }} />
            <Box sx={{ position: 'absolute', bottom: '-15%', left: '-8%', width: 500, height: 500, borderRadius: '50%', background: 'rgba(255,255,255,0.04)', pointerEvents: 'none' }} />

            {/* Split layout container */}
            <Card sx={{
                width: '100%', maxWidth: 860, display: 'flex', overflow: 'hidden',
                bgcolor: '#f0f4f9', boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
                border: 'none', borderRadius: 4, position: 'relative', zIndex: 1,
            }}>
                {/* Left panel — Product info */}
                <Box sx={{
                    width: { xs: 0, md: '45%' }, display: { xs: 'none', md: 'flex' },
                    flexDirection: 'column', justifyContent: 'center',
                    background: 'linear-gradient(180deg, #012f7a 0%, #0142a2 100%)',
                    color: 'white', p: 5,
                }}>
                    <Box sx={{
                        width: 56, height: 56, borderRadius: 3, mb: 3,
                        background: 'rgba(255,255,255,0.15)', backdropFilter: 'blur(8px)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                        <Phone sx={{ fontSize: 28 }} />
                    </Box>
                    <Typography variant="h4" fontWeight={800} sx={{ mb: 1, lineHeight: 1.2 }}>
                        iCompaas<br />Power Dialer
                    </Typography>
                    <Typography variant="body2" sx={{ opacity: 0.7, mb: 4 }}>
                        Sales Automation Platform
                    </Typography>
                    <Box sx={{ display: 'grid', gap: 1.5 }}>
                        {FEATURES.map((f) => (
                            <Box key={f} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <CheckCircle sx={{ fontSize: 18, color: '#10b981' }} />
                                <Typography variant="body2" sx={{ opacity: 0.9 }}>{f}</Typography>
                            </Box>
                        ))}
                    </Box>
                    <Divider sx={{ my: 3, borderColor: 'rgba(255,255,255,0.1)' }} />
                    <Typography variant="caption" sx={{ opacity: 0.5 }}>
                        Trusted by sales teams for outbound dialing
                    </Typography>
                </Box>

                {/* Right panel — Login form */}
                <CardContent sx={{ flex: 1, p: { xs: 3, sm: 5 }, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                    {/* Mobile-only logo */}
                    <Box sx={{ display: { xs: 'flex', md: 'none' }, alignItems: 'center', gap: 1.5, mb: 3 }}>
                        <Box sx={{ width: 44, height: 44, borderRadius: 2, bgcolor: '#0142a2', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <Phone sx={{ fontSize: 22, color: '#fff' }} />
                        </Box>
                        <Box>
                            <Typography fontWeight={800} color="#0142a2">iCompaas Power Dialer</Typography>
                            <Typography variant="caption" color="text.secondary">Sales Automation Platform</Typography>
                        </Box>
                    </Box>

                    <Typography variant="h5" fontWeight={800} sx={{ mb: 0.5, color: '#0f172a' }}>
                        Welcome back
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                        Sign in to your account to continue
                    </Typography>

                    <form onSubmit={handleSubmit}>
                        <TextField
                            fullWidth label="Username" value={form.username}
                            onChange={(e) => setForm({ ...form, username: e.target.value })}
                            error={form.username.length > 0 && !usernameValid}
                            helperText={form.username.length > 0 && !usernameValid ? 'Username is required' : ''}
                            InputProps={{ startAdornment: <InputAdornment position="start"><Person sx={{ color: '#94a3b8', fontSize: 20 }} /></InputAdornment> }}
                            sx={{ mb: 2 }} required
                        />
                        <TextField
                            fullWidth label="Password" type={showPw ? 'text' : 'password'}
                            value={form.password}
                            onChange={(e) => setForm({ ...form, password: e.target.value })}
                            error={form.password.length > 0 && !passwordValid}
                            helperText={form.password.length > 0 && !passwordValid ? 'Password is required' : ''}
                            InputProps={{
                                startAdornment: <InputAdornment position="start"><Lock sx={{ color: '#94a3b8', fontSize: 20 }} /></InputAdornment>,
                                endAdornment: <InputAdornment position="end"><IconButton size="small" onClick={() => setShowPw(!showPw)} aria-label={showPw ? 'Hide password' : 'Show password'}>{showPw ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}</IconButton></InputAdornment>,
                            }}
                            sx={{ mb: 2 }} required
                        />

                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
                            <FormControlLabel
                                control={<Checkbox size="small" sx={{ color: '#94a3b8' }} />}
                                label={<Typography variant="caption" color="text.secondary">Remember me</Typography>}
                            />
                        </Box>

                        <Button fullWidth type="submit" variant="contained" size="large" disabled={!canSubmit}
                            sx={{
                                py: 1.5, bgcolor: '#0142a2', '&:hover': { bgcolor: '#1a5bc4' },
                                boxShadow: '0 4px 14px rgba(1,66,162,0.35)',
                                borderRadius: 2.5, fontSize: '0.95rem', fontWeight: 700,
                            }}>
                            {loading ? <CircularProgress size={22} sx={{ color: '#fff' }} /> : 'Sign In'}
                        </Button>
                    </form>

                    {/* SSO placeholder */}
                    <Divider sx={{ my: 3, borderColor: '#e2e8f0' }}>
                        <Typography variant="caption" color="text.secondary">or continue with</Typography>
                    </Divider>
                    <Box sx={{ display: 'flex', gap: 1 }}>
                        <Button fullWidth variant="outlined" disabled
                            sx={{ borderColor: '#e2e8f0', color: '#94a3b8', textTransform: 'none', borderRadius: 2 }}>
                            Google (Coming Soon)
                        </Button>
                        <Button fullWidth variant="outlined" disabled
                            sx={{ borderColor: '#e2e8f0', color: '#94a3b8', textTransform: 'none', borderRadius: 2 }}>
                            Microsoft (Coming Soon)
                        </Button>
                    </Box>
                </CardContent>
            </Card>
        </Box>
    );
}
