import { useRelay } from '../hooks';

export default function AgentSelector({ relayId, onSelect }) {
  const { relay, loading, error } = useRelay(relayId);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-8 text-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-3"></div>
        <p className="text-gray-500 dark:text-gray-400">Loading relay info...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-100 dark:bg-red-900/30 border border-red-400 dark:border-red-700 text-red-700 dark:text-red-300 px-6 py-4 rounded-lg">
        <p className="font-bold mb-1">Error</p>
        <p>{error}</p>
      </div>
    );
  }

  const agents = relay?.agents || [];

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-8">
      <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
        Select Your Agent
      </h2>
      <p className="text-gray-600 dark:text-gray-400 mb-6">
        Choose which agent you want to join as in relay{' '}
        <span className="font-mono text-sm">{relayId}</span>
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {agents.map((agent) => (
          <button
            key={agent}
            onClick={() => onSelect(agent)}
            className="p-4 border-2 border-gray-200 dark:border-gray-600 rounded-lg text-left hover:border-blue-500 dark:hover:border-blue-400 hover:bg-blue-50 dark:hover:bg-blue-900/20 transition-colors group"
          >
            <p className="font-semibold text-gray-900 dark:text-gray-100 group-hover:text-blue-500 dark:group-hover:text-blue-400">
              {agent}
            </p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
              Join as this agent
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}
