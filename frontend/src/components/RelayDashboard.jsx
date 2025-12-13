import { useState, useEffect, useRef } from 'react';
import { getRelay, getHistory, sendMessage, connectWebSocket } from '../utils/api';
import TurnIndicator from './TurnIndicator';
import MessageList from './MessageList';
import MessageInput from './MessageInput';

export default function RelayDashboard({ relayId, agentName }) {
  const [relay, setRelay] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const wsRef = useRef(null);

  // Fetch relay state and message history
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [relayData, historyData] = await Promise.all([
          getRelay(relayId),
          getHistory(relayId),
        ]);
        setRelay(relayData);
        setMessages(historyData.messages || []);
        setError(null);
      } catch (err) {
        setError(err.message);
        console.error('Failed to fetch relay data:', err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [relayId]);

  // Set up WebSocket connection for real-time updates
  useEffect(() => {
    if (!relayId || !agentName) return;

    // Connect to WebSocket
    const ws = connectWebSocket(relayId, agentName, (message) => {
      // Add new message to the list
      setMessages((prev) => [...prev, message]);
      // Update current turn
      setRelay((prev) => ({ ...prev, current_turn: message.next_turn }));
    });

    // Store WebSocket reference
    wsRef.current = ws;

    // Cleanup: close WebSocket when component unmounts
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [relayId, agentName]);

  // Handle sending messages
  const handleSendMessage = async (content) => {
    const response = await sendMessage(relayId, content, agentName);
    // Update relay state with new turn
    setRelay((prev) => ({ ...prev, current_turn: response.next_turn }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-100 dark:bg-gray-900">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <p className="text-gray-600 dark:text-gray-400">Loading relay...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-100 dark:bg-gray-900">
        <div className="bg-red-100 dark:bg-red-900 border border-red-400 dark:border-red-700 text-red-700 dark:text-red-200 px-6 py-4 rounded-lg">
          <p className="font-bold">Error</p>
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
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            Agent Relay Dashboard
          </h1>
          <div className="flex items-center gap-4 text-sm text-gray-600 dark:text-gray-400">
            <span>Relay ID: <span className="font-mono">{relayId}</span></span>
            <span>•</span>
            <span>Agent: <span className="font-semibold">{agentName}</span></span>
            <span>•</span>
            <span>Messages: {relay?.message_count || 0}</span>
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
          disabled={false}
        />
      </div>
    </div>
  );
}
