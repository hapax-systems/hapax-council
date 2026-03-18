import { TerrainProvider } from "../contexts/TerrainContext";
import { TerrainLayout } from "../components/terrain/TerrainLayout";

export function TerrainPage() {
  return (
    <TerrainProvider>
      <TerrainLayout />
    </TerrainProvider>
  );
}
