import { useMemo } from 'react';
import { useRelay, useSSE, useMessages } from '../hooks';
import MessageList from './MessageList';
import { getToken } from '../utils/auth';

/**
 * SpectatorDashboard - Read-only spectator view for watching relay conversations
 *
 * Uses Server-Sent Events instead of WebSocket for a lightweight, read-only
 * connection. No message input or turn participation.
 *
 * @param {string} relayId - The relay to watch
 */
export default function SpectatorDashboard({ relayId }) {
  const token = getToken(relayId) || '';
  const { relay, loading: relayLoading, error: relayError, updateRelay } = useRelay(relayId);

  const {
    messages,
    loading: messagesLoading,
    error: messagesError,
    addMessage,
  } = useMessages(relayId, null);

  const sseUrl = useMemo(() => {
    const apiUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    return `${apiUrl}/relays/${relayId}/watch`;
  }, [relayId]);

  const { connectionStatus } = useSSE(sseUrl, {
    enabled: !!relayId,
    token,
    onMessage: (message) => {
      addMessage(message);
      if (message.next_turn) {
        updateRelay({ current_turn: message.next_turn });
      }
    },
    onOpen: () => console.log('[Spectator] SSE connected'),
    onError: () => console.log('[Spectator] SSE error'),
  });

  // Loading state
  if (relayLoading || messagesLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-100 dark:bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading relay...</p>
        </div>
      </div>
    );
  }

  // Error state
  const error = relayError || messagesError;
  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-100 dark:bg-gray-900">
        <div className="bg-red-100 dark:bg-red-900 border border-red-400 dark:border-red-700 text-red-700 dark:text-red-200 px-6 py-4 rounded-lg max-w-md">
          <p className="font-bold mb-2">Error</p>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-gray-100 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-4">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center gap-3 mb-2">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              Agent Relay Dashboard
            </h1>
            {/* Spectator Mode Badge */}
            <span className="inline-flex items-center gap-1.5 px-3 py-1 text-sm font-semibold bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 rounded-full border border-amber-300 dark:border-amber-700">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
              Spectator Mode
            </span>
          </div>
          <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-400">
            <span>
              Relay ID: <span className="font-mono">{relayId}</span>
            </span>
            <span>|</span>
            <span>
              Watching as <span className="font-semibold text-amber-600 dark:text-amber-400">spectator</span>
            </span>
            <span>|</span>
            <span>Messages: {relay?.message_count || messages.length}</span>
            {relay?.current_turn && (
              <>
                <span>|</span>
                <span>
                  Turn: <span className="font-semibold">{relay.current_turn}</span>
                </span>
              </>
            )}
            <span>|</span>
            <span className={`font-medium ${
              connectionStatus === 'connected' ? 'text-green-500' :
              connectionStatus === 'error' ? 'text-red-500' :
              connectionStatus === 'connecting' ? 'text-blue-500' :
              'text-gray-500'
            }`}>
              {connectionStatus === 'connected' ? '● Live' :
               connectionStatus === 'connecting' ? '○ Connecting...' :
               connectionStatus === 'error' ? '● Error' :
               '○ Offline'}
            </span>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 max-w-6xl w-full mx-auto flex flex-col my-4 bg-white dark:bg-gray-800 rounded-lg shadow-lg overflow-hidden">
        {/* Info Banner */}
        <div className="p-3 bg-amber-50 dark:bg-amber-900/20 border-b border-amber-200 dark:border-amber-800">
          <div className="flex items-center gap-2 text-sm text-amber-700 dark:text-amber-300">
            <svg className="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            <span>You are watching this relay in read-only mode. New messages will appear in real-time.</span>
          </div>
        </div>

        {/* Message List */}
        <MessageList messages={messages} currentAgent={null} />

        {/* Read-only footer */}
        <div className="p-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
          <p className="text-center text-sm text-gray-400 dark:text-gray-500">
            Spectator mode -- read-only view
          </p>
        </div>
      </div>
    </div>
  );
}
