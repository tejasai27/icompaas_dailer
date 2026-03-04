import { useEffect, useState } from 'react';
import AuthContext from './authContext';
import api from '../services/api';

const DEFAULT_USER = { username: 'demo', full_name: 'Demo User', role: 'admin' };

export default function AuthProvider({ children }) {
    const [user, setUser] = useState(DEFAULT_USER);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        try {
            const token = localStorage.getItem('access_token');
            const savedUser = localStorage.getItem('user');
            if (token && savedUser) {
                const parsedUser = JSON.parse(savedUser);
                if (parsedUser && typeof parsedUser === 'object') {
                    setUser(parsedUser);
                } else {
                    localStorage.removeItem('user');
                    setUser(DEFAULT_USER);
                }
            } else {
                setUser(DEFAULT_USER);
            }
        } catch {
            localStorage.removeItem('user');
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            setUser(DEFAULT_USER);
        }
        setLoading(false);
    }, []);

    const login = async (username, password) => {
        const { data } = await api.post('/auth/login/', { username, password });
        localStorage.setItem('access_token', data.access);
        localStorage.setItem('refresh_token', data.refresh);
        localStorage.setItem('user', JSON.stringify(data.user));
        setUser(data.user);
        return data.user;
    };

    const logout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        setUser(DEFAULT_USER);
    };

    return (
        <AuthContext.Provider value={{ user, login, logout, loading }}>
            {children}
        </AuthContext.Provider>
    );
}
