import { useParams, useSearchParams } from 'react-router-dom';
import RelayDashboard from '../components/RelayDashboard';
import SpectatorDashboard from '../components/SpectatorDashboard';
import AgentSelector from '../components/AgentSelector';

export default function RelayPage() {
  const { relayId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const agent = searchParams.get('agent');
  const mode = searchParams.get('mode');

  const handleAgentSelect = (agentName) => {
    setSearchParams({ agent: agentName });
  };

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

  return (
    <div className="flex flex-col" style={{ height: 'calc(100vh - 57px)' }}>
      <div className="flex-1 overflow-hidden">
        <RelayDashboard relayId={relayId} agentName={agent} />
      </div>
    </div>
  );
}
