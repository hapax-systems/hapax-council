import { useCallback, type ReactNode } from "react";
import { useTerrain, type RegionName, type Depth } from "../../contexts/TerrainContext";

interface RegionProps {
  name: RegionName;
  children: (depth: Depth) => ReactNode;
  className?: string;
  style?: React.CSSProperties;
}

const DEPTH_HEIGHTS: Record<Depth, string> = {
  surface: "100%",
  stratum: "100%",
  core: "100%",
};

const DEPTH_BORDER: Record<Depth, string> = {
  surface: "transparent",
  stratum: "rgba(180, 160, 120, 0.08)",
  core: "rgba(180, 160, 120, 0.15)",
};

export function Region({ name, children, className = "", style }: RegionProps) {
  const { regionDepths, cycleDepth, focusRegion } = useTerrain();
  const depth = regionDepths[name];

  const handleClick = useCallback(() => {
    if (depth === "surface") {
      cycleDepth(name);
      focusRegion(name);
    } else if (depth === "stratum") {
      cycleDepth(name);
    } else {
      // core -> surface, unfocus
      cycleDepth(name);
      focusRegion(null);
    }
  }, [depth, name, cycleDepth, focusRegion]);

  return (
    <div
      data-region={name}
      data-depth={depth}
      className={`relative overflow-hidden ${className}`}
      style={{
        height: DEPTH_HEIGHTS[depth],
        borderColor: DEPTH_BORDER[depth],
        borderWidth: "1px",
        borderStyle: "solid",
        transition: "height 200ms ease, border-color 300ms ease",
        cursor: depth === "surface" ? "pointer" : depth === "stratum" ? "pointer" : "default",
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
        }}
      >
        {depth}
      </div>

      {/* Content with depth-aware opacity transition */}
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
