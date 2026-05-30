import { useState } from 'react';
import TopBar from '../components/TopBar';
import Switch from '../components/Switch';
import { useApp } from '../context/AppContext';

function fmtUptime(seconds) {
  if (seconds == null) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  return `${d} days, ${h} hours`;
}
function fmtBytes(bytes) {
  if (bytes == null) return '—';
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(1)} KB`;
  return `${bytes} B`;
}

function CardH3({ children }) {
  return (
    <h3 style={{
      margin: 0, padding: '14px 18px',
      borderBottom: '1px solid var(--border)',
      fontSize: '13px', fontWeight: 600, color: 'var(--text)',
      display: 'flex', alignItems: 'center', gap: 8,
    }}>
      {children}
    </h3>
  );
}

function SettingField({ label, children }) {
  return (
    <div className="acct-field">
      <span className="lbl">{label}</span>
      {children}
    </div>
  );
}

export default function SettingsPage() {
  const { serverInfo } = useApp();
  const [retention, setRetention] = useState(90);
  const [rpm, setRpm] = useState(100);
  const [rph, setRph] = useState(2000);
  const [tpd, setTpd] = useState(500000);
  const [notifOn, setNotifOn] = useState(false);

  return (
    <>
      <TopBar title="Settings" />

      <div className="flex-1 overflow-y-auto" style={{ padding: '24px 28px 32px', maxWidth: '720px' }}>
        <h2
          className="m-0 mb-4 font-semibold"
          style={{ fontSize: '20px', letterSpacing: '-0.01em', color: 'var(--text)' }}
        >
          Settings
        </h2>

        {/* Server */}
        <div className="lg-card">
          <CardH3>Server</CardH3>
          <div className="card-body">
            <SettingField label="Version">
              <code className="font-mono text-sm" style={{ color: 'var(--text)' }}>
                v{serverInfo?.version ?? '—'}
              </code>
            </SettingField>
            <SettingField label="Uptime">
              <span className="val">{fmtUptime(serverInfo?.uptime_seconds)}</span>
            </SettingField>
            <SettingField label="Database">
              <span className="val">SQLite · {fmtBytes(serverInfo?.database_size_bytes)}</span>
            </SettingField>
            <SettingField label="Log retention">
              <span className="flex items-center gap-2">
                <input
                  className="lg-input"
                  type="number"
                  value={retention}
                  onChange={e => setRetention(parseInt(e.target.value || 0))}
                  style={{ width: 90 }}
                />
                <span className="text-sm" style={{ color: 'var(--text-3)' }}>days</span>
              </span>
            </SettingField>
          </div>
        </div>

        {/* Default rate limits */}
        <div className="lg-card" style={{ marginTop: 16 }}>
          <CardH3>Default Rate Limits</CardH3>
          <div className="card-body">
            <p className="text-sm mt-3 mb-0" style={{ color: 'var(--text-3)' }}>
              Applied to new API keys unless overridden per-key.
            </p>
            <SettingField label="Requests per minute">
              <span className="flex items-center gap-2">
                <input className="lg-input" type="number" value={rpm} onChange={e => setRpm(parseInt(e.target.value || 0))} style={{ width: 110 }} />
                <span className="text-sm" style={{ color: 'var(--text-3)' }}>/min</span>
              </span>
            </SettingField>
            <SettingField label="Requests per hour">
              <span className="flex items-center gap-2">
                <input className="lg-input" type="number" value={rph} onChange={e => setRph(parseInt(e.target.value || 0))} style={{ width: 110 }} />
                <span className="text-sm" style={{ color: 'var(--text-3)' }}>/hr</span>
              </span>
            </SettingField>
            <SettingField label="Max tokens per day">
              <span className="flex items-center gap-2">
                <input className="lg-input" type="number" value={tpd} onChange={e => setTpd(parseInt(e.target.value || 0))} style={{ width: 110 }} />
                <span className="text-sm" style={{ color: 'var(--text-3)' }}>tokens / day</span>
              </span>
            </SettingField>
          </div>
          <div className="btn-row">
            <button className="lg-btn primary">Save defaults</button>
          </div>
        </div>

        {/* Notifications (v1.1 — disabled) */}
        <div className="lg-card" style={{ marginTop: 16 }}>
          <CardH3>
            Notifications
            <span className="future-pill">v1.1</span>
          </CardH3>
          <div style={{ opacity: 0.55, pointerEvents: 'none' }}>
            <div className="acct-field">
              <span className="lbl">Webhook URL</span>
              <input
                className="lg-input"
                placeholder="https://hooks.your-org.com/cerberus_proxy"
                disabled
              />
            </div>
            <div className="acct-field">
              <span className="lbl">Email alerts on CRITICAL</span>
              <Switch on={notifOn} onToggle={() => setNotifOn(v => !v)} />
            </div>
            <div className="acct-field" style={{ borderBottom: 0 }}>
              <span className="lbl">Slack integration</span>
              <span className="val">Not connected</span>
            </div>
          </div>
        </div>

        {/* Danger zone */}
        <div className="lg-card danger-card" style={{ marginTop: 16, marginBottom: 16 }}>
          <CardH3 style={{ color: 'var(--v-red)' }}>
            <span style={{ color: 'var(--v-red)' }}>Danger Zone</span>
          </CardH3>
          <div className="danger-row">
            <div>
              <div className="name">Reset all rate-limit counters</div>
              <div className="desc">
                Clears the per-key request counters for all endpoints.
                Subsequent requests start from zero.{' '}
                <strong>Cannot be undone.</strong>
              </div>
            </div>
            <button className="lg-btn danger-outline">Reset counters</button>
          </div>
          <div className="danger-row">
            <div>
              <div className="name">Wipe all audit logs</div>
              <div className="desc">
                Permanently deletes every recorded event. Compliance reports
                relying on this data will be lost.{' '}
                <strong>Cannot be undone.</strong>
              </div>
            </div>
            <button className="lg-btn danger-outline">Wipe logs</button>
          </div>
        </div>
      </div>
    </>
  );
}
