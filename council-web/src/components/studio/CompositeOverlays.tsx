import type { OverlayType } from "./compositePresets";

/** Render visual overlay effects as CSS-only layers. */
export function CompositeOverlay({ type }: { type: OverlayType }) {
  switch (type) {
    case "scanlines":
      return (
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,0,0,0.12) 2px, rgba(0,0,0,0.12) 4px)",
            mixBlendMode: "multiply" as const,
          }}
        />
      );
    case "rgbsplit":
      return <RGBSplitOverlay />;
    case "vignette":
      return (
        <div
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse at center, transparent 50%, rgba(0,0,0,0.7) 100%)",
          }}
        />
      );
    case "huecycle":
      return (
        <div
          className="pointer-events-none absolute inset-0 studio-huecycle"
          style={{
            background: "linear-gradient(135deg, #ff00cc44, #3300ff44, #00ffcc44)",
            mixBlendMode: "overlay" as const,
            opacity: 0.3,
          }}
        />
      );
    case "noise":
      return (
        <div
          className="pointer-events-none absolute inset-0 studio-noise"
          style={{
            backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E")`,
            backgroundSize: "128px 128px",
            opacity: 0.08,
            mixBlendMode: "overlay" as const,
          }}
        />
      );
    default:
      return null;
  }
}

/** RGB chromatic aberration — 2 offset color-shifted copies */
function RGBSplitOverlay() {
  return (
    <>
      <div
        className="pointer-events-none absolute inset-0 studio-rgbsplit-r"
        style={{
          background: "inherit",
          mixBlendMode: "screen" as const,
          opacity: 0.15,
          transform: "translate(3px, 0)",
          filter: "hue-rotate(-30deg) saturate(3)",
        }}
      />
      <div
        className="pointer-events-none absolute inset-0 studio-rgbsplit-b"
        style={{
          background: "inherit",
          mixBlendMode: "screen" as const,
          opacity: 0.15,
          transform: "translate(-3px, 0)",
          filter: "hue-rotate(180deg) saturate(3)",
        }}
      />
    </>
  );
}
