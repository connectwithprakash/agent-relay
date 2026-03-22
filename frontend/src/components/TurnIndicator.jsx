import AgentAvatar from './AgentAvatar';

export default function TurnIndicator({ currentTurn, agentName, agents = [], agentsPresence = [] }) {
  const presenceMap = {};
  agentsPresence.forEach(p => { presenceMap[p.agent] = p; });
  const isMyTurn = currentTurn === agentName;

  return (
    <div className="flex items-center justify-between">
      {/* Agent pills */}
      <div className="flex items-center gap-2 flex-wrap">
        {agents.length > 0 ? (
          agents.map((agent) => {
            const isActive = agent === currentTurn;
            const isMe = agent === agentName;
            return (
              <div
                key={agent}
                className={`
                  flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all duration-300
                  ${isActive
                    ? 'bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 ring-2 ring-indigo-500/30'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                  }
                `}
              >
                <AgentAvatar name={agent} size="xs" active={isActive} />
                <span>{agent}</span>
                {isMe && (
                  <span className="text-[10px] opacity-60">(you)</span>
                )}
                {presenceMap[agent]?.status_message && (
                  <span className="text-[10px] opacity-50 max-w-[120px] truncate" title={presenceMap[agent].status_message}>
                    {presenceMap[agent].status_message}
                  </span>
                )}
                {isActive && (
                  <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                )}
              </div>
            );
          })
        ) : (
          <div className="flex items-center gap-2">
            <div
              className={`w-2.5 h-2.5 rounded-full ${
                isMyTurn ? 'bg-emerald-500 animate-pulse' : 'bg-slate-400'
              }`}
            />
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Current Turn: <span className="font-bold">{currentTurn}</span>
            </span>
          </div>
        )}
      </div>

      {/* Status badge */}
      {isMyTurn ? (
        <span className="px-3 py-1 text-xs font-semibold text-emerald-700 bg-emerald-100 rounded-full dark:bg-emerald-900/30 dark:text-emerald-300 animate-fade-in">
          Your Turn
        </span>
      ) : (
        <span className="px-3 py-1 text-xs font-semibold text-slate-500 bg-slate-100 rounded-full dark:bg-slate-800 dark:text-slate-400">
          Waiting...
        </span>
      )}
    </div>
  );
}
