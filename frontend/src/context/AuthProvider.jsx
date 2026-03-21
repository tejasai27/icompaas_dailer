import { useEffect, useState, useCallback } from 'react';
import AuthContext from './authContext';
import api from '../services/api';

export default function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    // Fetch current user from /auth/me/ (cookie-based auth)
    const fetchUser = useCallback(async () => {
        try {
            const { data } = await api.get('/auth/me/');
            setUser(data.user);
        } catch {
            setUser(null);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        fetchUser();
    }, [fetchUser]);

    const login = async (username, password) => {
        const { data } = await api.post('/auth/login/', { username, password });
        setUser(data.user);
        return data.user;
    };

    const logout = async () => {
        try {
            await api.post('/auth/logout/');
        } catch {
            // Even if logout API fails, clear local state
        }
        setUser(null);
    };

    return (
        <AuthContext.Provider value={{ user, login, logout, loading }}>
            {children}
        </AuthContext.Provider>
    );
}
