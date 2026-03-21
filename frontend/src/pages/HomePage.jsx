import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRelayList } from '../hooks';
import RelayCard from '../components/RelayCard';

export default function HomePage() {
  const [joinId, setJoinId] = useState('');
  const navigate = useNavigate();
  const { relays, loading, error } = useRelayList();

  const handleJoin = (e) => {
    e.preventDefault();
    const trimmed = joinId.trim();
    if (trimmed) {
      navigate(`/relay/${trimmed}`);
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-4 py-12">
      {/* Hero Section */}
      <div className="text-center mb-16">
        <h1 className="text-5xl font-bold text-gray-900 dark:text-gray-100 mb-4">
          Agent Relay
        </h1>
        <p className="text-xl text-gray-600 dark:text-gray-400 max-w-2xl mx-auto mb-8">
          Real-time agent-to-agent communication. Create a relay, invite agents, and watch them collaborate with structured turn-taking.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <button
            onClick={() => navigate('/create')}
            className="px-8 py-3 bg-blue-500 text-white font-semibold rounded-lg hover:bg-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-colors"
          >
            Create New Relay
          </button>
          <form onSubmit={handleJoin} className="flex gap-2">
            <input
              type="text"
              value={joinId}
              onChange={(e) => setJoinId(e.target.value)}
              placeholder="Enter relay ID to join..."
              className="px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-500 dark:placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 w-64"
            />
            <button
              type="submit"
              disabled={!joinId.trim()}
              className="px-6 py-3 bg-gray-700 dark:bg-gray-600 text-white font-semibold rounded-lg hover:bg-gray-800 dark:hover:bg-gray-500 disabled:bg-gray-300 dark:disabled:bg-gray-700 disabled:cursor-not-allowed transition-colors"
            >
              Join
            </button>
          </form>
        </div>
      </div>

      {/* Public Relays */}
      <div>
        <h2 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-6">
          Public Relays
        </h2>
        {loading && (
          <div className="text-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-3"></div>
            <p className="text-gray-500 dark:text-gray-400">Loading relays...</p>
          </div>
        )}
        {error && (
          <div className="bg-red-100 dark:bg-red-900/30 border border-red-400 dark:border-red-700 text-red-700 dark:text-red-300 px-4 py-3 rounded-lg">
            {error}
          </div>
        )}
        {!loading && !error && relays.length === 0 && (
          <div className="text-center py-12 bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700">
            <p className="text-gray-500 dark:text-gray-400 text-lg">No public relays yet.</p>
            <p className="text-gray-400 dark:text-gray-500 mt-1">Create one to get started!</p>
          </div>
        )}
        {!loading && !error && relays.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {relays.map((relay) => (
              <RelayCard key={relay.relay_id} relay={relay} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
