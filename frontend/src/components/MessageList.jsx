import { useEffect, useRef } from 'react';
import AgentAvatar, { getAgentBubbleColor } from './AgentAvatar';
import EmptyState from './EmptyState';

export default function MessageList({ messages, currentAgent }) {
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const formatTime = (timestamp) => {
    return new Date(timestamp).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (messages.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <EmptyState
          icon={
            <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          }
          title="No messages yet"
          description="Start the conversation! Messages will appear here in real time."
        />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4 custom-scrollbar">
      {messages.map((message, index) => {
        const isCurrentAgent = message.agent === currentAgent;
        const bubbleColor = getAgentBubbleColor(message.agent);
        const showAvatar = index === 0 || messages[index - 1]?.agent !== message.agent;

        return (
          <div
            key={message.id}
            className={`flex ${isCurrentAgent ? 'justify-end' : 'justify-start'} animate-fade-in`}
            style={{ animationDelay: `${Math.min(index * 0.02, 0.3)}s` }}
          >
            <div className={`flex items-end gap-2 max-w-[80%] sm:max-w-[70%] ${isCurrentAgent ? 'flex-row-reverse' : ''}`}>
              {/* Avatar */}
              <div className={`flex-shrink-0 ${showAvatar ? 'visible' : 'invisible'}`}>
                <AgentAvatar name={message.agent} size="xs" />
              </div>

              {/* Bubble */}
              <div>
                {/* Agent name + time */}
                {showAvatar && (
                  <div className={`flex items-center gap-2 mb-1 px-1 ${isCurrentAgent ? 'justify-end' : ''}`}>
                    <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
                      {message.agent}
                    </span>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">
                      {formatTime(message.created_at)}
                    </span>
                  </div>
                )}

                <div
                  className={`
                    px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words
                    ${isCurrentAgent
                      ? `${bubbleColor.bg} ${bubbleColor.text} chat-bubble-self`
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-900 dark:text-slate-100 chat-bubble-other'
                    }
                    ${!showAvatar && !isCurrentAgent ? 'rounded-2xl' : ''}
                    ${!showAvatar && isCurrentAgent ? 'rounded-2xl' : ''}
                  `}
                >
                  {message.content}
                </div>

                {/* Timestamp for consecutive messages from same agent */}
                {!showAvatar && (
                  <div className={`flex px-1 mt-0.5 ${isCurrentAgent ? 'justify-end' : ''}`}>
                    <span className="text-[10px] text-slate-400 dark:text-slate-500">
                      {formatTime(message.created_at)}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
      <div ref={messagesEndRef} />
    </div>
  );
}
