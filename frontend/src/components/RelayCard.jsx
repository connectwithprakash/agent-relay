import { useNavigate } from 'react-router-dom';

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

  return (
    <button
      onClick={() => navigate(`/relay/${relay.relay_id}`)}
      className="w-full text-left p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg hover:border-blue-500 dark:hover:border-blue-400 hover:shadow-md transition-all group"
    >
      <div className="flex items-start justify-between mb-2">
        <span className="font-mono text-sm text-gray-500 dark:text-gray-400 truncate max-w-[70%]">
          {relay.relay_id}
        </span>
        <span className="text-xs text-gray-400 dark:text-gray-500">
          {formatDate(relay.created_at)}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5 mb-3">
        {(relay.agents || []).map((agent) => (
          <span
            key={agent}
            className="px-2 py-0.5 text-xs font-medium bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300 rounded-full"
          >
            {agent}
          </span>
        ))}
      </div>
      <div className="text-sm text-gray-500 dark:text-gray-400">
        {relay.message_count ?? 0} messages
      </div>
    </button>
  );
}
