import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AppLayout } from "./layouts/AppLayout";
import { BrandEditor } from "./pages/BrandEditor";
import { Brands } from "./pages/Brands";
import { Dashboard } from "./pages/Dashboard";
import { NewProject } from "./pages/NewProject";
import { ProjectDetail } from "./pages/ProjectDetail";
import { Projects } from "./pages/Projects";
import { SettingsPage } from "./pages/Settings";
import { Welcome } from "./pages/Welcome";
import { api } from "./services/api";

/** First launch goes to the welcome wizard until it is completed or skipped. */
function FirstRunGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const loc = useLocation();
  const nav = useNavigate();
  useEffect(() => {
    // redirect once, on first load only - never after the user has left the wizard
    api.settings()
      .then((s) => { if (!s.settings.onboarding_complete && loc.pathname === "/") nav("/welcome", { replace: true }); })
      .catch(() => undefined)
      .finally(() => setReady(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return ready ? <>{children}</> : null;
}

export default function App() {
  return (
    <BrowserRouter>
      <FirstRunGate>
        <Routes>
          <Route path="/welcome" element={<Welcome />} />
          <Route element={<AppLayout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/new" element={<NewProject />} />
            <Route path="/projects" element={<Projects />} />
            <Route path="/projects/:id" element={<ProjectDetail />} />
            <Route path="/brands" element={<Brands />} />
            <Route path="/brands/:id" element={<BrandEditor />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </FirstRunGate>
    </BrowserRouter>
  );
}
