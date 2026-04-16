import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api, { setToken, setTokens, refreshAccessToken, getRefreshToken } from './api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, _setToken] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  // Sync tokens to api module whenever they change
  const applyTokens = useCallback((accessToken, refreshToken) => {
    _setToken(accessToken);
    setTokens(accessToken, refreshToken);
  }, []);

  // On first mount, try to restore from sessionStorage
  useEffect(() => {
    const savedToken = sessionStorage.getItem('token');
    const savedRefresh = sessionStorage.getItem('refreshToken');
    if (savedToken) {
      applyTokens(savedToken, savedRefresh);
      api.get('/api/auth/me')
        .then(u => setUser(u))
        .catch(async () => {
          // Access token may be expired — try refreshing
          if (savedRefresh) {
            setTokens(null, savedRefresh);
            const refreshed = await refreshAccessToken();
            if (refreshed) {
              try {
                const u = await api.get('/api/auth/me');
                setUser(u);
                _setToken(sessionStorage.getItem('token'));
                return;
              } catch {
                // fall through to logout
              }
            }
          }
          sessionStorage.removeItem('token');
          sessionStorage.removeItem('refreshToken');
          applyTokens(null, null);
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [applyTokens]);

  // Listen for 401 events from the API module
  useEffect(() => {
    const handler = () => logout();
    window.addEventListener('auth:unauthorized', handler);
    return () => window.removeEventListener('auth:unauthorized', handler);
  });

  async function login(username, password) {
    const data = await api.login(username, password);
    applyTokens(data.access_token, data.refresh_token);
    sessionStorage.setItem('token', data.access_token);
    if (data.refresh_token) {
      sessionStorage.setItem('refreshToken', data.refresh_token);
    }
    const me = await api.get('/api/auth/me');
    setUser(me);
    return me;
  }

  async function register(username, displayName, email, password) {
    const regResult = await api.post('/api/auth/register', {
      username,
      display_name: displayName,
      email,
      password,
    });
    const me = await login(username, password);
    // Return both user and registration metadata
    return { ...me, is_first_user: regResult.is_first_user || false };
  }

  async function logout() {
    try {
      await api.logout();
    } catch {
      // ignore
    }
    applyTokens(null, null);
    sessionStorage.removeItem('token');
    sessionStorage.removeItem('refreshToken');
    setUser(null);
    navigate('/login');
  }

  // Refresh user data (e.g., after email verification)
  async function refreshUser() {
    try {
      const me = await api.get('/api/auth/me');
      setUser(me);
    } catch {
      // ignore
    }
  }

  return (
    <AuthContext.Provider value={{ user, token, loading, login, register, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
