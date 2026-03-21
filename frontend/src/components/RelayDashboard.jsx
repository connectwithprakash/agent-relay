import { useMemo } from 'react';
import { useRelay, useWebSocket, useMessages } from '../hooks';
import { getApiKey } from '../utils/auth';
import TurnIndicator from './TurnIndicator';
import MessageList from './MessageList';
import MessageInput from './MessageInput';
import ConnectionBadge from './ConnectionBadge';
import AgentAvatar from './AgentAvatar';

export default function RelayDashboard({ relayId, agentName }) {
  const { relay, loading: relayLoading, error: relayError, updateRelay } = useRelay(relayId);

  const {
    messages,
    loading: messagesLoading,
    error: messagesError,
    addMessage,
    send: sendMessageFn,
  } = useMessages(relayId, agentName);

  const wsUrl = useMemo(() => {
    const apiUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    const wsProtocol = apiUrl.replace('https://', 'wss://').replace('http://', 'ws://');
    const apiKey = getApiKey(relayId);
    let url = `${wsProtocol}/relays/${relayId}/ws?agent=${agentName}`;
    if (apiKey) url += `&api_key=${encodeURIComponent(apiKey)}`;
    return url;
  }, [relayId, agentName]);

  const { connectionStatus } = useWebSocket(wsUrl, {
    enabled: !!relayId && !!agentName,
    onMessage: (message) => {
      addMessage(message);
      if (message.next_turn) {
        updateRelay({ current_turn: message.next_turn });
      }
    },
    onOpen: () => console.log('[Dashboard] WebSocket connected'),
    onClose: () => console.log('[Dashboard] WebSocket closed'),
    reconnectInterval: 3000,
    maxReconnectAttempts: 5,
  });

  const handleSendMessage = async (content) => {
    const response = await sendMessageFn(content);
    if (response?.next_turn) {
      updateRelay({ current_turn: response.next_turn });
    }
  };

  // Loading state
  if (relayLoading || messagesLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-50 dark:bg-slate-950">
        <div className="text-center animate-fade-in">
          <div className="w-12 h-12 border-3 border-indigo-200 dark:border-indigo-800 border-t-indigo-600 dark:border-t-indigo-400 rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-500 dark:text-slate-400 font-medium">Loading relay...</p>
        </div>
      </div>
    );
  }

  // Error state
  const error = relayError || messagesError;
  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-slate-50 dark:bg-slate-950 px-4">
        <div className="max-w-md w-full p-6 bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-red-200 dark:border-red-800 animate-scale-in">
          <div className="w-12 h-12 rounded-full bg-red-100 dark:bg-red-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white text-center mb-2">
            Connection Error
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 text-center">{error}</p>
          {connectionStatus === 'failed' && (
            <p className="text-xs text-slate-400 dark:text-slate-500 text-center mt-2">
              WebSocket connection failed after maximum retry attempts.
            </p>
          )}
        </div>
      </div>
    );
  }

  const agents = relay?.agent_names || relay?.agents || [];

  // Handle relay deactivation (e.g., agent left, relay closed)
  if (relay && relay.status !== 'active') {
    const statusLabel = relay.status === 'open' ? 'waiting for agents' : relay.status || 'inactive';
    return (
      <div className="flex items-center justify-center h-screen bg-slate-50 dark:bg-slate-950 px-4">
        <div className="max-w-md w-full p-6 bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-amber-200 dark:border-amber-800 animate-scale-in text-center">
          <div className="w-12 h-12 rounded-full bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6 text-amber-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
            Relay {statusLabel}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            This relay is no longer active. An agent may have left or the relay was closed.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Refresh
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-slate-50 dark:bg-slate-950">
      {/* Dashboard Header */}
      <div className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 px-4 sm:px-6 py-3">
        <div className="max-w-5xl mx-auto">
          {/* Top row */}
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <h1 className="text-lg font-bold text-slate-900 dark:text-white">
                Relay Dashboard
              </h1>
              <ConnectionBadge status={connectionStatus} />
            </div>
            <div className="hidden sm:flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 20l4-16m2 16l4-16M6 9h14M4 15h14" />
              </svg>
              <span className="font-mono">{relayId.substring(0, 12)}...</span>
            </div>
          </div>

          {/* Agent row */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {/* Agent avatars */}
              <div className="flex items-center -space-x-1.5">
                {agents.map((agent) => (
                  <AgentAvatar
                    key={agent}
                    name={agent}
                    size="xs"
                    active={agent === relay?.current_turn}
                  />
                ))}
              </div>

              <div className="flex items-center gap-2 text-sm text-slate-600 dark:text-slate-400">
                <span>
                  Viewing as <span className="font-semibold text-slate-900 dark:text-white">{agentName}</span>
                </span>
                <span className="text-slate-300 dark:text-slate-600">|</span>
                <span>{relay?.message_count || messages.length} messages</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 max-w-5xl w-full mx-auto flex flex-col my-3 sm:my-4 mx-3 sm:mx-auto bg-white dark:bg-slate-900 rounded-2xl shadow-lg border border-slate-200 dark:border-slate-800 overflow-hidden">
        {/* Turn Indicator */}
        <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-800">
          <TurnIndicator
            currentTurn={relay?.current_turn}
            agentName={agentName}
            agents={agents}
          />
        </div>

        {/* Messages */}
        <MessageList messages={messages} currentAgent={agentName} />

        {/* Input */}
        <MessageInput
          onSendMessage={handleSendMessage}
          currentTurn={relay?.current_turn}
          agentName={agentName}
          disabled={connectionStatus !== 'connected'}
        />
      </div>
    </div>
  );
}
