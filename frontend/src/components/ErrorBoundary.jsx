import React from 'react';
import { Box, Button, Typography } from '@mui/material';

export default class ErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, info) {
        console.error('ErrorBoundary caught:', error, info.componentStack);
    }

    render() {
        if (this.state.hasError) {
            return (
                <Box sx={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center',
                    justifyContent: 'center', minHeight: '100vh', p: 4, textAlign: 'center',
                }}>
                    <Typography variant="h4" fontWeight={700} sx={{ mb: 1, color: '#0f172a' }}>
                        Something went wrong
                    </Typography>
                    <Typography color="text.secondary" sx={{ mb: 3, maxWidth: 480 }}>
                        An unexpected error occurred. Please reload the page or go back to the dashboard.
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 2 }}>
                        <Button
                            variant="contained"
                            onClick={() => window.location.reload()}
                            sx={{ bgcolor: '#0142a2' }}
                        >
                            Reload Page
                        </Button>
                        <Button
                            variant="outlined"
                            onClick={() => {
                                this.setState({ hasError: false, error: null });
                                window.location.href = '/dashboard';
                            }}
                            sx={{ borderColor: '#0142a2', color: '#0142a2' }}
                        >
                            Go to Dashboard
                        </Button>
                    </Box>
                </Box>
            );
        }

        return this.props.children;
    }
}
