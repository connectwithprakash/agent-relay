import { useState, useEffect, useCallback } from 'react';
import { getRelay } from '../utils/api';
import AgentAvatar from './AgentAvatar';

export default function WaitingRoom({ relay: initialRelay, relayId, onActivate }) {
  const [relay, setRelay] = useState(initialRelay);
  const [copied, setCopied] = useState(false);

  const agents = relay?.agent_names || relay?.agents || [];
  const minAgents = relay?.min_agents || 2;
  const joinCode = relay?.join_code || '';
  const description = relay?.description || '';
  const progress = Math.min(agents.length / minAgents, 1);

  const handleCopyCode = useCallback(async () => {
    if (!joinCode) return;
    try {
      await navigator.clipboard.writeText(joinCode);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for non-HTTPS contexts
      const textArea = document.createElement('textarea');
      textArea.value = joinCode;
      document.body.appendChild(textArea);
      textArea.select();
      document.execCommand('copy');
      document.body.removeChild(textArea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }, [joinCode]);

  // Poll relay state every 3 seconds
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const state = await getRelay(relayId);
        setRelay(state);
        const currentAgents = state.agent_names || state.agents || [];
        const needed = state.min_agents || 2;
        if (currentAgents.length >= needed || state.status === 'active') {
          clearInterval(interval);
          if (onActivate) onActivate(state);
        }
      } catch (err) {
        console.error('Failed to poll relay state:', err);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [relayId, onActivate]);

  // Sync initial relay prop updates
  useEffect(() => {
    if (initialRelay) setRelay(initialRelay);
  }, [initialRelay]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center px-4 py-12">
      <div className="max-w-lg w-full bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-slate-200 dark:border-slate-800 p-6 sm:p-8 animate-fade-in-up">
        {/* Header icon */}
        <div className="text-center mb-6">
          <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-50 dark:bg-indigo-950/40 mb-4">
            <svg className="w-7 h-7 text-indigo-600 dark:text-indigo-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white mb-1">
            Waiting Room
          </h2>
          {description && (
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{description}</p>
          )}
        </div>

        {/* Join code */}
        {joinCode && (
          <div className="mb-6">
            <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-2 text-center">
              Share this join code
            </p>
            <div className="flex items-center justify-center gap-2">
              <span className="font-mono text-3xl font-bold tracking-widest text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/40 px-6 py-3 rounded-xl border-2 border-dashed border-indigo-200 dark:border-indigo-800">
                {joinCode}
              </span>
              <button
                onClick={handleCopyCode}
                className="p-3 rounded-xl border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                title="Copy join code"
              >
                {copied ? (
                  <svg className="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5 text-slate-500 dark:text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Pulsing waiting indicator */}
        <div className="flex items-center justify-center gap-2 mb-6">
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-indigo-500" />
          </span>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            Waiting for agents to join...
          </span>
        </div>

        {/* Progress bar */}
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              {agents.length} of {minAgents} agents needed
            </span>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              {Math.round(progress * 100)}%
            </span>
          </div>
          <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2.5 overflow-hidden">
            <div
              className="bg-indigo-500 h-2.5 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${progress * 100}%` }}
              role="progressbar"
              aria-valuenow={agents.length}
              aria-valuemin={0}
              aria-valuemax={minAgents}
            />
          </div>
        </div>

        {/* Joined agents list */}
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider mb-3">
            Agents joined
          </p>
          {agents.length === 0 ? (
            <p className="text-sm text-slate-400 dark:text-slate-500 italic text-center py-4">
              No agents have joined yet
            </p>
          ) : (
            <div className="space-y-2">
              {agents.map((agent, i) => (
                <div
                  key={agent}
                  className="flex items-center gap-3 p-3 bg-slate-50 dark:bg-slate-800/50 rounded-xl animate-fade-in-up"
                  style={{ animationDelay: `${i * 0.1}s` }}
                >
                  <AgentAvatar name={agent} size="sm" />
                  <span className="font-medium text-slate-900 dark:text-white text-sm">
                    {agent}
                  </span>
                  <span className="ml-auto text-xs text-green-500 font-medium">Joined</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Relay ID */}
        <div className="mt-6 pt-4 border-t border-slate-100 dark:border-slate-800 text-center">
          <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">
            Relay {relayId.substring(0, 12)}...
          </span>
        </div>
      </div>
    </div>
  );
}
