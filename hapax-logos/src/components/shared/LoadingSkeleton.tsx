import { useState } from "react";

interface LoadingSkeletonProps {
  lines?: number;
  className?: string;
}

export function LoadingSkeleton({ lines = 3, className = "" }: LoadingSkeletonProps) {
  const [widths] = useState(() =>
    Array.from({ length: lines }, () => 70 + Math.random() * 30)
  );

  return (
    <div className={`animate-pulse space-y-2 ${className}`}>
      {widths.slice(0, lines).map((w, i) => (
        <div
          key={i}
          className="h-3 rounded bg-zinc-800"
          style={{ width: `${w}%` }}
        />
      ))}
    </div>
  );
}
