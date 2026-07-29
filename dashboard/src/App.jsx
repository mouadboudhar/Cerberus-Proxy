import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router';
import { ThemeProvider } from './context/ThemeContext';
import { AppProvider } from './context/AppContext';
import { getToken } from './hooks/useApi';
import Sidebar from './components/Sidebar';

import LoginPage      from './pages/LoginPage';
import OverviewPage   from './pages/OverviewPage';
import EndpointsPage  from './pages/EndpointsPage';
import ApiKeysPage    from './pages/ApiKeysPage';
import AuditLogPage   from './pages/AuditLogPage';
import GuardConfigPage from './pages/GuardConfigPage';
import AccountPage    from './pages/AccountPage';
import SettingsPage   from './pages/SettingsPage';

function RequireAuth({ children }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return children;
}

function Shell() {
  return (
    <div
      className="flex h-screen overflow-hidden"
      style={{ background: 'var(--bg)' }}
    >
      <Sidebar />
      <main className="flex flex-col flex-1 min-w-0 overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/"
            element={
              <RequireAuth>
                <AppProvider>
                  <Shell />
                </AppProvider>
              </RequireAuth>
            }
          >
            <Route index element={<Navigate to="/overview" replace />} />
            <Route path="overview"  element={<OverviewPage />} />
            <Route path="endpoints" element={<EndpointsPage />} />
            <Route path="keys"      element={<ApiKeysPage />} />
            <Route path="audit"     element={<AuditLogPage />} />
            <Route path="guards"    element={<GuardConfigPage />} />
            <Route path="account"   element={<AccountPage />} />
            <Route path="settings"  element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  );
}
