import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import HomePage from './pages/HomePage';
import CreateRelayPage from './pages/CreateRelayPage';
import RelayPage from './pages/RelayPage';
import NotFoundPage from './pages/NotFoundPage';
import { ToastProvider } from './components/Toast';

function App() {
  return (
    <ToastProvider>
      <Layout>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/create" element={<CreateRelayPage />} />
            <Route path="/relay/:relayId" element={<RelayPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </ErrorBoundary>
      </Layout>
    </ToastProvider>
  );
}

export default App;
