import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/layout/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { ChatPage } from "./pages/ChatPage";
import { DemosPage } from "./pages/DemosPage";
import { FlowPage } from "./pages/FlowPage";
import { InsightPage } from "./pages/InsightPage";
import { StudioPage } from "./pages/StudioPage";
import { VisualPage } from "./pages/VisualPage";
import { HapaxPage } from "./pages/HapaxPage";
import { TerrainPage } from "./pages/TerrainPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Terrain — spatial regions, no chrome */}
        <Route path="terrain" element={<TerrainPage />} />
        {/* Hapax Corpora — full-screen, no chrome */}
        <Route path="hapax" element={<HapaxPage />} />
        {/* Main app with layout shell */}
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="flow" element={<FlowPage />} />
          <Route path="insight" element={<InsightPage />} />
          <Route path="demos" element={<DemosPage />} />
          <Route path="studio" element={<StudioPage />} />
          <Route path="visual" element={<VisualPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
