import { useCallback, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
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
  stratum: "color-mix(in srgb, var(--color-zinc-500) 8%, transparent)",
  core: "color-mix(in srgb, var(--color-zinc-500) 15%, transparent)",
};

const DEPTH_GLOW: Record<Depth, string> = {
  surface: "none",
  stratum: "inset 0 0 20px color-mix(in srgb, var(--color-zinc-500) 3%, transparent)",
  core: "inset 0 0 30px color-mix(in srgb, var(--color-zinc-500) 6%, transparent)",
};

function stimmungBorderStyle(
  stance: StimmungStance | undefined,
  baseBorder: string,
): { borderColor: string; animation?: string; boxShadow?: string } {
  if (!stance || stance === "nominal") {
    return { borderColor: baseBorder };
  }
  if (stance === "cautious") {
    return { borderColor: "color-mix(in srgb, var(--color-yellow-400) 15%, transparent)" };
  }
  if (stance === "degraded") {
    return {
      borderColor: "color-mix(in srgb, var(--color-orange-400) 25%, transparent)",
      animation: "stimmung-breathe-degraded 6s ease-in-out infinite",
      boxShadow: "inset 0 0 8px color-mix(in srgb, var(--color-orange-400) 6%, transparent)",
    };
  }
  // critical
  return {
    borderColor: "color-mix(in srgb, var(--color-red-400) 35%, transparent)",
    animation: "stimmung-breathe-critical 2s ease-in-out infinite",
    boxShadow: "inset 0 0 12px color-mix(in srgb, var(--color-red-400) 8%, transparent)",
  };
}

export function Region({ name, children, className = "", style, stimmungStance }: RegionProps) {
  const { regionDepths, focusedRegion, highlightedRegion, cycleDepth, focusRegion } = useTerrain();
  const depth = regionDepths[name];
  const isFocused = focusedRegion === name;
  const isHighlighted = highlightedRegion === name;
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
    ? "color-mix(in srgb, var(--color-green-400) 12%, transparent)"
    : isHovered && depth === "surface"
      ? "color-mix(in srgb, var(--color-zinc-500) 12%, transparent)"
      : DEPTH_BORDER[depth];
  const stimmung = stimmungBorderStyle(stimmungStance, baseBorder);

  const hoverGlow =
    isHovered && depth === "surface" && !isFocused
      ? "inset 0 0 16px color-mix(in srgb, var(--color-zinc-500) 4%, transparent)"
      : undefined;

  return (
    <div
      data-region={name}
      data-depth={depth}
      className={`relative overflow-hidden ${className}`}
      style={{
        borderColor: isHighlighted ? "color-mix(in srgb, var(--color-yellow-400) 60%, transparent)" : stimmung.borderColor,
        borderWidth: "1px",
        borderStyle: "solid",
        boxShadow: isHighlighted
          ? "inset 0 0 8px color-mix(in srgb, var(--color-yellow-400) 15%, transparent), 0 0 12px color-mix(in srgb, var(--color-yellow-400) 30%, transparent)"
          : stimmung.boxShadow ?? hoverGlow ?? (isFocused
            ? "inset 0 0 24px color-mix(in srgb, var(--color-green-400) 4%, transparent)"
            : DEPTH_GLOW[depth]),
        animation: isHighlighted ? "demo-highlight 0.8s ease-in-out infinite" : stimmung.animation,
        transition: "border-color 300ms ease, box-shadow 300ms ease",
        cursor: depth === "core" ? "default" : "pointer",
        ...style,
      }}
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Depth indicator — 3-dot nav, clickable to jump */}
      <DepthDots name={name} depth={depth} />

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

const DEPTHS: Depth[] = ["surface", "stratum", "core"];

function DepthDots({ name, depth }: { name: RegionName; depth: Depth }) {
  const { setRegionDepth, focusRegion } = useTerrain();
  const currentIdx = DEPTHS.indexOf(depth);

  const jump = useCallback(
    (e: ReactMouseEvent, target: Depth) => {
      e.stopPropagation();
      if (target === depth) return;
      setRegionDepth(name, target);
      if (target === "surface") {
        focusRegion(null);
      } else {
        focusRegion(name);
      }
    },
    [name, depth, setRegionDepth, focusRegion],
  );

  return (
    <div
      className="absolute top-1.5 right-1.5 flex gap-1 items-center"
      style={{ zIndex: 2, opacity: depth === "surface" ? 0 : 1, transition: "opacity 150ms ease" }}
      role="navigation"
      aria-label={`${name} depth: ${depth}`}
    >
      {DEPTHS.map((d, i) => (
        <button
          key={d}
          onClick={(e) => jump(e, d)}
          aria-label={d}
          aria-current={i === currentIdx ? "step" : undefined}
          className="block rounded-full"
          style={{
            width: 6,
            height: 6,
            background:
              i === currentIdx
                ? "color-mix(in srgb, var(--color-green-400) 50%, transparent)"
                : "color-mix(in srgb, var(--color-zinc-500) 20%, transparent)",
            transition: "background 150ms ease",
            cursor: "pointer",
            border: "none",
            padding: 0,
          }}
        />
      ))}
    </div>
  );
}
