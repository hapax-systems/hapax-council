import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
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
        {/* Terrain — default, spatial regions, no chrome */}
        <Route index element={<TerrainPage />} />
        <Route path="terrain" element={<TerrainPage />} />
        {/* Hapax Corpora — full-screen standalone escape hatch */}
        <Route path="hapax" element={<HapaxPage />} />
        {/* Legacy layout routes — kept for deep links and escape hatch */}
        <Route path="legacy" element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="flow" element={<FlowPage />} />
          <Route path="insight" element={<InsightPage />} />
          <Route path="demos" element={<DemosPage />} />
          <Route path="studio" element={<StudioPage />} />
          <Route path="visual" element={<VisualPage />} />
        </Route>
        {/* Old route redirects → terrain */}
        <Route path="chat" element={<Navigate to="/?overlay=investigation&tab=chat" replace />} />
        <Route
          path="insight"
          element={<Navigate to="/?overlay=investigation&tab=insight" replace />}
        />
        <Route
          path="demos"
          element={<Navigate to="/?overlay=investigation&tab=demos" replace />}
        />
        <Route path="flow" element={<Navigate to="/?region=watershed&depth=core" replace />} />
        <Route path="studio" element={<Navigate to="/?region=ground&depth=core" replace />} />
        <Route path="visual" element={<Navigate to="/?region=bedrock&depth=core" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
