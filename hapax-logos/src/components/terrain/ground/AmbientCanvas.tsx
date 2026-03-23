/**
 * AmbientCanvas — floating shapes + text fragments extracted from HapaxPage.
 * Lives in Ground region surface. The ambient visual layer that makes
 * the terrain feel alive.
 */

import { useEffect, useState } from "react";

const FRAGMENT_CYCLE_MS = 12000;

const FALLBACK_FRAGMENTS = [
  "externalized executive function",
  "consent must thread invariantly",
  "what layer does this touch?",
  "let the angular behaviors glimmer",
  "subsumption: lower layers work independently",
  "the periphery informs without overburdening",
  "data is dreamed, not displayed",
  "if a machine can learn, can it also dream?",
  "confusion is a pedagogical tool",
  "LLMs are perspective machines",
  "proportionate to who they are",
  "23 minutes to recover from interruption",
  "the right amount is the minimum needed",
  "voice is the most expensive channel",
  "fractal complexity D=1.3 to 1.5",
];

interface AmbientCanvasProps {
  ambientText: string;
  secondaryText: string;
  speed: number;
}

export function AmbientCanvas({ ambientText, secondaryText, speed }: AmbientCanvasProps) {
  const [fragmentIdx, setFragmentIdx] = useState(0);

  useEffect(() => {
    const id = setInterval(() => {
      setFragmentIdx((prev) => (prev + 1) % FALLBACK_FRAGMENTS.length);
    }, FRAGMENT_CYCLE_MS);
    return () => clearInterval(id);
  }, []);

  const fragment = ambientText || FALLBACK_FRAGMENTS[fragmentIdx];

  return (
    <>
      {/* Ambient visual layer handled by AmbientShader (z-0) — no CSS blobs needed */}

      {/* Floating text fragment */}
      <div className="absolute inset-0 flex items-end justify-start p-8 pointer-events-none">
        <div className="relative h-12 overflow-hidden">
          <div
            key={fragment}
            className="text-white/20 text-xl font-light tracking-wider leading-relaxed"
            style={{ animation: "fragmentIn 3s ease-out forwards" }}
          >
            {fragment}
          </div>
        </div>
      </div>

      {/* Secondary context line — below time display, top-left */}
      {secondaryText && (
        <div className="absolute top-14 left-4 pointer-events-none">
          <div
            key={secondaryText}
            className="text-white/20 text-[10px] tracking-widest"
            style={{ animation: "fragmentIn 3s ease-out forwards" }}
          >
            {secondaryText}
          </div>
        </div>
      )}

      <style>{`
        @keyframes fragmentIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </>
  );
}
