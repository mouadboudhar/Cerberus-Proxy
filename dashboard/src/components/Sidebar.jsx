import { useNavigate, useLocation } from 'react-router-dom';
import { useTheme } from '../context/ThemeContext';
import { useApp } from '../context/AppContext';
import { formatNum } from '../data';

const NAV_ITEMS = [
  { id: 'overview',  path: '/overview',  label: 'Overview',     icon: '◇' },
  { id: 'endpoints', path: '/endpoints', label: 'Endpoints',    icon: '⊟' },
  { id: 'keys',      path: '/keys',      label: 'API Keys',     icon: '◷' },
  { id: 'audit',     path: '/audit',     label: 'Audit Log',    icon: '≡' },
  { id: 'guards',    path: '/guards',    label: 'Guard Config', icon: '◈' },
  { id: 'account',   path: '/account',   label: 'Account',      icon: '◐' },
  { id: 'settings',  path: '/settings',  label: 'Settings',     icon: '⚙' },
];

export default function Sidebar() {
  const navigate  = useNavigate();
  const location  = useLocation();
  const { theme, setTheme } = useTheme();
  const { endpoints, keys, events } = useApp();

  const activePath = location.pathname;
  const keysPreview = keys.slice(0, 4);

  return (
    <aside
      className="flex flex-col overflow-hidden"
      style={{
        width: 'var(--sidebar-w)',
        background: 'var(--bg-1)',
        borderRight: '1px solid var(--border)',
      }}
    >
      {/* Brand header */}
      <div
        className="flex items-center gap-[10px] px-4 flex-shrink-0"
        style={{ height: 'var(--header-h)', borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-[9px] flex-1 min-w-0">
          <div className="logo-mark" />
          <span
            className="font-semibold text-md truncate"
            style={{ letterSpacing: '-0.01em', color: 'var(--text)' }}
          >
            Cerberus Proxy
          </span>
        </div>
        <span
          className="font-mono text-[10.5px] tracking-[0.04em] flex-shrink-0"
          style={{ color: 'var(--text-3)' }}
        >
          acme-prod
        </span>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">

        {/* Navigation */}
        <section style={{ borderBottom: '1px solid var(--border)', padding: '10px 0 12px' }}>
          <div
            className="px-4 pb-[6px] pt-[6px] text-[10px] font-semibold tracking-[0.14em] uppercase select-none"
            style={{ color: 'var(--text-4)' }}
          >
            Navigation
          </div>
          <nav className="flex flex-col py-0.5">
            {NAV_ITEMS.map((item) => {
              const active = activePath === item.path || activePath.startsWith(item.path + '/');
              return (
                <button
                  key={item.id}
                  onClick={() => navigate(item.path)}
                  className="flex items-center gap-[11px] px-4 py-[7px] text-left transition-colors"
                  style={{
                    fontSize: '12.5px',
                    borderLeft: `2px solid ${active ? 'var(--accent)' : 'transparent'}`,
                    background: active ? 'var(--bg-2)' : 'transparent',
                    color: active ? 'var(--text)' : 'var(--text-2)',
                  }}
                  onMouseEnter={e => { if (!active) { e.currentTarget.style.background = 'var(--bg-2)'; e.currentTarget.style.color = 'var(--text)'; } }}
                  onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-2)'; } }}
                >
                  <span
                    className="w-[14px] h-[14px] grid place-items-center flex-shrink-0 text-[13px]"
                    style={{ color: active ? 'var(--accent)' : 'var(--text-3)' }}
                  >
                    {item.icon}
                  </span>
                  <span className="flex-1">{item.label}</span>
                  {item.id === 'audit' && events.length > 0 && (
                    <span
                      className="font-mono text-[10.5px] tracking-[0.04em]"
                      style={{ color: 'var(--text-4)' }}
                    >
                      {events.length}
                    </span>
                  )}
                </button>
              );
            })}
          </nav>
        </section>

        {/* Endpoints list */}
        <section style={{ borderBottom: '1px solid var(--border)', padding: '10px 0 12px' }}>
          <div
            className="flex items-center justify-between px-4 pb-[6px] pt-[6px] text-[10px] font-semibold tracking-[0.14em] uppercase select-none"
            style={{ color: 'var(--text-4)' }}
          >
            <span>Endpoints</span>
            <span className="font-mono text-[10px]">{endpoints.length}</span>
          </div>
          <div className="flex flex-col gap-0.5 px-2">
            {endpoints.map((ep) => (
              <button
                key={ep.id}
                onClick={() => navigate('/endpoints')}
                className="grid items-center gap-[10px] px-2 py-2 w-full text-left transition-colors hover:bg-surface-2"
                style={{ gridTemplateColumns: '8px 1fr auto', border: '1px solid transparent' }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.background = 'var(--bg-2)'; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = 'transparent'; e.currentTarget.style.background = 'transparent'; }}
              >
                <span className={`ep-dot ${ep.is_active ? 'healthy' : 'paused'}`} />
                <div className="min-w-0">
                  <div
                    className="truncate font-medium"
                    style={{ fontSize: '12.5px', color: 'var(--text)' }}
                  >
                    {ep.name}
                  </div>
                  <div className="font-mono text-[10px] mt-0.5" style={{ color: 'var(--text-3)' }}>
                    <span
                      className="uppercase tracking-[0.1em] font-semibold mr-1.5"
                      style={{ fontSize: '9.5px', color: 'var(--text-3)' }}
                    >
                      {ep.provider}
                    </span>
                  </div>
                </div>
                <div className="font-mono text-[10.5px] text-right" style={{ color: 'var(--text-3)' }}>
                  <span style={{ color: 'var(--text-2)' }}>{formatNum(ep.stats?.requests_today ?? 0)}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* API Keys list */}
        <section style={{ padding: '10px 0 12px' }}>
          <div
            className="flex items-center justify-between px-4 pb-[6px] pt-[6px] text-[10px] font-semibold tracking-[0.14em] uppercase select-none"
            style={{ color: 'var(--text-4)' }}
          >
            <span>API Keys</span>
            <span className="font-mono text-[10px]">{keys.length}</span>
          </div>
          <div className="flex flex-col px-2">
            {keysPreview.map((k) => (
              <button
                key={k.id}
                onClick={() => navigate('/keys')}
                className="flex items-baseline justify-between px-2 py-[6px] w-full text-left transition-colors"
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-2)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                <span
                  className="font-mono truncate mr-2"
                  style={{ fontSize: '11.5px', color: k.is_active ? 'var(--text)' : 'var(--text-4)', maxWidth: '150px' }}
                >
                  {k.name}
                </span>
                <span className="text-[10.5px] flex-shrink-0" style={{ color: 'var(--text-3)' }}>
                  {k.is_active ? 'active' : 'revoked'}
                </span>
              </button>
            ))}
          </div>
          <button
            onClick={() => navigate('/keys')}
            className="block px-4 pt-2 pb-1 text-[11.5px] text-left transition-colors"
            style={{ color: 'var(--accent)' }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent-2)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--accent)'; }}
          >
            Manage all keys →
          </button>
        </section>
      </div>

      {/* Footer */}
      <div
        className="flex items-center justify-between gap-2 flex-shrink-0 px-[14px] py-[10px]"
        style={{ borderTop: '1px solid var(--border)' }}
      >
        {/* Theme toggle */}
        <div
          className="inline-flex items-center overflow-hidden"
          style={{
            border: '1px solid var(--border-2)',
            background: 'var(--bg-1)',
          }}
        >
          {(['light', 'dark'] ).map((t, i) => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className="px-2 py-1 text-[11px] flex items-center gap-1 transition-colors"
              style={{
                color: theme === t ? 'var(--text)' : 'var(--text-3)',
                background: theme === t ? 'var(--bg-2)' : 'transparent',
                borderLeft: i > 0 ? '1px solid var(--border-2)' : 'none',
              }}
            >
              {t === 'light' ? '☼' : '☾'} {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {/* Version + status */}
        <div className="flex items-center gap-1.5 text-[10.5px]" style={{ color: 'var(--text-3)' }}>
          <span className="cdot" />
          <span className="font-mono">v0.5.0</span>
        </div>
      </div>
    </aside>
  );
}
