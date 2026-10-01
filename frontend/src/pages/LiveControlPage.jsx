import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { getAgent, getToken } from '../utils/auth';
import { renewLease } from '../utils/api';
import { parseServerTimestamp } from '../utils/time';
import { useControlStream } from '../hooks/useControlStream';
import { useLeaseCountdown } from '../hooks/useLeaseCountdown';
import TerminalViewport from '../components/TerminalViewport';

const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const wsBase = apiBase.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:');

function hasActiveLease(session, agent) {
  return Boolean(
    agent
      && session?.controller_agent === agent
      && session.lease_expires_at
      && parseServerTimestamp(session.lease_expires_at) > Date.now(),
  );
}

const LEASE_SECONDS = 60;
const RENEW_FIRST_FRACTION = 0.5;
const RENEW_RETRY_FRACTION = 0.75;
const SESSION_END_KINDS = new Set(['session_failed', 'session_exited']);

const ERROR_FALLBACKS = {
  invalid_resize: 'The terminal size was rejected by the relay.',
  worker_unavailable: 'The worker is unavailable.',
};

function StreamBadge({ status }) {
  const tone = status === 'connected' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : status === 'revoked' ? 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
  return <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>{status}</span>;
}

function formatRemaining(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

function LeaseBadge({ seconds }) {
  const tone = seconds <= 10 ? 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300' : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
  return <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold tabular-nums ${tone}`}>Lease {formatRemaining(seconds)}</span>;
}

function SessionBadge({ status }) {
  const tone = status === 'ready' || status === 'controlled' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : status === 'failed' ? 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300';
  return <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>session {status || 'unknown'}</span>;
}

function WorkerBadge({ status }) {
  const tone = status === 'online' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300' : status === 'revoked' ? 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300' : 'bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300';
  return <span className={`whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${tone}`}>worker {status || 'unknown'}</span>;
}

export default function LiveControlPage() {
  const { relayId, sessionId } = useParams();
  return <LiveControlSession key={`${relayId}/${sessionId}`} />;
}

function LiveControlSession() {
  const { relayId, sessionId } = useParams();
  const token = getToken(relayId);
  const agent = getAgent(relayId);
  const [session, setSessionState] = useState(null);
  const sessionRef = useRef(null);
  const [lease, setLease] = useState(false);
  const [terminal, setTerminal] = useState('');
  const [input, setInput] = useState('');
  const [approvalPrompt, setApprovalPrompt] = useState(null);
  const [error, setError] = useState('');


  const setSession = useCallback((update) => {
    sessionRef.current = typeof update === 'function' ? update(sessionRef.current) : update;
    setSessionState(sessionRef.current);
  }, []);

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...options.headers },
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Control request failed');
    return response.json();
  }, [token]);

  const loadSession = useCallback(async () => {
    if (!token) return;
    try {
      const result = await request(`/relays/${relayId}/sessions`);
      const next = result.sessions.find((item) => item.session_id === sessionId);
      if (!next) throw new Error('Session not found');
      if (sessionRef.current && next.version < sessionRef.current.version) return;
      setSession(next);
      setLease(hasActiveLease(next, agent));
    } catch (cause) {
      setError(cause.message);
    }
  }, [agent, relayId, request, sessionId, setSession, token]);

  useEffect(() => { loadSession(); }, [loadSession]);

  const onFrame = useCallback((frame) => {
    if (frame.type === 'connected') setLease(Boolean(frame.lease?.held));
    if (frame.type === 'event' && frame.event?.kind === 'output') {
      setTerminal((current) => current + (frame.event.data?.text || ''));
    }
    if (frame.type === 'event' && frame.event?.kind === 'input_requested') setApprovalPrompt(null);
    if (frame.type === 'event' && frame.event?.kind === 'lease_renewed' && frame.event.data?.controller_agent === agent) void loadSession();
    if (frame.type === 'event' && frame.event?.kind === 'session_adopted' && sessionRef.current?.status !== 'failed') void loadSession();
    if (frame.type === 'event' && SESSION_END_KINDS.has(frame.event?.kind)) {
      setSession((current) => current ? { ...current, status: 'failed' } : current);
      setLease(false);
      void loadSession();
    }
    if (frame.type === 'event' && frame.event?.kind === 'approval_requested' && typeof frame.event.data?.prompt === 'string' && frame.event.data.prompt) {
      setApprovalPrompt(frame.event.data.prompt);
    }
    if (frame.type === 'error') {
      if (frame.code === 'lease_required') {
        setLease(false);
        setError('Control lease ended. Take control again to send input.');
        void loadSession();
        return;
      }
      setError(frame.message || ERROR_FALLBACKS[frame.code] || 'The relay reported an error.');
      if (frame.code === 'worker_unavailable') {
        setSession((current) => current ? { ...current, worker_status: 'offline' } : current);
        void loadSession();
      }
    }
  }, [agent, loadSession, setSession]);

  const holdsLive = lease && !['failed', 'detached'].includes(session?.status);
  const onLeaseExpired = useCallback(() => { setLease(false); void loadSession(); }, [loadSession]);
  const leaseSeconds = useLeaseCountdown(parseServerTimestamp(session?.lease_expires_at), holdsLive, onLeaseExpired);

  const { status, sendInput, sendResize, reconnect } = useControlStream({
    url: token ? `${wsBase}/relays/${relayId}/sessions/${sessionId}/stream` : '',
    token,
    onEvent: onFrame,
  });

  const failedRenewalRef = useRef(null);
  const leaseExpiresAt = session?.lease_expires_at;
  const canRenew = holdsLive && status === 'connected' && session?.worker_status === 'online';
  useEffect(() => {
    const expiresMs = parseServerTimestamp(leaseExpiresAt);
    if (!canRenew || !Number.isFinite(expiresMs) || failedRenewalRef.current === leaseExpiresAt) return undefined;
    // Renew once, halfway through the remaining lease. A network error or 5xx gets one
    // retry three quarters of the way through; any other failure, or a failed retry, is
    // remembered for this expiry, so there is no loop and the expiry transition ends control.
    const startedAt = Date.now();
    const remainingMs = expiresMs - startedAt;
    let cancelled = false;
    let retryTimer;
    const attempt = async (isRetry) => {
      try {
        const renewed = await renewLease(relayId, sessionId, { expectedVersion: sessionRef.current.version, leaseSeconds: LEASE_SECONDS });
        // The effect may have been torn down while this request was in flight (worker or
        // stream flapping). The response is still real server state, so adopt it unless the
        // page has already moved to a newer version (release, refetch, another tab).
        setSession((current) => (current && renewed.version > current.version
          ? { ...renewed, worker_status: current.worker_status }
          : current));
      } catch (cause) {
        if (cancelled) return;
        const transient = cause.status === undefined || cause.status >= 500;
        if (transient && !isRetry) {
          retryTimer = setTimeout(() => attempt(true), Math.max(0, startedAt + remainingMs * RENEW_RETRY_FRACTION - Date.now()));
          return;
        }
        failedRenewalRef.current = leaseExpiresAt;
        if (cause.status === 409) void loadSession();
      }
    };
    const timer = setTimeout(() => attempt(false), Math.max(0, remainingMs * RENEW_FIRST_FRACTION));
    return () => { cancelled = true; clearTimeout(timer); clearTimeout(retryTimer); };
  }, [canRenew, leaseExpiresAt, loadSession, relayId, sessionId, setSession]);

  const sendTerminalInput = useCallback((data) => {
    if (!lease || status !== 'connected' || session?.worker_status !== 'online') return;
    if (!sendInput(data)) setError('Stream is not connected. Reconnect before sending input.');
    else setApprovalPrompt(null);
  }, [lease, sendInput, session?.worker_status, status]);

  const claim = async () => {
    const requestClaim = (version) => request(`/relays/${relayId}/sessions/${sessionId}/claim`, {
      method: 'POST', body: JSON.stringify({ lease_seconds: LEASE_SECONDS, expected_version: version }),
    });
    const applyClaim = (result) => {
      setSession((current) => ({ ...result, worker_status: current?.worker_status }));
      setLease(true);
      setError('');
    };
    try {
      applyClaim(await requestClaim(session.version));
    } catch (cause) {
      if (cause.message !== 'Session state changed; refresh and retry') {
        setError(cause.message);
        return;
      }
      try {
        const result = await request(`/relays/${relayId}/sessions`);
        const refreshed = result.sessions.find((item) => item.session_id === sessionId);
        if (!refreshed) throw new Error('Session not found');
        setSession(refreshed);
        applyClaim(await requestClaim(refreshed.version));
      } catch (retryCause) {
        setError(retryCause.message);
      }
    }
  };

  const release = async () => {
    try {
      const result = await request(`/relays/${relayId}/sessions/${sessionId}/release`, { method: 'POST' });
      setSession((current) => ({ ...result, worker_status: current?.worker_status }));
      setLease(false);
      setError('');
    } catch (cause) { setError(cause.message); }
  };

  const submit = (event) => {
    event.preventDefault();
    if (!input || !lease) return;
    if (!sendInput(input.endsWith('\n') ? input : `${input}\n`)) setError('Stream is not connected. Reconnect before sending input.');
    else { setInput(''); setApprovalPrompt(null); }
  };

  if (!token) return <section className="mx-auto max-w-3xl p-6"><h1 className="text-xl font-bold">Relay access required</h1><p className="mt-2 text-slate-600 dark:text-slate-300">Pair this browser with the relay before opening a live control session.</p></section>;

  return (
    <div className="min-h-[calc(100vh-7rem)] bg-slate-50 p-4 dark:bg-slate-950 sm:p-6">
      <main className="mx-auto flex max-w-6xl flex-col gap-4">
        <header className="flex flex-col gap-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0"><p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">Live control</p><h1 className="truncate text-xl font-bold text-slate-900 dark:text-white">{session?.profile || 'Loading session…'}</h1><p className="text-sm text-slate-500 dark:text-slate-400">{sessionId}</p></div>
          <div className="flex flex-wrap items-center gap-2">{holdsLive && leaseSeconds > 0 && <LeaseBadge seconds={leaseSeconds} />}<SessionBadge status={session?.status} /><WorkerBadge status={session?.worker_status} /><StreamBadge status={status} /><button onClick={reconnect} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold dark:border-slate-700">Reconnect</button>{lease ? <button onClick={release} className="rounded-lg bg-slate-800 px-3 py-2 text-sm font-semibold text-white dark:bg-slate-100 dark:text-slate-900">Release control</button> : <button disabled={!session || session.status === 'failed' || session.worker_status !== 'online'} onClick={claim} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Take control</button>}</div>
        </header>
        {error && <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">{error}</p>}
        <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-sm">
          <div className="border-b border-slate-800 px-4 py-2 text-xs font-medium text-slate-400">Terminal output · durable replay on reconnect</div>
          <TerminalViewport output={terminal} inputEnabled={lease && status === 'connected' && session?.worker_status === 'online'} onInput={sendTerminalInput} onResize={sendResize} approvalPrompt={approvalPrompt} onDismissApproval={() => setApprovalPrompt(null)} />
        </section>
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row"><label className="sr-only" htmlFor="terminal-input">Terminal input</label><input id="terminal-input" value={input} onChange={(event) => setInput(event.target.value)} disabled={!lease || status !== 'connected' || session?.worker_status !== 'online'} placeholder={session?.worker_status !== 'online' ? 'Worker is unavailable' : lease ? 'Type terminal input…' : 'Take control to send input'} className="min-w-0 flex-1 rounded-xl border border-slate-300 bg-white px-4 py-3 font-mono text-sm text-slate-900 disabled:bg-slate-100 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:disabled:bg-slate-800"/><button disabled={!lease || !input || status !== 'connected' || session?.worker_status !== 'online'} className="rounded-xl bg-indigo-600 px-5 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">Send</button></form>
      </main>
    </div>
  );
}
