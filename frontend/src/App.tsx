import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AppLayout } from "./layouts/AppLayout";
import { BrandDocDetail } from "./pages/BrandDocDetail";
import { BrandDocuments } from "./pages/BrandDocuments";
import { BrandEditor } from "./pages/BrandEditor";
import { Brands } from "./pages/Brands";
import { Dashboard } from "./pages/Dashboard";
import { MediaLibrary } from "./pages/MediaLibrary";
import { NewProject } from "./pages/NewProject";
import { PaperDetail } from "./pages/PaperDetail";
import { ProjectDetail } from "./pages/ProjectDetail";
import { Projects } from "./pages/Projects";
import { ResearchPapers } from "./pages/ResearchPapers";
import { SettingsPage } from "./pages/Settings";
import { Templates } from "./pages/Templates";
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
            <Route path="/papers" element={<ResearchPapers />} />
            <Route path="/papers/:id" element={<PaperDetail />} />
            <Route path="/brand-docs" element={<BrandDocuments />} />
            <Route path="/brand-docs/:id" element={<BrandDocDetail />} />
            <Route path="/templates" element={<Templates />} />
            <Route path="/media" element={<MediaLibrary />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </FirstRunGate>
    </BrowserRouter>
  );
}
