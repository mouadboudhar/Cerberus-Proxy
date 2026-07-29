import { useNavigate } from 'react-router';
import TopBar      from '../components/TopBar';
import SevBadge    from '../components/SevBadge';
import Sparkline   from '../components/Sparkline';
import GuardBarChart from '../components/GuardBarChart';
import { useEventStream } from '../hooks/useEventStream';
import { useApp } from '../context/AppContext';
import { useApi } from '../hooks/useApi';
import { formatNum } from '../data';

/* Derive live guard-activity buckets from the recent event buffer. */
function computeGuardActivity(events) {
  const N = 12;
  const ordered = [...events].reverse(); // oldest -> newest
  const mk = () => ({ passed: Array(N).fill(0), blocked: Array(N).fill(0) });
  const input = mk();
  const output = mk();
  if (ordered.length === 0) return { input: null, output: null };
  ordered.forEach((e, idx) => {
    const b = Math.min(N - 1, Math.floor((idx / ordered.length) * N));
    if (e.type === 'INPUT_GUARD_PASSED') input.passed[b] += 1;
    else if (e.type === 'INPUT_GUARD_BLOCKED') input.blocked[b] += 1;
    else if (e.type === 'OUTPUT_GUARD_PASSED') output.passed[b] += 1;
    else if (e.type === 'OUTPUT_GUARD_BLOCKED' || e.type === 'OUTPUT_GUARD_REDACTED') output.blocked[b] += 1;
  });
  const empty = (g) => g.passed.every((v) => v === 0) && g.blocked.every((v) => v === 0);
  return {
    input: empty(input) ? null : input,
    output: empty(output) ? null : output,
  };
}

/* ── Stat card ───────────────────────────────────────── */
function StatCard({ label, value, sub, subClass, spark, danger }) {
  return (
    <div
      className="flex flex-col gap-1.5"
      style={{ background: 'var(--bg-1)', border: '1px solid var(--border)', padding: '14px 16px' }}
    >
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--text-3)' }}>
        {label}
      </div>
      <div
        className="font-mono font-semibold leading-none"
        style={{ fontSize: '26px', letterSpacing: '-0.01em', color: danger ? 'var(--v-red)' : 'var(--text)' }}
      >
        {value}
      </div>
      {spark}
      <div className={['text-[11px] flex items-center gap-1.5 mt-auto', subClass || ''].join(' ')} style={{ color: 'var(--text-3)' }}>
        {sub}
      </div>
    </div>
  );
}

/* ── Live feed ───────────────────────────────────────── */
function LiveFeed({ events, paused, onPause, endpointName }) {
  return (
    <div className="flex flex-col" style={{ background: 'var(--bg-1)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between flex-shrink-0 px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Live Event Feed</span>
        <div className="flex items-center gap-[10px]">
          <button
            onClick={onPause}
            className="font-mono text-[11px] transition-colors"
            style={{ color: 'var(--text-3)' }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text)'; }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-3)'; }}
          >
            {paused ? '▶ resume' : '∥ pause'}
          </button>
          <span className="flex items-center gap-1.5 font-mono text-[11px] tracking-[0.04em]" style={{ color: 'var(--text-3)' }}>
            <span className="cdot animate" />
            LIVE
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {events.length === 0 ? (
          <div className="flex-1 grid place-items-center p-8" style={{ color: 'var(--text-3)', fontSize: '12px' }}>
            <span className="flex items-center gap-2.5">
              <span className="cdot animate" />
              Listening for events…
            </span>
          </div>
        ) : (
          events.map((e, i) => {
            const ep = e.endpoint_id != null ? endpointName(e.endpoint_id) : null;
            return (
              <div key={e.id ?? i} className={`feed-row${e.isNew ? ' new' : ''}`}>
                <span className="feed-ts">{e.ts}</span>
                <SevBadge sev={e.sev} />
                <div className="feed-detail">
                  <span className="type">{e.type}</span>
                  {ep && <span className="ep">· {ep}</span>}
                  <span className="desc">{e.detail}</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

/* ── Guard activity panel ────────────────────────────── */
function GuardActivity({ activity }) {
  return (
    <div className="flex flex-col" style={{ background: 'var(--bg-1)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between flex-shrink-0 px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Guard Activity</span>
        <span className="font-mono text-[11px]" style={{ color: 'var(--text-3)' }}>recent events</span>
      </div>
      <div className="flex-1 overflow-y-auto" style={{ padding: '6px 0' }}>
        <GuardBarChart label="Input Guard"     data={activity.input}  />
        <GuardBarChart label="Output Guard"    data={activity.output} />
        <GuardBarChart label="Retrieval AuthZ" data={null} />
      </div>
    </div>
  );
}

/* ── Recent audit table ──────────────────────────────── */
function RecentAudit({ rows, endpointName, onViewAll }) {
  return (
    <div className="flex flex-col" style={{ background: 'var(--bg-1)', border: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between flex-shrink-0 px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
        <span className="text-sm font-semibold" style={{ color: 'var(--text)' }}>Recent Audit Events</span>
        <button
          onClick={onViewAll}
          className="text-[11.5px] transition-colors"
          style={{ color: 'var(--accent)' }}
          onMouseEnter={e => { e.currentTarget.style.color = 'var(--accent-2)'; }}
          onMouseLeave={e => { e.currentTarget.style.color = 'var(--accent)'; }}
        >
          View all →
        </button>
      </div>
      <div className="overflow-x-auto">
        <table className="ov-audit-table">
          <thead>
            <tr><th>Time</th><th>Endpoint</th><th>Event Type</th><th>Severity</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {rows.slice(0, 5).map((r, i) => (
              <tr key={r.id ?? i}>
                <td className="col-ts">{r.ts}</td>
                <td className="col-ep">{r.endpoint_id != null ? endpointName(r.endpoint_id) : '—'}</td>
                <td className="col-type">{r.type}</td>
                <td className="col-sev"><SevBadge sev={r.sev} /></td>
                <td className="col-action">{r.detail || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Page ────────────────────────────────────────────── */
export default function OverviewPage() {
  const navigate = useNavigate();
  const { events, paused, setPaused } = useEventStream();
  const { serverInfo, endpoints, endpointName } = useApp();
  const { data: stats } = useApi('/api/audit/stats');

  const total = serverInfo?.requests_today ?? 0;
  const blocked = serverInfo?.blocked_today ?? 0;
  const avgMs = serverInfo?.avg_latency_ms ?? 0;
  const activeEps = serverInfo?.active_endpoints ?? endpoints.filter(e => e.is_active).length;
  const totalEps = endpoints.length;

  const sparkData = (stats?.requests_by_hour || []).map(r => r.count);
  const activity = computeGuardActivity(events);

  return (
    <>
      <TopBar title="Overview">
        <div className="top-metric">Requests <strong>{formatNum(total)}</strong></div>
        <div className="top-metric">Blocked <strong className="danger">{formatNum(blocked)}</strong></div>
        <div className="top-metric">Avg <strong>{avgMs}ms</strong></div>
      </TopBar>

      <div className="flex-1 overflow-y-auto" style={{ padding: '22px 24px 36px' }}>
        <div className="grid gap-3 mb-[18px]" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
          <StatCard
            label="Requests Today"
            value={formatNum(total)}
            spark={sparkData.length > 1 ? <Sparkline data={sparkData} /> : null}
            sub="last 24h"
          />
          <StatCard
            label="Blocked"
            danger
            value={formatNum(blocked)}
            sub={total > 0 ? `${((blocked / total) * 100).toFixed(2)}% of requests` : '—'}
          />
          <StatCard
            label="Avg Latency"
            value={<>{avgMs}<span className="font-mono" style={{ fontSize: '14px', color: 'var(--text-3)', marginLeft: '4px' }}>ms</span></>}
            sub="last 24h"
          />
          <StatCard
            label="Active Endpoints"
            value={<>{activeEps}<span className="font-mono" style={{ fontSize: '14px', color: 'var(--text-3)', marginLeft: '4px' }}>/ {totalEps}</span></>}
            sub={
              <div className="flex items-center gap-1 mt-1">
                {endpoints.map(ep => (
                  <span
                    key={ep.id}
                    title={ep.name}
                    className="rounded-full"
                    style={{ width: '7px', height: '7px', background: ep.is_active ? 'var(--v-green)' : 'var(--text-4)' }}
                  />
                ))}
              </div>
            }
          />
        </div>

        <div className="grid gap-3 mb-[18px]" style={{ gridTemplateColumns: 'minmax(0,3fr) minmax(0,2fr)', minHeight: '360px' }}>
          <LiveFeed events={events} paused={paused} onPause={() => setPaused(p => !p)} endpointName={endpointName} />
          <GuardActivity activity={activity} />
        </div>

        <RecentAudit rows={events} endpointName={endpointName} onViewAll={() => navigate('/audit')} />
      </div>
    </>
  );
}
