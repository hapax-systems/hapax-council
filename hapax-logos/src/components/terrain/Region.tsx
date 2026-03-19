import { useCallback, useState, type ReactNode } from "react";
import { useTerrain, type RegionName, type Depth } from "../../contexts/TerrainContext";
import type { StimmungStance } from "../../hooks/useVisualLayer";

interface RegionProps {
  name: RegionName;
  children: (depth: Depth) => ReactNode;
  className?: string;
  style?: React.CSSProperties;
  stimmungStance?: StimmungStance;
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

function stimmungBorderStyle(
  stance: StimmungStance | undefined,
  baseBorder: string,
): { borderColor: string; animation?: string; boxShadow?: string } {
  if (!stance || stance === "nominal") {
    return { borderColor: baseBorder };
  }
  if (stance === "cautious") {
    // 15% yellow blend
    return { borderColor: "rgba(250, 189, 47, 0.15)" };
  }
  if (stance === "degraded") {
    return {
      borderColor: "rgba(254, 128, 25, 0.25)",
      animation: "stimmung-breathe-degraded 6s ease-in-out infinite",
      boxShadow: "inset 0 0 8px rgba(254, 128, 25, 0.06)",
    };
  }
  // critical
  return {
    borderColor: "rgba(251, 73, 52, 0.35)",
    animation: "stimmung-breathe-critical 2s ease-in-out infinite",
    boxShadow: "inset 0 0 12px rgba(251, 73, 52, 0.08)",
  };
}

export function Region({ name, children, className = "", style, stimmungStance }: RegionProps) {
  const { regionDepths, focusedRegion, cycleDepth, focusRegion } = useTerrain();
  const depth = regionDepths[name];
  const isFocused = focusedRegion === name;
  const [isHovered, setIsHovered] = useState(false);

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

  const baseBorder = isFocused
    ? "rgba(184, 187, 38, 0.12)"
    : isHovered && depth === "surface"
      ? "rgba(180, 160, 120, 0.12)"
      : DEPTH_BORDER[depth];
  const stimmung = stimmungBorderStyle(stimmungStance, baseBorder);

  const hoverGlow =
    isHovered && depth === "surface" && !isFocused
      ? "inset 0 0 16px rgba(180, 160, 120, 0.04)"
      : undefined;

  return (
    <div
      data-region={name}
      data-depth={depth}
      className={`relative overflow-hidden ${className}`}
      style={{
        borderColor: stimmung.borderColor,
        borderWidth: "1px",
        borderStyle: "solid",
        boxShadow: stimmung.boxShadow ?? hoverGlow ?? (isFocused
          ? "inset 0 0 24px rgba(184, 187, 38, 0.04)"
          : DEPTH_GLOW[depth]),
        animation: stimmung.animation,
        transition: "border-color 300ms ease, box-shadow 300ms ease",
        cursor: depth === "core" ? "default" : "pointer",
        ...style,
      }}
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Depth indicator */}
      <div
        className="absolute top-1 right-1 text-[9px] uppercase tracking-[0.3em] pointer-events-none"
        style={{
          color: "rgba(180, 160, 120, 0.3)",
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
