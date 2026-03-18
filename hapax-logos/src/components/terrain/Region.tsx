import { useCallback, type ReactNode } from "react";
import { useTerrain, type RegionName, type Depth } from "../../contexts/TerrainContext";

interface RegionProps {
  name: RegionName;
  children: (depth: Depth) => ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

const DEPTH_BORDER: Record<Depth, string> = {
  surface: "transparent",
  stratum: "rgba(180, 160, 120, 0.08)",
  core: "rgba(180, 160, 120, 0.15)",
};

const DEPTH_GLOW: Record<Depth, string> = {
  surface: "none",
  stratum: "inset 0 0 20px rgba(180, 160, 120, 0.03)",
  core: "inset 0 0 30px rgba(180, 160, 120, 0.06)",
};

export function Region({ name, children, className = "", style }: RegionProps) {
  const { regionDepths, focusedRegion, cycleDepth, focusRegion } = useTerrain();
  const depth = regionDepths[name];
  const isFocused = focusedRegion === name;

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      // Don't cycle if clicking interactive content in stratum/core
      if (depth !== "surface") {
        const target = e.target as HTMLElement;
        if (target.closest("button, a, input, textarea, [role=button]")) return;
      }

      if (depth === "surface") {
        cycleDepth(name);
        focusRegion(name);
      } else if (depth === "stratum") {
        cycleDepth(name);
      } else {
        cycleDepth(name);
        focusRegion(null);
      }
    },
    [depth, name, cycleDepth, focusRegion],
  );

  return (
    <div
      data-region={name}
      data-depth={depth}
      className={`relative overflow-hidden ${className}`}
      style={{
        borderColor: isFocused ? "rgba(184, 187, 38, 0.12)" : DEPTH_BORDER[depth],
        borderWidth: "1px",
        borderStyle: "solid",
        boxShadow: isFocused
          ? "inset 0 0 24px rgba(184, 187, 38, 0.04)"
          : DEPTH_GLOW[depth],
        transition: "border-color 300ms ease, box-shadow 300ms ease",
        cursor: depth === "core" ? "default" : "pointer",
        ...style,
      }}
      onClick={handleClick}
    >
      {/* Depth indicator */}
      <div
        className="absolute top-1 right-1 text-[8px] uppercase tracking-[0.3em] pointer-events-none"
        style={{
          color: "rgba(180, 160, 120, 0.15)",
          opacity: depth === "surface" ? 0 : 1,
          transition: "opacity 150ms ease",
          zIndex: 2,
        }}
      >
        {depth}
      </div>

      {/* Content */}
      <div
        className="w-full h-full"
        style={{
          opacity: 1,
          transition: "opacity 150ms ease",
        }}
      >
        {children(depth)}
      </div>
    </div>
  );
}
