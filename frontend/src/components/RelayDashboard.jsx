import { useMemo } from 'react';
import { useRelay, useWebSocket, useMessages } from '../hooks';
import TurnIndicator from './TurnIndicator';
import MessageList from './MessageList';
import MessageInput from './MessageInput';

/**
 * RelayDashboard - Main relay interface component
 *
 * REFACTORED for SOLID principles:
 * - Single Responsibility: Only handles UI rendering and composition
 * - Open/Closed: Extensible through hooks configuration
 * - Dependency Inversion: Depends on hooks abstraction, not direct API calls
 *
 * Before: 128 lines with mixed concerns (data fetching, WebSocket, state, UI)
 * After: ~80 lines focused on UI composition
 */
export default function RelayDashboard({ relayId, agentName }) {
  // Relay state management (replaces useEffect + useState combo)
  const { relay, loading: relayLoading, error: relayError, updateRelay } = useRelay(relayId);

  // Message state management
  const {
    messages,
    loading: messagesLoading,
    error: messagesError,
    addMessage,
    send: sendMessageFn,
  } = useMessages(relayId, agentName);

  // WebSocket URL configuration
  const wsUrl = useMemo(() => {
    const apiUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
    const wsProtocol = apiUrl.replace('https://', 'wss://').replace('http://', 'ws://');
    return `${wsProtocol}/relays/${relayId}/ws?agent=${agentName}`;
  }, [relayId, agentName]);

  // WebSocket connection with auto-reconnection
  const { connectionStatus } = useWebSocket(wsUrl, {
    enabled: !!relayId && !!agentName,
    onMessage: (message) => {
      // Add new message from WebSocket
      addMessage(message);
      // Update relay state with new turn
      if (message.next_turn) {
        updateRelay({ current_turn: message.next_turn });
      }
    },
    onOpen: () => console.log('[Dashboard] WebSocket connected'),
    onClose: () => console.log('[Dashboard] WebSocket closed'),
    reconnectInterval: 3000,
    maxReconnectAttempts: 5,
  });

  // Handle message sending
  const handleSendMessage = async (content) => {
    const response = await sendMessageFn(content);
    // Update relay with new turn from API response
    if (response?.next_turn) {
      updateRelay({ current_turn: response.next_turn });
    }
  };

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
          {connectionStatus === 'failed' && (
            <p className="mt-2 text-sm">
              WebSocket connection failed after maximum retry attempts.
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-gray-100 dark:bg-gray-900">
      {/* Header */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700 p-4">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            Agent Relay Dashboard
          </h1>
          <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-400">
            <span>
              Relay ID: <span className="font-mono">{relayId}</span>
            </span>
            <span>•</span>
            <span>
              Agent: <span className="font-semibold">{agentName}</span>
            </span>
            <span>•</span>
            <span>Messages: {relay?.message_count || messages.length}</span>
            <span>•</span>
            <span className={`font-medium ${
              connectionStatus === 'connected' ? 'text-green-500' :
              connectionStatus === 'reconnecting' ? 'text-yellow-500' :
              connectionStatus === 'connecting' ? 'text-blue-500' :
              'text-gray-500'
            }`}>
              {connectionStatus === 'connected' ? '● Live' :
               connectionStatus === 'reconnecting' ? '◐ Reconnecting...' :
               connectionStatus === 'connecting' ? '○ Connecting...' :
               '○ Offline'}
            </span>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 max-w-6xl w-full mx-auto flex flex-col my-4 bg-white dark:bg-gray-800 rounded-lg shadow-lg overflow-hidden">
        {/* Turn Indicator */}
        <div className="p-4 border-b border-gray-200 dark:border-gray-700">
          <TurnIndicator currentTurn={relay?.current_turn} agentName={agentName} />
        </div>

        {/* Message List */}
        <MessageList messages={messages} currentAgent={agentName} />

        {/* Message Input */}
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
