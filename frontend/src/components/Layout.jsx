import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
    Box, Drawer, AppBar, Toolbar, Typography, IconButton,
    List, ListItem, ListItemButton, ListItemIcon, ListItemText,
    Avatar, Chip, Tooltip, Divider, Badge
} from '@mui/material';
import {
    Dashboard, Campaign, Headphones, Contacts, Phone, Dialpad,
    History, Settings, Menu, ChevronLeft, PowerSettingsNew,
    Notifications, Circle, People, AudioFile
} from '@mui/icons-material';
import useAuth from '../context/useAuth';

const DRAWER_WIDTH = 260;

const nav = [
    { label: 'Dashboard', icon: <Dashboard />, path: '/dashboard' },
    { label: 'Dial', icon: <Dialpad />, path: '/dial' },
    { label: 'Campaigns', icon: <Campaign />, path: '/campaigns' },
    { label: 'Salesfloor', icon: <Headphones />, path: '/salesfloor' },
    { label: 'SDRs', icon: <People />, path: '/sdrs' },
    { label: 'Contacts', icon: <Contacts />, path: '/contacts' },
    { label: 'Call Logs', icon: <History />, path: '/call-logs' },
    { label: 'Call Recordings', icon: <AudioFile />, path: '/recordings' },
    { label: 'Settings', icon: <Settings />, path: '/settings' },
];

export default function Layout() {
    const [open, setOpen] = useState(true);
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    return (
        <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
            {/* Sidebar */}
            <Drawer
                variant="permanent"
                sx={{
                    width: open ? DRAWER_WIDTH : 72,
                    transition: 'width 0.3s ease',
                    '& .MuiDrawer-paper': {
                        width: open ? DRAWER_WIDTH : 72,
                        overflowX: 'hidden',
                        transition: 'width 0.3s ease',
                        bgcolor: '#12122a',
                        borderRight: '1px solid rgba(99,102,241,0.15)',
                        display: 'flex',
                        flexDirection: 'column',
                    },
                }}
            >
                {/* Logo */}
                <Box sx={{ p: 2, display: 'flex', alignItems: 'center', gap: 1.5, minHeight: 64 }}>
                    <Box sx={{
                        width: 36, height: 36, borderRadius: 2,
                        background: 'linear-gradient(135deg, #6366f1, #818cf8)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0
                    }}>
                        <Phone sx={{ fontSize: 18, color: '#fff' }} />
                    </Box>
                    {open && (
                        <Typography variant="h6" fontWeight={700} sx={{
                            background: 'linear-gradient(90deg, #6366f1, #818cf8)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                        }}>
                            PowerDialer
                        </Typography>
                    )}
                </Box>

                <Divider sx={{ borderColor: 'rgba(99,102,241,0.1)' }} />

                {/* Nav items */}
                <List sx={{ flex: 1, px: 1, pt: 1 }}>
                    {nav.map(({ label, icon, path }) => {
                        const active = location.pathname.startsWith(path);
                        return (
                            <ListItem key={path} disablePadding sx={{ mb: 0.5 }}>
                                <Tooltip title={!open ? label : ''} placement="right">
                                    <ListItemButton
                                        onClick={() => navigate(path)}
                                        sx={{
                                            borderRadius: 2,
                                            minHeight: 44,
                                            px: 1.5,
                                            bgcolor: active ? 'rgba(99,102,241,0.15)' : 'transparent',
                                            '&:hover': { bgcolor: 'rgba(99,102,241,0.1)' },
                                            transition: 'all 0.2s',
                                        }}
                                    >
                                        <ListItemIcon sx={{
                                            minWidth: 36,
                                            color: active ? '#6366f1' : '#64748b',
                                        }}>
                                            {icon}
                                        </ListItemIcon>
                                        {open && (
                                            <ListItemText
                                                primary={label}
                                                primaryTypographyProps={{
                                                    fontSize: '0.875rem',
                                                    fontWeight: active ? 600 : 400,
                                                    color: active ? '#6366f1' : '#94a3b8',
                                                }}
                                            />
                                        )}
                                        {active && open && (
                                            <Box sx={{
                                                width: 3, height: 20, borderRadius: 2,
                                                bgcolor: '#6366f1', ml: 1
                                            }} />
                                        )}
                                    </ListItemButton>
                                </Tooltip>
                            </ListItem>
                        );
                    })}
                </List>

                <Divider sx={{ borderColor: 'rgba(99,102,241,0.1)' }} />

                {/* User section */}
                <Box sx={{ p: 1.5 }}>
                    {open ? (
                        <Box sx={{
                            display: 'flex', alignItems: 'center', gap: 1.5,
                            p: 1.5, borderRadius: 2, bgcolor: 'rgba(99,102,241,0.08)',
                            cursor: 'pointer', '&:hover': { bgcolor: 'rgba(99,102,241,0.15)' }
                        }}>
                            <Avatar sx={{ width: 32, height: 32, bgcolor: '#6366f1', fontSize: '0.85rem' }}>
                                {user?.full_name?.[0] || user?.username?.[0]}
                            </Avatar>
                            <Box flex={1}>
                                <Typography fontSize="0.8rem" fontWeight={600} color="text.primary">
                                    {user?.full_name || user?.username}
                                </Typography>
                                <Chip
                                    label={user?.role}
                                    size="small"
                                    sx={{ height: 16, fontSize: '0.65rem', bgcolor: 'rgba(99,102,241,0.2)', color: '#818cf8' }}
                                />
                            </Box>
                            <Tooltip title="Logout">
                                <IconButton size="small" onClick={logout} sx={{ color: '#64748b' }}>
                                    <PowerSettingsNew fontSize="small" />
                                </IconButton>
                            </Tooltip>
                        </Box>
                    ) : (
                        <Tooltip title={user?.full_name} placement="right">
                            <Avatar
                                onClick={logout}
                                sx={{ width: 36, height: 36, bgcolor: '#6366f1', fontSize: '0.9rem', cursor: 'pointer', mx: 'auto' }}
                            >
                                {user?.full_name?.[0] || user?.username?.[0]}
                            </Avatar>
                        </Tooltip>
                    )}
                </Box>
            </Drawer>

            {/* Main content */}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* Top bar */}
                <AppBar position="static" elevation={0} sx={{
                    bgcolor: '#12122a',
                    borderBottom: '1px solid rgba(99,102,241,0.15)',
                }}>
                    <Toolbar sx={{ gap: 2 }}>
                        <IconButton onClick={() => setOpen(!open)} sx={{ color: '#64748b' }}>
                            {open ? <ChevronLeft /> : <Menu />}
                        </IconButton>
                        <Box flex={1} />
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                            <Circle sx={{ fontSize: 8, color: '#10b981' }} />
                            <Typography variant="caption" color="success.main" fontWeight={600}>
                                System Online
                            </Typography>
                        </Box>
                        <IconButton sx={{ color: '#64748b' }}>
                            <Badge badgeContent={2} color="error">
                                <Notifications />
                            </Badge>
                        </IconButton>
                    </Toolbar>
                </AppBar>

                {/* Page content */}
                <Box sx={{ flex: 1, overflow: 'auto', p: 3 }}>
                    <Outlet />
                </Box>
            </Box>
        </Box>
    );
}
