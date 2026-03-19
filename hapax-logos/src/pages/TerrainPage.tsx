import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { TerrainProvider, useTerrainActions, type RegionName, type Depth, type InvestigationTab } from "../contexts/TerrainContext";
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

function TerrainChrome() {
  const [manualOpen, setManualOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { modal, dismissModal, status: _status } = useHapaxIntrospection();

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const target = e.target as HTMLElement;
      const isInput =
        target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable;

      if ((e.ctrlKey || e.metaKey) && e.key === "p") {
        e.preventDefault();
        setPaletteOpen((prev) => !prev);
        return;
      }

      if (e.key === "?" && !e.ctrlKey && !e.metaKey && !isInput) {
        e.preventDefault();
        setManualOpen((prev) => !prev);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

  return (
    <>
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onManualToggle={() => setManualOpen((prev) => !prev)}
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
    </>
  );
}

export function TerrainPage() {
  return (
    <ToastProvider>
      <AgentRunProvider>
        <TerrainProvider>
          <ErrorBoundary>
            <TerrainParamSync />
            <TerrainLayout />
            <TerrainChrome />
          </ErrorBoundary>
        </TerrainProvider>
      </AgentRunProvider>
    </ToastProvider>
  );
}
