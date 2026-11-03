import { Navigate, Route, Routes } from "react-router-dom";
import { ServerOff } from "lucide-react";
import { useAuth } from "./lib/auth";
import { ProjectProvider } from "./lib/project";
import Layout from "./components/Layout";
import { Button, Loading } from "./components/ui";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Requirements from "./pages/Requirements";
import TestDesigner from "./pages/TestDesigner";
import TestCases from "./pages/TestCases";
import TestSets from "./pages/TestSets";
import Incidents from "./pages/Incidents";
import IncidentStudio from "./pages/IncidentStudio";
import Releases from "./pages/Releases";
import Sync from "./pages/Sync";
import Audit from "./pages/Audit";
import Integrations from "./pages/Integrations";
import Settings from "./pages/Settings";

export default function App() {
  const { status, retry } = useAuth();
  if (status === "loading") return <Loading label="Starting TouQA AI…" />;
  if (status === "offline")
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center">
        <ServerOff className="h-8 w-8 text-muted-foreground" />
        <h1 className="text-lg font-semibold">Backend unavailable</h1>
        <p className="max-w-md text-sm text-muted-foreground">
          The TouQA API could not be reached. Start the backend (see README) or check <code>VITE_API_URL</code>.
        </p>
        <Button onClick={retry}>Try again</Button>
      </div>
    );
  if (status === "signed_out") return <Login />;
  return (
    <ProjectProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="requirements" element={<Requirements />} />
          <Route path="requirements/:id" element={<Requirements />} />
          <Route path="designer" element={<TestDesigner />} />
          <Route path="test-cases" element={<TestCases />} />
          <Route path="test-sets" element={<TestSets />} />
          <Route path="incidents" element={<Incidents />} />
          <Route path="incident-studio" element={<IncidentStudio />} />
          <Route path="incident-studio/:id" element={<IncidentStudio />} />
          <Route path="releases" element={<Releases />} />
          <Route path="sync" element={<Sync />} />
          <Route path="audit" element={<Audit />} />
          <Route path="integrations" element={<Integrations />} />
          <Route path="settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </ProjectProvider>
  );
}
