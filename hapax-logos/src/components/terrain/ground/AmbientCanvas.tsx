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
  speed: number;
}

export function AmbientCanvas({ ambientText, speed }: AmbientCanvasProps) {
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
      {/* Organic floating shapes */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div
          className="absolute rounded-full"
          style={{
            width: "40vw",
            height: "40vw",
            left: "10%",
            top: "20%",
            background: "radial-gradient(circle, rgba(120,45,10,0.08) 0%, transparent 70%)",
            animation: `drift1 ${25 + speed * 30}s ease-in-out infinite alternate`,
          }}
        />
        <div
          className="absolute rounded-full"
          style={{
            width: "30vw",
            height: "30vw",
            right: "5%",
            bottom: "10%",
            background: "radial-gradient(circle, rgba(160,70,15,0.06) 0%, transparent 70%)",
            animation: `drift2 ${30 + speed * 25}s ease-in-out infinite alternate`,
          }}
        />
        <div
          className="absolute rounded-full"
          style={{
            width: "50vw",
            height: "50vw",
            left: "40%",
            top: "-10%",
            background: "radial-gradient(circle, rgba(90,25,8,0.07) 0%, transparent 70%)",
            animation: `drift3 ${35 + speed * 20}s ease-in-out infinite alternate`,
          }}
        />
      </div>

      {/* Floating text fragment */}
      <div className="absolute inset-0 flex items-end justify-start p-8 pointer-events-none">
        <div className="relative h-12 overflow-hidden">
          <div
            key={fragment}
            className="text-white/8 text-xl font-light tracking-wider leading-relaxed"
            style={{ animation: "fragmentIn 3s ease-out forwards" }}
          >
            {fragment}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes drift1 {
          from { transform: translate(0, 0) scale(1); }
          to { transform: translate(5vw, 3vh) scale(1.1); }
        }
        @keyframes drift2 {
          from { transform: translate(0, 0) scale(1); }
          to { transform: translate(-4vw, -5vh) scale(0.9); }
        }
        @keyframes drift3 {
          from { transform: translate(0, 0) scale(1); }
          to { transform: translate(3vw, 4vh) scale(1.05); }
        }
        @keyframes fragmentIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 0.08; transform: translateY(0); }
        }
      `}</style>
    </>
  );
}
