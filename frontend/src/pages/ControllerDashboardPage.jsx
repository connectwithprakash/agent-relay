import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getToken } from '../utils/auth';

const apiBase = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

function InvitationCard({ title, description, invitation, onCopy }) {
  return (
    <article className="rounded-xl border border-slate-200 p-4 dark:border-slate-800">
      <h3 className="font-semibold text-slate-900 dark:text-white">{title}</h3>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{description}</p>
      {invitation && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950/30">
          <p className="break-all font-mono text-sm text-slate-800 dark:text-slate-100">{invitation}</p>
          <button onClick={onCopy} className="mt-2 rounded-lg bg-slate-800 px-3 py-2 text-sm font-semibold text-white dark:bg-slate-100 dark:text-slate-900">Copy one-time code</button>
        </div>
      )}
    </article>
  );
}

export default function ControllerDashboardPage() {
  const { relayId } = useParams();
  const navigate = useNavigate();
  const token = getToken(relayId);
  const [workers, setWorkers] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [participants, setParticipants] = useState([]);
  const [profiles, setProfiles] = useState({});
  const [workerAgent, setWorkerAgent] = useState('');
  const [browserInvitation, setBrowserInvitation] = useState('');
  const [workerInvitation, setWorkerInvitation] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const request = useCallback(async (path, options = {}) => {
    const response = await fetch(`${apiBase}${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...options.headers },
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Control request failed');
    return response.json();
  }, [token]);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [workerResult, sessionResult, participantResult] = await Promise.all([
        request(`/relays/${relayId}/workers`),
        request(`/relays/${relayId}/sessions`),
        request(`/relays/${relayId}/unpaired-participants`),
      ]);
      setWorkers(workerResult.workers);
      setSessions(sessionResult.sessions);
      setParticipants(participantResult.participants || []);
      setProfiles(Object.fromEntries(workerResult.workers.map((worker) => [worker.worker_id, worker.profiles[0] || ''])));
      setError('');
    } catch (cause) {
      setError(cause.message);
    } finally {
      setLoading(false);
    }
  }, [relayId, request, token]);

  useEffect(() => { load(); }, [load]);

  const availableWorkerAgents = useMemo(() => participants, [participants]);

  useEffect(() => {
    if (!workerAgent || !availableWorkerAgents.includes(workerAgent)) setWorkerAgent(availableWorkerAgents[0] || '');
  }, [availableWorkerAgents, workerAgent]);

  const copyInvitation = async (invitation) => {
    try {
      await navigator.clipboard.writeText(invitation);
      setError('');
    } catch {
      setError('Could not copy the one-time code. Copy it directly from the panel instead.');
    }
  };

  const createBrowserInvitation = async () => {
    try {
      const result = await request(`/relays/${relayId}/controller-browser-invitations?expires_in_seconds=300`, { method: 'POST' });
      setBrowserInvitation(result.invitation);
      setError('');
    } catch (cause) {
      setError(cause.message);
    }
  };

  const createWorkerInvitation = async () => {
    if (!workerAgent) return;
    try {
      const result = await request(`/relays/${relayId}/invitations?agent_name=${encodeURIComponent(workerAgent)}&expires_in_seconds=900`, { method: 'POST' });
      setWorkerInvitation(result.invitation);
      setError('');
    } catch (cause) {
      setError(cause.message);
    }
  };

  const start = async (workerId) => {
    try {
      const session = await request(`/relays/${relayId}/sessions`, {
        method: 'POST',
        body: JSON.stringify({ worker_id: workerId, profile: profiles[workerId] }),
      });
      navigate(`/relay/${relayId}/sessions/${session.session_id}/live`);
    } catch (cause) {
      setError(cause.message);
    }
  };

  if (!token) {
    return <main className="mx-auto max-w-3xl p-6"><h1 className="text-xl font-bold">Relay access required</h1><p className="mt-2 text-slate-600 dark:text-slate-300">Paste a one-time browser invitation on the home page, then return here.</p><Link className="mt-4 inline-block font-semibold text-indigo-600" to="/">Go to pairing</Link></main>;
  }

  return (
    <main className="mx-auto max-w-5xl p-4 sm:p-6">
      <header className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"><div><p className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">Controller</p><h1 className="text-2xl font-bold text-slate-900 dark:text-white">Your managed sessions</h1><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Workers are remembered; control is temporary and lease-gated.</p></div><button onClick={load} className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-semibold dark:border-slate-700">Refresh</button></header>
      {error && <p role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-200">{error}</p>}

      <section className="mb-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"><h2 className="font-semibold text-slate-900 dark:text-white">Pair devices and browsers</h2><p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Create a short-lived one-time code here. It is never saved after you leave this page.</p><div className="mt-4 grid gap-4 md:grid-cols-2"><InvitationCard title="Pair another browser" description="Use this code on the Home page of the browser you want to authorize." invitation={browserInvitation} onCopy={() => copyInvitation(browserInvitation)} /><div className="flex items-end gap-2"><button onClick={createBrowserInvitation} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white">Create browser code</button></div><InvitationCard title="Pair a work computer" description="Choose its named participant, then use the one-time code in the local Worker app during its first setup." invitation={workerInvitation} onCopy={() => copyInvitation(workerInvitation)} /><div className="flex flex-wrap items-end gap-2"><select aria-label="Worker participant" value={workerAgent} onChange={(event) => setWorkerAgent(event.target.value)} disabled={!availableWorkerAgents.length} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"><option value="">{availableWorkerAgents.length ? 'Choose participant' : 'No unpaired participants'}</option>{availableWorkerAgents.map((agent) => <option key={agent} value={agent}>{agent}</option>)}</select><button onClick={createWorkerInvitation} disabled={!workerAgent} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Create work-computer code</button></div></div></section>

      <section className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"><h2 className="font-semibold text-slate-900 dark:text-white">Workers</h2><div className="mt-3 space-y-3">{loading ? <p className="text-sm text-slate-500">Loading workers…</p> : workers.length === 0 ? <p className="text-sm text-slate-500">No worker is paired yet. Create a work-computer code above, then complete setup in its local Worker app.</p> : workers.map((worker) => <article key={worker.worker_id} className="flex flex-col gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800 sm:flex-row sm:items-center sm:justify-between"><div><p className="font-semibold text-slate-900 dark:text-white">{worker.name}</p><p className="text-sm text-slate-500 dark:text-slate-400">{worker.status} · {worker.profiles.join(', ')}</p></div><div className="flex gap-2"><select aria-label={`Profile for ${worker.name}`} value={profiles[worker.worker_id] || ''} onChange={(event) => setProfiles((current) => ({ ...current, [worker.worker_id]: event.target.value }))} disabled={worker.status !== 'online'} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-800"><>{worker.profiles.map((profile) => <option key={profile}>{profile}</option>)}</></select><button onClick={() => start(worker.worker_id)} disabled={worker.status !== 'online'} className="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">Start session</button></div></article>)}</div></section>
      <section className="mt-6 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-800 dark:bg-slate-900"><h2 className="font-semibold text-slate-900 dark:text-white">Sessions</h2><div className="mt-3 space-y-2">{sessions.length === 0 ? <p className="text-sm text-slate-500">No managed sessions yet.</p> : sessions.map((session) => <Link key={session.session_id} to={`/relay/${relayId}/sessions/${session.session_id}/live`} className="flex items-center justify-between rounded-xl border border-slate-200 p-3 transition hover:border-indigo-400 dark:border-slate-800"><span><strong>{session.profile}</strong><span className="ml-2 text-sm text-slate-500">{session.worker_status}</span></span><span className="text-sm font-semibold text-indigo-600">Open</span></Link>)}</div></section>
    </main>
  );
}
