import AgentAvatar from './AgentAvatar';
import { getAgent, getToken } from '../utils/auth';

export default function AgentSelector({ relayId, onSelect }) {
  const token = getToken(relayId);
  const agent = getAgent(relayId);

  if (!token || !agent) {
    return (
      <div className="p-6 bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-amber-200 dark:border-amber-800 animate-scale-in">
        <p className="font-semibold text-slate-900 dark:text-white mb-1">Participant credential required</p>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Redeem the one-time invitation for your named participant before opening this relay.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-slate-200 dark:border-slate-800 p-6 sm:p-8 animate-fade-in-up">
      <div className="text-center mb-6">
        <h2 className="text-2xl font-bold text-slate-900 dark:text-white mb-1">Join Relay</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Your credential is bound to this participant identity.
        </p>
      </div>
      <button
        onClick={() => onSelect(agent)}
        className="w-full p-4 border-2 border-indigo-300 dark:border-indigo-700 rounded-xl text-left hover:bg-indigo-50/50 dark:hover:bg-indigo-950/20 transition-all"
      >
        <div className="flex items-center gap-3">
          <AgentAvatar name={agent} size="md" />
          <div>
            <p className="font-semibold text-slate-900 dark:text-white">{agent}</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">Continue as authenticated participant</p>
          </div>
        </div>
      </button>
    </div>
  );
}
