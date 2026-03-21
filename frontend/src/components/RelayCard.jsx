import { useNavigate } from 'react-router-dom';
import AgentAvatar from './AgentAvatar';

export default function RelayCard({ relay }) {
  const navigate = useNavigate();

  const formatDate = (timestamp) => {
    if (!timestamp) return 'Unknown';
    return new Date(timestamp).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const agents = relay.agents || [];
  const messageCount = relay.message_count ?? 0;

  return (
    <button
      onClick={() => navigate(`/relay/${relay.relay_id}`)}
      className="w-full text-left p-5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl hover:border-indigo-300 dark:hover:border-indigo-700 hover:shadow-lg transition-all duration-200 group"
    >
      {/* Header row */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex -space-x-1.5">
          {agents.slice(0, 4).map((agent) => (
            <AgentAvatar key={agent} name={agent} size="sm" showRing />
          ))}
          {agents.length > 4 && (
            <div className="w-8 h-8 rounded-full bg-slate-100 dark:bg-slate-800 border-2 border-white dark:border-slate-900 flex items-center justify-center text-xs font-medium text-slate-500 dark:text-slate-400">
              +{agents.length - 4}
            </div>
          )}
        </div>
        <span className="text-[11px] text-slate-400 dark:text-slate-500 flex items-center gap-1">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {formatDate(relay.created_at)}
        </span>
      </div>

      {/* Relay ID */}
      <p className="font-mono text-xs text-slate-400 dark:text-slate-500 mb-2 truncate">
        {relay.relay_id}
      </p>

      {/* Agent tags */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {agents.map((agent) => (
          <span
            key={agent}
            className="px-2 py-0.5 text-xs font-medium bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 rounded-full"
          >
            {agent}
          </span>
        ))}
      </div>

      {/* Footer stats */}
      <div className="flex items-center gap-3 text-xs text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
          </svg>
          {messageCount} message{messageCount !== 1 ? 's' : ''}
        </span>
        <span className="flex items-center gap-1">
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          {agents.length} agent{agents.length !== 1 ? 's' : ''}
        </span>
        <span className="ml-auto text-indigo-500 dark:text-indigo-400 opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 font-medium">
          Open
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
          </svg>
        </span>
      </div>
    </button>
  );
}
