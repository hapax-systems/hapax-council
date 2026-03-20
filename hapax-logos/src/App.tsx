import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

// Eagerly loaded: default route
const TerrainPage = lazy(() => import("./pages/TerrainPage").then((m) => ({ default: m.TerrainPage })));
// Lazy loaded: secondary routes
const HapaxPage = lazy(() => import("./pages/HapaxPage").then((m) => ({ default: m.HapaxPage })));
const Layout = lazy(() => import("./components/layout/Layout").then((m) => ({ default: m.Layout })));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const ChatPage = lazy(() => import("./pages/ChatPage").then((m) => ({ default: m.ChatPage })));
const DemosPage = lazy(() => import("./pages/DemosPage").then((m) => ({ default: m.DemosPage })));
const FlowPage = lazy(() => import("./pages/FlowPage").then((m) => ({ default: m.FlowPage })));
const InsightPage = lazy(() => import("./pages/InsightPage").then((m) => ({ default: m.InsightPage })));
const StudioPage = lazy(() => import("./pages/StudioPage").then((m) => ({ default: m.StudioPage })));
const VisualPage = lazy(() => import("./pages/VisualPage").then((m) => ({ default: m.VisualPage })));

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div className="flex h-screen items-center justify-center bg-[#1d2021] text-zinc-600 text-xs">loading...</div>}>
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
      </Suspense>
    </BrowserRouter>
  );
}
