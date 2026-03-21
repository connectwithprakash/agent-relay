import { useState, useCallback } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useRelay } from '../hooks';
import RelayDashboard from '../components/RelayDashboard';
import SpectatorDashboard from '../components/SpectatorDashboard';
import AgentSelector from '../components/AgentSelector';
import WaitingRoom from '../components/WaitingRoom';

function isRelayWaiting(relay) {
  if (!relay) return false;
  if (relay.status === 'open') return true;
  const agents = relay.agent_names || relay.agents || [];
  const minAgents = relay.min_agents || 2;
  return agents.length < minAgents && relay.status !== 'active';
}

export default function RelayPage() {
  const { relayId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const agent = searchParams.get('agent');
  const mode = searchParams.get('mode');

  const { relay, loading, error, updateRelay } = useRelay(relayId);
  const [activated, setActivated] = useState(false);

  const handleAgentSelect = (agentName) => {
    setSearchParams({ agent: agentName });
  };

  const handleActivate = useCallback((updatedRelay) => {
    updateRelay(updatedRelay);
    setActivated(true);
  }, [updateRelay]);

  if (mode === 'watch') {
    return <SpectatorDashboard relayId={relayId} />;
  }

  if (!agent) {
    return (
      <div className="max-w-2xl mx-auto px-4 sm:px-6 py-12">
        <AgentSelector relayId={relayId} onSelect={handleAgentSelect} />
      </div>
    );
  }

  // Show waiting room if relay is open and hasn't been activated
  if (!activated && !loading && !error && relay && isRelayWaiting(relay)) {
    return (
      <WaitingRoom
        relay={relay}
        relayId={relayId}
        onActivate={handleActivate}
      />
    );
  }

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 57px)' }}>
      <div className="flex-1 overflow-hidden">
        <RelayDashboard relayId={relayId} agentName={agent} />
      </div>
    </div>
  );
}
