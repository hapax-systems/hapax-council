import { useReactFlow } from "@xyflow/react";
import { useStudioGraph, type StudioGraphState } from "../../stores/studioGraphStore";

type S = StudioGraphState;

export function GraphToolbar() {
  const { fitView, zoomIn, zoomOut } = useReactFlow();
  const graphName = useStudioGraph((s: S) => s.graphName);
  const graphDirty = useStudioGraph((s: S) => s.graphDirty);
  const hapaxLocked = useStudioGraph((s: S) => s.hapaxLocked);
  const toggleHapaxLock = useStudioGraph((s: S) => s.toggleHapaxLock);

  return (
    <div
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        right: 0,
        height: 36,
        background: "var(--color-bg1)",
        borderBottom: "1px solid var(--color-bg3)",
        display: "flex",
        alignItems: "center",
        padding: "0 12px",
        gap: 12,
        zIndex: 10,
        fontSize: 13,
      }}
    >
      <span style={{ color: "var(--color-fg1)", fontWeight: 600 }}>
        {graphName}
        {graphDirty && <span style={{ color: "var(--color-yellow)", marginLeft: 4 }}>*</span>}
      </span>

      <div style={{ flex: 1 }} />

      <button
        onClick={toggleHapaxLock}
        title={
          hapaxLocked ? "Hapax suppressed — click to allow" : "Hapax active — click to suppress"
        }
        style={{
          background: "none",
          border: "1px solid var(--color-bg3)",
          borderRadius: 4,
          padding: "2px 8px",
          color: hapaxLocked ? "var(--color-red)" : "var(--color-green)",
          cursor: "pointer",
          fontSize: 12,
        }}
      >
        {hapaxLocked ? "Hapax locked" : "Hapax active"}
      </button>

      <button
        onClick={() => zoomOut()}
        style={{ background: "none", border: "none", color: "var(--color-fg4)", cursor: "pointer" }}
      >
        −
      </button>
      <button
        onClick={() => zoomIn()}
        style={{ background: "none", border: "none", color: "var(--color-fg4)", cursor: "pointer" }}
      >
        +
      </button>
      <button
        onClick={() => fitView({ padding: 0.2 })}
        style={{
          background: "none",
          border: "1px solid var(--color-bg3)",
          borderRadius: 4,
          padding: "2px 8px",
          color: "var(--color-fg4)",
          cursor: "pointer",
          fontSize: 12,
        }}
      >
        Fit
      </button>
    </div>
  );
}
