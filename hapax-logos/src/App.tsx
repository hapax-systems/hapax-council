import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";

// Eagerly loaded: default route
const TerrainPage = lazy(() => import("./pages/TerrainPage").then((m) => ({ default: m.TerrainPage })));
// Lazy loaded: secondary routes
const HapaxPage = lazy(() => import("./pages/HapaxPage").then((m) => ({ default: m.HapaxPage })));

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
