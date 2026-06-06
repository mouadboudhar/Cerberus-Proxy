import { useState } from 'react';
import TopBar from '../components/TopBar';
import { useApp } from '../context/AppContext';

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

/* ── One-time key reveal ───────────────────────────── */
function RevealPanel({ keyValue, onDone }) {
  const [saved,  setSaved]  = useState(false);
  const [copied, setCopied] = useState(false);

  async function copy() {
    try { await navigator.clipboard.writeText(keyValue); } catch { /* ignore */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }

  return (
    <div className="reveal-card">
      <div className="reveal-bar" />
      <div className="reveal-body">
        <div className="reveal-head">
          <span className="warn-glyph">⚠</span>
          <div>
            <h3>Your new API key — save this now</h3>
            <p>This key will never be shown again after you close this panel.</p>
          </div>
        </div>

        <div className="reveal-key">
          <code>{keyValue}</code>
          <button
            className={`lg-btn${copied ? ' copied' : ''}`}
            onClick={copy}
            style={copied ? { color: 'var(--v-green)', borderColor: 'var(--v-green)' } : {}}
          >
            {copied ? '✓ Copied' : '⎘ Copy'}
          </button>
        </div>

        <label className="reveal-check">
          <input type="checkbox" checked={saved} onChange={e => setSaved(e.target.checked)} />
          <span className="custom-check" />
          I have saved this key somewhere safe
        </label>

        <div className="flex justify-end">
          <button className="lg-btn primary" disabled={!saved} onClick={onDone}>Done</button>
        </div>
      </div>
    </div>
  );
}

/* ── Create key modal ──────────────────────────────── */
function CreateModal({ endpoints, onClose, onCreate }) {
  const [name, setName] = useState('');
  const [endpointId, setEndpointId] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function submit() {
    if (!name.trim() || busy) return;
    setBusy(true); setErr('');
    try {
      await onCreate({ name: name.trim(), endpoint_id: endpointId ? Number(endpointId) : null });
    } catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div className="lg-modal-backdrop" onClick={onClose}>
      <div className="lg-modal" onClick={e => e.stopPropagation()}>
        <div className="flex items-start gap-4 px-5 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
          <div>
            <h3 className="m-0 font-semibold" style={{ fontSize: '15px', color: 'var(--text)' }}>Create API Key</h3>
            <p className="m-0 mt-0.5 text-sm" style={{ color: 'var(--text-3)' }}>
              The plaintext key is shown once on creation. Only its hash is stored.
            </p>
          </div>
          <button
            onClick={onClose}
            className="ml-auto w-6 h-6 grid place-items-center text-[13px]"
            style={{ color: 'var(--text-3)' }}
          >✕</button>
        </div>

        <div style={{ padding: '6px 20px 16px' }}>
          {err && <div className="text-[11.5px] px-3 py-2 mt-3" style={{ border: '1px solid var(--v-red)', color: 'var(--v-red)' }}>{err}</div>}
          <div className="flex flex-col gap-1.5 mt-3">
            <label className="text-[11px] font-semibold tracking-[0.1em] uppercase" style={{ color: 'var(--text-3)' }}>
              Name <span style={{ color: 'var(--v-red)' }}>*</span>
            </label>
            <input className="lg-input" placeholder="e.g. mobile-app-prod" value={name} onChange={e => setName(e.target.value)} autoFocus />
          </div>
          <div className="flex flex-col gap-1.5 mt-4">
            <label className="text-[11px] font-semibold tracking-[0.1em] uppercase" style={{ color: 'var(--text-3)' }}>Endpoint (optional)</label>
            <select className="lg-select" value={endpointId} onChange={e => setEndpointId(e.target.value)}>
              <option value="">— none —</option>
              {endpoints.map(ep => <option key={ep.id} value={ep.id}>{ep.name}</option>)}
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2 px-5 py-[14px]" style={{ borderTop: '1px solid var(--border)' }}>
          <button className="lg-btn" onClick={onClose}>Cancel</button>
          <button className="lg-btn primary" disabled={!name.trim() || busy} onClick={submit}>
            {busy ? 'Creating…' : 'Create key'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── Page ──────────────────────────────────────────── */
export default function ApiKeysPage() {
  const { keys, endpoints, createKey, revokeKey } = useApp();
  const [showCreate, setShowCreate] = useState(false);
  const [newKey, setNewKey] = useState(null);

  const activeCount  = keys.filter(k => k.is_active).length;
  const revokedCount = keys.filter(k => !k.is_active).length;

  async function handleCreate(body) {
    const created = await createKey(body);
    setShowCreate(false);
    if (created?.key) setNewKey(created.key);
  }

  return (
    <>
      <TopBar title="API Keys" />

      <div className="flex-1 overflow-y-auto" style={{ padding: '24px 28px 32px' }}>
        <div className="flex items-baseline gap-3 mb-4 flex-wrap">
          <h2 className="m-0 font-semibold" style={{ fontSize: '20px', letterSpacing: '-0.01em', color: 'var(--text)' }}>API Keys</h2>
          <span className="font-mono text-[11.5px]" style={{ color: 'var(--text-3)' }}>
            {activeCount} active · {revokedCount} revoked
          </span>
          <span className="flex-1" />
          <button className="lg-btn primary" onClick={() => setShowCreate(true)}>+ Create Key</button>
        </div>

        {newKey && <RevealPanel keyValue={newKey} onDone={() => setNewKey(null)} />}

        <div className="lg-card" style={{ marginTop: newKey ? 14 : 0 }}>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Name</th><th>Key</th><th>Endpoint</th><th>Created</th><th>Last used</th><th>Status</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {keys.map(k => (
                  <tr key={k.id} className={!k.is_active ? 'is-muted' : ''}>
                    <td><span className="font-medium" style={{ color: 'var(--text)', fontWeight: 600 }}>{k.name}</span></td>
                    <td><code className="mono-pill">cbrs_••••••••••••</code></td>
                    <td>
                      <span className="ep-pill">
                        <span className="ep-dot-sm" style={{ background: k.endpoint_id != null ? 'var(--accent)' : 'var(--text-4)' }} />
                        {k.endpoint_name || '—'}
                      </span>
                    </td>
                    <td className="muted-cell">{fmtDate(k.created_at)}</td>
                    <td className="muted-cell">{fmtDate(k.last_used_at)}</td>
                    <td>
                      <span className={`status-pill ${k.is_active ? 'active' : 'revoked'}`}>
                        {k.is_active ? 'Active' : 'Revoked'}
                      </span>
                    </td>
                    <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                      {k.is_active && (
                        <button className="link-danger" onClick={() => revokeKey(k.id)}>Revoke</button>
                      )}
                    </td>
                  </tr>
                ))}
                {keys.length === 0 && (
                  <tr><td colSpan={7} className="muted-cell" style={{ padding: '18px' }}>No API keys yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {showCreate && (
        <CreateModal endpoints={endpoints} onClose={() => setShowCreate(false)} onCreate={handleCreate} />
      )}
    </>
  );
}
