import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider, createTheme } from '@mui/material/styles';
import CssBaseline from '@mui/material/CssBaseline';
import { Toaster } from 'react-hot-toast';
import AuthProvider from './context/AuthProvider';
import Layout from './components/Layout';
import DashboardPage from './pages/DashboardPage';
import CampaignsPage from './pages/CampaignsPage';
import CampaignCreatePage from './pages/CampaignCreatePage';
import CampaignDetailPage from './pages/CampaignDetailPage';
import ContactsPage from './pages/ContactsPage';
import DialPage from './pages/DialPage';
import DialCallPage from './pages/DialCallPage';
import CallLogsPage from './pages/CallLogsPage';
import CallRecordingsPage from './pages/CallRecordingsPage';
import RecordingTranscriptPage from './pages/RecordingTranscriptPage';
import SettingsPage from './pages/SettingsPage';
import IntegrationsPage from './pages/IntegrationsPage';
import HubspotRecordsPage from './pages/HubspotRecordsPage';
import SalesfloorPage from './pages/SalesfloorPage';
import SdrsPage from './pages/SdrsPage';

const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#0142a2', light: '#1a5bc4', dark: '#012f7a', contrastText: '#ffffff' },
    secondary: { main: '#0d9488', light: '#14b8a6', dark: '#0f766e', contrastText: '#ffffff' },
    error: { main: '#dc2626' },
    warning: { main: '#d97706' },
    info: { main: '#0142a2' },
    success: { main: '#059669' },
    background: { default: '#f0f4f9', paper: '#ffffff' },
    text: { primary: '#0f172a', secondary: '#64748b' },
    divider: '#e2e8f0',
  },
  typography: {
    fontFamily: '"Inter", "DM Sans", "Roboto", "Helvetica", "Arial", sans-serif',
    h1: { fontWeight: 800 },
    h2: { fontWeight: 700 },
    h3: { fontWeight: 700 },
    h4: { fontWeight: 700 },
    h5: { fontWeight: 600 },
    h6: { fontWeight: 600 },
  },
  shape: { borderRadius: 10 },
  shadows: [
    'none',
    '0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04)',
    '0 2px 6px rgba(0,0,0,0.07)',
    '0 4px 12px rgba(0,0,0,0.08)',
    '0 6px 16px rgba(0,0,0,0.08)',
    '0 8px 24px rgba(0,0,0,0.09)',
    '0 8px 24px rgba(0,0,0,0.09)',
    '0 8px 24px rgba(0,0,0,0.09)',
    '0 8px 24px rgba(0,0,0,0.09)',
    '0 12px 32px rgba(0,0,0,0.1)',
    '0 12px 32px rgba(0,0,0,0.1)',
    '0 12px 32px rgba(0,0,0,0.1)',
    '0 12px 32px rgba(0,0,0,0.1)',
    '0 16px 40px rgba(0,0,0,0.12)',
    '0 16px 40px rgba(0,0,0,0.12)',
    '0 16px 40px rgba(0,0,0,0.12)',
    '0 16px 40px rgba(0,0,0,0.12)',
    '0 20px 48px rgba(0,0,0,0.13)',
    '0 20px 48px rgba(0,0,0,0.13)',
    '0 20px 48px rgba(0,0,0,0.13)',
    '0 20px 48px rgba(0,0,0,0.13)',
    '0 24px 56px rgba(0,0,0,0.14)',
    '0 24px 56px rgba(0,0,0,0.14)',
    '0 24px 56px rgba(0,0,0,0.14)',
    '0 24px 56px rgba(0,0,0,0.14)',
  ],
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: '#f0f4f9',
          color: '#0f172a',
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          backgroundColor: '#ffffff',
          border: '1px solid #e2e8f0',
          boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
          borderRadius: 12,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 600,
          borderRadius: 8,
          boxShadow: 'none',
          '&:hover': { boxShadow: 'none' },
        },
        containedPrimary: {
          background: '#0142a2',
          '&:hover': { background: '#1a5bc4' },
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 6, fontWeight: 600 },
      },
    },
    MuiTableHead: {
      styleOverrides: {
        root: {
          '& .MuiTableCell-root': {
            backgroundColor: '#f0f4f9',
            fontWeight: 700,
            fontSize: '0.72rem',
            textTransform: 'uppercase',
            letterSpacing: '0.07em',
            color: '#64748b',
            borderBottom: '1px solid #e2e8f0',
          },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: '1px solid #e2e8f0',
          color: '#0f172a',
        },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: {
          '&:hover': { backgroundColor: 'rgba(1, 66, 162, 0.04)' },
        },
      },
    },
    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiOutlinedInput-root': {
            borderRadius: 8,
            backgroundColor: '#ffffff',
            '& fieldset': { borderColor: '#cbd5e1' },
            '&:hover fieldset': { borderColor: '#0142a2' },
            '&.Mui-focused fieldset': { borderColor: '#0142a2', borderWidth: 2 },
          },
          '& .MuiInputLabel-root.Mui-focused': { color: '#0142a2' },
        },
      },
    },
    MuiSelect: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          backgroundColor: '#ffffff',
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: { borderColor: '#e2e8f0' },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: '#ffffff',
          color: '#0f172a',
          boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
          borderBottom: '1px solid #e2e8f0',
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: '#0142a2',
          borderRight: 'none',
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 8,
          '&.Mui-selected': {
            backgroundColor: 'rgba(255,255,255,0.18)',
            '&:hover': { backgroundColor: 'rgba(255,255,255,0.22)' },
          },
          '&:hover': { backgroundColor: 'rgba(255,255,255,0.1)' },
        },
      },
    },
    MuiListItemIcon: {
      styleOverrides: {
        root: { color: 'rgba(255,255,255,0.75)', minWidth: 40 },
      },
    },
    MuiListItemText: {
      styleOverrides: {
        primary: { color: 'rgba(255,255,255,0.9)', fontSize: '0.875rem' },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: { borderRadius: 8 },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: '#0f172a',
          fontSize: '0.75rem',
          borderRadius: 6,
        },
      },
    },
    MuiSkeleton: {
      styleOverrides: {
        root: { backgroundColor: '#e2e8f0' },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 10 },
      },
    },
  },
});

function App() {
  return (
    <ThemeProvider theme={lightTheme}>
      <CssBaseline />
      <AuthProvider>
        <BrowserRouter>
          <Toaster
            position="top-right"
            toastOptions={{
              style: {
                background: '#ffffff',
                color: '#0f172a',
                border: '1px solid #e2e8f0',
                boxShadow: '0 4px 16px rgba(0,0,0,0.1)',
                borderRadius: 10,
                fontSize: '0.875rem',
              },
              success: { iconTheme: { primary: '#059669', secondary: '#fff' } },
              error: { iconTheme: { primary: '#dc2626', secondary: '#fff' } },
            }}
          />
          <Routes>
            <Route path="/login" element={<Navigate to="/dashboard" replace />} />
            <Route path="/" element={<Layout />}>
              <Route index element={<Navigate to="/dashboard" replace />} />
              <Route path="dashboard" element={<DashboardPage />} />
              <Route path="dial" element={<DialPage />} />
              <Route path="dial/call/:callPublicId" element={<DialCallPage />} />
              <Route path="campaigns" element={<CampaignsPage />} />
              <Route path="campaigns/new" element={<CampaignCreatePage />} />
              <Route path="campaigns/:id" element={<CampaignDetailPage />} />
              <Route path="salesfloor" element={<SalesfloorPage />} />
              <Route path="sdrs" element={<SdrsPage />} />
              <Route path="contacts" element={<ContactsPage />} />
              <Route path="call-logs" element={<CallLogsPage />} />
              <Route path="recordings" element={<CallRecordingsPage />} />
              <Route path="recordings/:recordingPublicId/transcript" element={<RecordingTranscriptPage />} />
              <Route path="integrations" element={<IntegrationsPage />} />
              <Route path="hubspot-records" element={<HubspotRecordsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
