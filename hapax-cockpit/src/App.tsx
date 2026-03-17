import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Layout } from "./components/layout/Layout";
import { DashboardPage } from "./pages/DashboardPage";
import { ChatPage } from "./pages/ChatPage";
import { DemosPage } from "./pages/DemosPage";
import { InsightPage } from "./pages/InsightPage";
import { StudioPage } from "./pages/StudioPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<DashboardPage />} />
          <Route path="chat" element={<ChatPage />} />
          <Route path="insight" element={<InsightPage />} />
          <Route path="demos" element={<DemosPage />} />
          <Route path="studio" element={<StudioPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
