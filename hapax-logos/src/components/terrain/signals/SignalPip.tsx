import { CATEGORY_HEX, type SignalCategory } from "../../../contexts/ClassificationOverlayContext";

interface SignalPipProps {
  category: SignalCategory;
  severity: number;
  title: string;
  detail?: string;
  freshness?: number; // 0.0 (stale) to 1.0 (fresh)
}

function breatheClass(severity: number): string | undefined {
  if (severity < 0.2) return undefined;
  if (severity < 0.4) return "signal-breathe-slow";
  if (severity < 0.7) return "signal-breathe-mod";
  if (severity < 0.85) return "signal-breathe-fast";
  return "signal-breathe-crit";
}

function breatheDuration(severity: number): string | undefined {
  if (severity < 0.2) return undefined;
  if (severity < 0.4) return "8s";
  if (severity < 0.7) return "4s";
  if (severity < 0.85) return "1.5s";
  return "0.6s";
}

function pipSize(severity: number): number {
  if (severity < 0.4) return 6;
  if (severity < 0.7) return 7;
  if (severity < 0.85) return 8;
  return 10;
}

export function SignalPip({ category, severity, title, detail, freshness = 1.0 }: SignalPipProps) {
  const color = CATEGORY_HEX[category] ?? "#bdae93";
  const size = pipSize(severity);
  const anim = breatheClass(severity);
  const dur = breatheDuration(severity);
  const opacity = Math.max(0.3, freshness);

  return (
    <div
      className="inline-block rounded-full"
      title={detail ? `${title}\n${detail}` : title}
      style={{
        width: size,
        height: size,
        backgroundColor: color,
        opacity,
        animation: anim ? `${anim} ${dur} ease-in-out infinite` : undefined,
      }}
    />
  );
}
