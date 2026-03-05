import React, { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import {
    Box, Drawer, AppBar, Toolbar, Typography, IconButton,
    List, ListItem, ListItemButton, ListItemIcon, ListItemText,
    Avatar, Tooltip, Divider, Badge, Button
} from '@mui/material';
import {
    Dashboard, Campaign, Headphones, Contacts, Phone, Dialpad,
    History, Settings, Menu, ChevronLeft, PowerSettingsNew,
    Notifications, Circle, People, AudioFile, Add


} from '@mui/icons-material';
import useAuth from '../context/useAuth';

const DRAWER_WIDTH = 248;

const nav = [
    { label: 'Dashboard', icon: <Dashboard fontSize="small" />, path: '/dashboard' },
    { label: 'Dial', icon: <Dialpad fontSize="small" />, path: '/dial' },
    { label: 'Campaigns', icon: <Campaign fontSize="small" />, path: '/campaigns' },
    { label: 'Salesfloor', icon: <Headphones fontSize="small" />, path: '/salesfloor' },
    { label: 'SDRs', icon: <People fontSize="small" />, path: '/sdrs' },
    { label: 'Contacts', icon: <Contacts fontSize="small" />, path: '/contacts' },
    { label: 'Call Logs', icon: <History fontSize="small" />, path: '/call-logs' },
    { label: 'Call Recordings', icon: <AudioFile fontSize="small" />, path: '/recordings' },
    { label: 'Settings', icon: <Settings fontSize="small" />, path: '/settings' },

];

// Sidebar background - very dark navy, like Image 2
const SIDEBAR_BG = '#0d1b2e';
const SIDEBAR_HOVER = 'rgba(255,255,255,0.07)';
const SIDEBAR_ACTIVE = 'rgba(255,255,255,0.12)';
const NAV_TEXT = 'rgba(255,255,255,0.75)';
const NAV_TEXT_ACTIVE = '#ffffff';

export default function Layout() {
    const [open, setOpen] = useState(true);
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const location = useLocation();

    return (
        <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: '#f0f4f9' }}>
            {/* Sidebar */}
            <Drawer
                variant="permanent"
                sx={{
                    width: open ? DRAWER_WIDTH : 60,
                    flexShrink: 0,
                    transition: 'width 0.25s ease',
                    '& .MuiDrawer-paper': {
                        width: open ? DRAWER_WIDTH : 60,
                        overflowX: 'hidden',
                        transition: 'width 0.25s ease',
                        bgcolor: SIDEBAR_BG,
                        border: 'none',
                        display: 'flex',
                        flexDirection: 'column',
                    },
                }}
            >
                {/* Brand header */}
                <Box sx={{
                    px: 2,
                    pt: 2,
                    pb: 1.5,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 1.2,
                    minHeight: 60,
                }}>
                    <Box sx={{
                        width: 34, height: 34,
                        borderRadius: 2,
                        background: 'linear-gradient(135deg, #0142a2, #1a6ed8)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        flexShrink: 0,
                        boxShadow: '0 2px 8px rgba(1,66,162,0.5)',
                    }}>
                        <Phone sx={{ fontSize: 17, color: '#fff' }} />
                    </Box>
                    {open && (
                        <Box>
                            <Typography sx={{ fontSize: '0.95rem', fontWeight: 700, color: '#ffffff', lineHeight: 1.1, letterSpacing: '-0.01em' }}>
                                PowerDialer
                            </Typography>
                            <Typography sx={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.45)', lineHeight: 1 }}>
                                Sales Platform
                            </Typography>
                        </Box>
                    )}
                </Box>

                {/* Create Campaign button */}
                {open && (
                    <Box sx={{ px: 1.5, pb: 1.5 }}>
                        <Button
                            fullWidth
                            variant="contained"
                            startIcon={<Add />}
                            onClick={() => navigate('/campaigns/new')}
                            sx={{
                                bgcolor: '#0142a2',
                                color: '#fff',
                                fontWeight: 700,
                                fontSize: '0.82rem',
                                borderRadius: 2,
                                py: 1,
                                textTransform: 'none',
                                boxShadow: 'none',
                                '&:hover': {
                                    bgcolor: '#1a5bc4',
                                    boxShadow: '0 4px 12px rgba(1,66,162,0.4)',
                                },
                            }}
                        >
                            Create Campaign
                        </Button>
                    </Box>
                )}

                {/* Nav */}
                <List sx={{ flex: 1, px: 1, pt: 0.5, pb: 1 }}>
                    {nav.map(({ label, icon, path }) => {
                        const active = location.pathname === path || location.pathname.startsWith(path + '/');
                        return (
                            <ListItem key={path} disablePadding sx={{ mb: 0.25 }}>
                                <Tooltip title={!open ? label : ''} placement="right">
                                    <ListItemButton
                                        onClick={() => navigate(path)}
                                        sx={{
                                            borderRadius: 1.5,
                                            minHeight: 38,
                                            px: open ? 1.5 : 1,
                                            py: 0.75,
                                            position: 'relative',
                                            bgcolor: active ? SIDEBAR_ACTIVE : 'transparent',
                                            '&:hover': { bgcolor: active ? SIDEBAR_ACTIVE : SIDEBAR_HOVER },
                                            transition: 'background 150ms ease',
                                        }}
                                    >
                                        {/* Active left indicator */}
                                        {active && (
                                            <Box sx={{
                                                position: 'absolute',
                                                left: 0, top: 6, bottom: 6,
                                                width: 3,
                                                borderRadius: '0 2px 2px 0',
                                                bgcolor: '#4d9fff',
                                            }} />
                                        )}
                                        <ListItemIcon sx={{
                                            minWidth: open ? 32 : 'auto',
                                            color: active ? NAV_TEXT_ACTIVE : NAV_TEXT,
                                            justifyContent: 'center',
                                        }}>
                                            {icon}
                                        </ListItemIcon>
                                        {open && (
                                            <ListItemText
                                                primary={label}
                                                primaryTypographyProps={{
                                                    fontSize: '0.85rem',
                                                    fontWeight: active ? 600 : 400,
                                                    color: active ? NAV_TEXT_ACTIVE : NAV_TEXT,
                                                    letterSpacing: '0.01em',
                                                }}
                                            />
                                        )}
                                    </ListItemButton>
                                </Tooltip>
                            </ListItem>
                        );
                    })}
                </List>

                <Divider sx={{ borderColor: 'rgba(255,255,255,0.08)' }} />

                {/* User section */}
                <Box sx={{ p: 1.5 }}>
                    {open ? (
                        <Box sx={{
                            display: 'flex', alignItems: 'center', gap: 1.2,
                            p: 1.2, borderRadius: 2,
                            bgcolor: 'rgba(255,255,255,0.07)',
                            cursor: 'default',
                        }}>
                            <Avatar sx={{
                                width: 30, height: 30,
                                bgcolor: '#0142a2',
                                fontSize: '0.8rem',
                                color: '#fff',
                                fontWeight: 700,
                                flexShrink: 0,
                            }}>
                                {user?.full_name?.[0] || user?.username?.[0]}
                            </Avatar>
                            <Box flex={1} minWidth={0}>
                                <Typography fontSize="0.78rem" fontWeight={600} sx={{ color: '#fff', lineHeight: 1.2 }} noWrap>
                                    {user?.full_name || user?.username}
                                </Typography>
                                <Typography fontSize="0.65rem" sx={{ color: 'rgba(255,255,255,0.5)', textTransform: 'capitalize' }}>
                                    {user?.role}
                                </Typography>
                            </Box>
                            <Tooltip title="Logout">
                                <IconButton
                                    size="small"
                                    onClick={logout}
                                    sx={{
                                        color: 'rgba(255,255,255,0.5)',
                                        width: 28, height: 28,
                                        '&:hover': { color: '#fff', bgcolor: 'rgba(255,255,255,0.1)' },
                                    }}
                                >
                                    <PowerSettingsNew sx={{ fontSize: 16 }} />
                                </IconButton>
                            </Tooltip>
                        </Box>
                    ) : (
                        <Tooltip title={user?.full_name || 'Logout'} placement="right">
                            <Avatar
                                onClick={logout}
                                sx={{
                                    width: 34, height: 34,
                                    bgcolor: '#0142a2',
                                    fontSize: '0.85rem',
                                    cursor: 'pointer',
                                    mx: 'auto',
                                    color: '#fff',
                                    fontWeight: 700,
                                }}
                            >
                                {user?.full_name?.[0] || user?.username?.[0]}
                            </Avatar>
                        </Tooltip>
                    )}
                </Box>
            </Drawer>

            {/* Main content area */}
            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
                {/* Top bar */}
                <AppBar position="static" elevation={0} sx={{
                    bgcolor: '#ffffff',
                    borderBottom: '1px solid #e2e8f0',
                    boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
                }}>
                    <Toolbar sx={{ gap: 1, minHeight: '56px !important', px: 2 }}>
                        <IconButton
                            onClick={() => setOpen(!open)}
                            size="small"
                            sx={{
                                color: '#64748b',
                                '&:hover': { bgcolor: 'rgba(1,66,162,0.06)', color: '#0142a2' },
                            }}
                        >
                            {open ? <ChevronLeft fontSize="small" /> : <Menu fontSize="small" />}
                        </IconButton>
                        <Box flex={1} />
                        {/* System status */}
                        <Box sx={{
                            display: 'flex', alignItems: 'center', gap: 0.6,
                            px: 1.5, py: 0.5, borderRadius: 2,
                            bgcolor: 'rgba(5,150,105,0.08)',
                            border: '1px solid rgba(5,150,105,0.18)',
                        }}>
                            <Circle sx={{ fontSize: 7, color: '#059669' }} />
                            <Typography variant="caption" sx={{ color: '#059669', fontWeight: 700, fontSize: '0.72rem' }}>
                                System Online
                            </Typography>
                        </Box>
                        <IconButton
                            size="small"
                            sx={{ color: '#64748b', '&:hover': { color: '#0142a2', bgcolor: 'rgba(1,66,162,0.06)' } }}
                        >
                            <Badge badgeContent={0} color="error">
                                <Notifications fontSize="small" />
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
