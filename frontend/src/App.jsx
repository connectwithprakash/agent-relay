import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import HomePage from './pages/HomePage';
import CreateRelayPage from './pages/CreateRelayPage';
import RelayPage from './pages/RelayPage';

function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/create" element={<CreateRelayPage />} />
        <Route path="/relay/:relayId" element={<RelayPage />} />
      </Routes>
    </Layout>
  );
}

export default App;
