import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiRequest, setToken } from '../hooks/useApi';

export default function LoginPage() {
  const navigate = useNavigate();
  const [token, setTokenInput] = useState('');
  const [error, setError]      = useState('');
  const [busy, setBusy]        = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!token.trim()) {
      setError('Dashboard token is required.');
      return;
    }
    setBusy(true);
    setError('');
    // Stash the token first so apiRequest sends X-Dashboard-Token on /verify.
    setToken(token.trim());
    try {
      await apiRequest('/api/auth/verify', { method: 'POST', body: { token: token.trim() } });
      navigate('/overview');
    } catch {
      localStorage.removeItem('cbrs_token');
      setError('Invalid dashboard token.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-4"
      style={{ background: 'var(--bg)' }}
    >
      {/* Card */}
      <div
        className="w-full flex flex-col"
        style={{
          maxWidth: '360px',
          background: 'var(--bg-1)',
          border: '1px solid var(--border)',
        }}
      >
        {/* Brand */}
        <div
          className="flex flex-col items-center gap-3 px-8 pt-8 pb-6"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div className="logo-mark" style={{ width: '28px', height: '28px' }} />
          <div className="text-center">
            <div
              className="font-semibold"
              style={{ fontSize: '17px', letterSpacing: '-0.01em', color: 'var(--text)' }}
            >
              Cerberus Proxy
            </div>
            <div className="mt-1 text-[11.5px]" style={{ color: 'var(--text-3)' }}>
              Enterprise Security Gateway
            </div>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-8 py-6" noValidate>
          {error && (
            <div
              className="text-[11.5px] px-3 py-2"
              style={{
                border: '1px solid color-mix(in oklab, var(--v-red) 40%, var(--border))',
                background: 'color-mix(in oklab, var(--v-red) 8%, transparent)',
                color: 'var(--v-red)',
              }}
            >
              {error}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="token"
              className="text-[11px] font-semibold tracking-[0.08em] uppercase"
              style={{ color: 'var(--text-3)' }}
            >
              Dashboard Token
            </label>
            <input
              id="token"
              type="password"
              autoComplete="current-password"
              className="lg-input"
              placeholder="••••••••••••••••"
              value={token}
              onChange={e => { setTokenInput(e.target.value); setError(''); }}
              autoFocus
            />
          </div>

          <button
            type="submit"
            className="lg-btn primary w-full justify-center mt-1"
            style={{ paddingTop: '9px', paddingBottom: '9px', fontSize: '13px' }}
            disabled={busy}
          >
            {busy ? 'Verifying…' : 'Sign in'}
          </button>

          <div className="text-center text-[11px]" style={{ color: 'var(--text-4)' }}>
            Set via <code className="font-mono">CERBERUS_DASHBOARD_TOKEN</code>
          </div>
        </form>
      </div>

      <div className="mt-6 text-[11px]" style={{ color: 'var(--text-4)' }}>
        Self-hosted · v0.5.0 · acme-prod
      </div>
    </div>
  );
}
