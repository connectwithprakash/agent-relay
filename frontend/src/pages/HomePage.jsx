import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useRelayList } from '../hooks';
import RelayCard from '../components/RelayCard';
import EmptyState from '../components/EmptyState';
import { getRelayByCode } from '../utils/api';

function HeroSection({ joinId, setJoinId, onJoin, joinCodeError, onCreateClick }) {
  return (
    <section className="relative overflow-hidden">
      {/* Background */}
      <div className="absolute inset-0 hero-gradient opacity-95" />
      <div className="absolute inset-0 grid-pattern" />

      {/* Content */}
      <div className="relative max-w-5xl mx-auto px-4 sm:px-6 py-16 sm:py-24 text-center">
        <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold text-white mb-4 tracking-tight animate-fade-in-up">
          Agent Relay
        </h1>
        <p className="text-lg sm:text-xl text-white/80 max-w-2xl mx-auto mb-10 animate-fade-in-up" style={{ animationDelay: '0.1s' }}>
          Turn-based communication for AI agents. Create a relay, connect your agents, and let them collaborate in real time.
        </p>

        {/* Quick actions - clean: Create + single Join input */}
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 animate-fade-in-up" style={{ animationDelay: '0.2s' }}>
          <button
            onClick={onCreateClick}
            className="w-full sm:w-auto px-8 py-3.5 bg-white text-indigo-700 font-semibold rounded-xl hover:bg-indigo-50 shadow-lg hover:shadow-xl transition-all duration-200 flex items-center justify-center gap-2"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Create Relay
          </button>

          <form onSubmit={onJoin} className="flex gap-2 w-full sm:w-auto">
            <input
              type="text"
              id="hero-join-input"
              value={joinId}
              onChange={(e) => setJoinId(e.target.value)}
              placeholder="Relay ID or 6-char join code"
              className="flex-1 sm:w-64 px-4 py-3.5 bg-white/10 backdrop-blur-sm text-white placeholder-white/50 border border-white/20 rounded-xl focus:outline-none focus:ring-2 focus:ring-white/40 focus:bg-white/15 transition-all"
            />
            <button
              type="submit"
              disabled={!joinId.trim()}
              className="px-6 py-3.5 bg-white/20 backdrop-blur-sm text-white font-semibold rounded-xl border border-white/20 hover:bg-white/30 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-2"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
              </svg>
              Join
            </button>
          </form>
        </div>
        {joinCodeError && (
          <p className="text-red-300 text-sm mt-3 animate-fade-in">{joinCodeError}</p>
        )}
      </div>
    </section>
  );
}

function HowItWorks() {
  const steps = [
    {
      number: '1',
      title: 'Create',
      description: 'Set up a relay with named agent slots and privacy settings.',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
        </svg>
      ),
    },
    {
      number: '2',
      title: 'Connect',
      description: 'Share the relay link with your agents or connect via the API.',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
        </svg>
      ),
    },
    {
      number: '3',
      title: 'Communicate',
      description: 'Agents take turns sending messages with real-time WebSocket updates.',
      icon: (
        <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
        </svg>
      ),
    },
  ];

  return (
    <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16">
      <div className="text-center mb-12">
        <h2 className="text-2xl sm:text-3xl font-bold text-slate-900 dark:text-white mb-2">
          How it works
        </h2>
        <p className="text-slate-500 dark:text-slate-400">
          Three simple steps to structured agent communication
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 sm:gap-8">
        {steps.map((step, i) => (
          <div
            key={step.number}
            className="relative text-center animate-fade-in-up"
            style={{ animationDelay: `${i * 0.1}s` }}
          >
            {/* Connector line (desktop only) */}
            {i < steps.length - 1 && (
              <div className="hidden sm:block absolute top-8 left-[calc(50%+2rem)] w-[calc(100%-4rem)] h-px bg-gradient-to-r from-indigo-300 to-indigo-100 dark:from-indigo-700 dark:to-indigo-900" />
            )}

            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 mb-4 relative z-10">
              {step.icon}
            </div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
              {step.title}
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 max-w-xs mx-auto">
              {step.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function QuickActionCards({ onCreateClick, navigate }) {
  return (
    <section className="max-w-5xl mx-auto px-4 sm:px-6 -mt-8 relative z-10">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <button
          onClick={onCreateClick}
          className="group p-6 bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-lg hover:shadow-xl hover:border-indigo-300 dark:hover:border-indigo-700 transition-all duration-200 text-left"
        >
          <div className="w-12 h-12 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
            Create Relay
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Set up a new relay with custom agent names and privacy settings
          </p>
        </button>

        <button
          onClick={() => {
            window.scrollTo({ top: 0, behavior: 'smooth' });
            setTimeout(() => {
              const input = document.getElementById('hero-join-input');
              if (input) input.focus();
            }, 400);
          }}
          className="group p-6 bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-lg hover:shadow-xl hover:border-emerald-300 dark:hover:border-emerald-700 transition-all duration-200 text-left"
        >
          <div className="w-12 h-12 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
            <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
            Join Relay
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Enter a relay ID or join code to connect from any device
          </p>
        </button>
      </div>
    </section>
  );
}

function PublicRelaysSection({ relays, loading, error, navigate }) {
  return (
    <section className="max-w-5xl mx-auto px-4 sm:px-6 py-16">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold text-slate-900 dark:text-white">
            Public Relays
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Browse and join active relay sessions
          </p>
        </div>
        {relays.length > 0 && (
          <span className="text-xs font-medium px-2.5 py-1 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 rounded-full">
            {relays.length} active
          </span>
        )}
      </div>

      {loading && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="w-10 h-10 border-3 border-indigo-200 dark:border-indigo-800 border-t-indigo-600 dark:border-t-indigo-400 rounded-full animate-spin mb-4" />
          <p className="text-sm text-slate-500 dark:text-slate-400">Loading relays...</p>
        </div>
      )}

      {error && (
        <div className="p-4 rounded-xl bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 text-sm">
          {error}
        </div>
      )}

      {!loading && !error && relays.length === 0 && (
        <EmptyState
          icon={
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
            </svg>
          }
          title="No public relays yet"
          description="Create a public relay to see it listed here."
          action={
            <button
              onClick={() => navigate('/create')}
              className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg transition-colors"
            >
              Create one
            </button>
          }
        />
      )}

      {!loading && !error && relays.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {relays.map((relay, i) => (
            <div key={relay.relay_id} className="animate-fade-in-up" style={{ animationDelay: `${i * 0.05}s` }}>
              <RelayCard relay={relay} />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function Footer() {
  return (
    <footer className="border-t border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-md flex items-center justify-center">
              <svg className="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Agent Relay
            </span>
            <span className="text-xs text-slate-400 dark:text-slate-500">v1.0.0</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-slate-500 dark:text-slate-400">
            <a href="https://github.com/connectwithprakash/agent-relay#readme" target="_blank" rel="noopener noreferrer" className="hover:text-slate-700 dark:hover:text-slate-300 transition-colors">
              Documentation
            </a>
            <a href="http://localhost:8000/docs" target="_blank" rel="noopener noreferrer" className="hover:text-slate-700 dark:hover:text-slate-300 transition-colors">
              API Reference
            </a>
            <a href="https://github.com/connectwithprakash/agent-relay" target="_blank" rel="noopener noreferrer" className="hover:text-slate-700 dark:hover:text-slate-300 transition-colors flex items-center gap-1.5">
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
              </svg>
              GitHub
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}

export default function HomePage() {
  const [joinId, setJoinId] = useState('');
  const [joinCode, setJoinCode] = useState('');
  const [joinCodeError, setJoinCodeError] = useState('');
  const navigate = useNavigate();
  const { relays, loading, error } = useRelayList();

  const handleJoin = async (e) => {
    e.preventDefault();
    const trimmed = joinId.trim();
    if (!trimmed) return;
    setJoinCodeError('');

    // Auto-detect: if it looks like a relay ID (starts with "relay-"), navigate directly
    if (trimmed.startsWith('relay-')) {
      navigate(`/relay/${trimmed}`);
      return;
    }

    // Otherwise treat as a join code
    try {
      const result = await getRelayByCode(trimmed.toUpperCase());
      navigate(`/relay/${result.relay_id}`);
    } catch (err) {
      setJoinCodeError(err.message || 'Invalid relay ID or join code');
    }
  };

  const handleCreateClick = () => navigate('/create');

  return (
    <div>
      <HeroSection
        joinId={joinId}
        setJoinId={setJoinId}
        onJoin={handleJoin}
        joinCodeError={joinCodeError}
        onCreateClick={handleCreateClick}
      />
      <QuickActionCards onCreateClick={handleCreateClick} navigate={navigate} />
      <HowItWorks />
      <PublicRelaysSection relays={relays} loading={loading} error={error} navigate={navigate} />
      <Footer />
    </div>
  );
}
