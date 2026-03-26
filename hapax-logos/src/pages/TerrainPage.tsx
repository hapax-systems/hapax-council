import { lazy, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TerrainProvider, useTerrainActions, type RegionName, type Depth, type InvestigationTab } from "../contexts/TerrainContext";
import { CommandRegistryProvider } from "../contexts/CommandRegistryContext";

const DemoRunner = lazy(() => import("../demo/DemoRunner").then((m) => ({ default: m.DemoRunner })));
import { TerrainLayout } from "../components/terrain/TerrainLayout";
import { ToastProvider } from "../components/shared/ToastProvider";
import { AgentRunProvider } from "../contexts/AgentRunContext";
import { ErrorBoundary } from "../components/shared/ErrorBoundary";
import { CommandPalette } from "../components/shared/CommandPalette";
import { ManualDrawer } from "../components/layout/ManualDrawer";
import { HapaxModal } from "../components/layout/HapaxModal";
import { HealthToastWatcher } from "../components/layout/HealthToastWatcher";
import { useHapaxIntrospection } from "../hooks/useHapaxIntrospection";

const REGIONS: RegionName[] = ["horizon", "field", "ground", "watershed", "bedrock"];
const DEPTHS: Depth[] = ["surface", "stratum", "core"];
const TABS: InvestigationTab[] = ["chat", "insight", "demos"];

function TerrainParamSync() {
  const [params] = useSearchParams();
  const { setRegionDepth, focusRegion, setOverlay, setInvestigationTab } = useTerrainActions();

  useEffect(() => {
    const region = params.get("region") as RegionName | null;
    const depth = params.get("depth") as Depth | null;
    const overlay = params.get("overlay");
    const tab = params.get("tab") as InvestigationTab | null;

    if (region && REGIONS.includes(region)) {
      focusRegion(region);
      if (depth && DEPTHS.includes(depth)) {
        setRegionDepth(region, depth);
      }
    }

    if (overlay === "investigation") {
      setOverlay("investigation");
      if (tab && TABS.includes(tab)) {
        setInvestigationTab(tab);
      }
    }
  }, [params, setRegionDepth, focusRegion, setOverlay, setInvestigationTab]);

  return null;
}

function DemoGate() {
  const [params] = useSearchParams();
  const demoName = params.get("demo");
  if (!demoName) return null;
  return <DemoRunner demoName={demoName} />;
}

export function TerrainPage() {
  const [manualOpen, setManualOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { modal, dismissModal } = useHapaxIntrospection();

  return (
    <ToastProvider>
      <AgentRunProvider>
        <TerrainProvider>
          <CommandRegistryProvider
            onManualToggle={() => setManualOpen((p) => !p)}
            onPaletteToggle={() => setPaletteOpen((p) => !p)}
          >
            <ErrorBoundary>
              <TerrainParamSync />
              <TerrainLayout />
              <CommandPalette
                open={paletteOpen}
                onClose={() => setPaletteOpen(false)}
                onManualToggle={() => setManualOpen((p) => !p)}
              />
              <ManualDrawer open={manualOpen} onClose={() => setManualOpen(false)} />
              <HapaxModal
                visible={modal.visible}
                title={modal.title}
                content={modal.content}
                dismissable={modal.dismissable}
                onDismiss={dismissModal}
              />
              <HealthToastWatcher />
              <DemoGate />
            </ErrorBoundary>
          </CommandRegistryProvider>
        </TerrainProvider>
      </AgentRunProvider>
    </ToastProvider>
  );
}
