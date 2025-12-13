import RelayDashboard from './components/RelayDashboard';
import './App.css';

function App() {
  // For now, hardcode the relay ID and agent name
  // TODO: Add relay selection UI later
  const relayId = 'relay-Ou9jQcYbJxQ';
  const agentName = 'builder';

  return <RelayDashboard relayId={relayId} agentName={agentName} />;
}

export default App;
