/**
 * Custom React hooks for Agent Relay
 *
 * These hooks follow SOLID principles:
 * - Single Responsibility: Each hook handles one concern
 * - Open/Closed: Extensible through configuration
 * - Dependency Inversion: Components depend on hooks, not implementation details
 */

export { useRelay } from './useRelay';
export { useWebSocket } from './useWebSocket';
export { useMessages } from './useMessages';
export { useRelayCreation } from './useRelayCreation';
export { useRelayList } from './useRelayList';
export { useSSE } from './useSSE';
