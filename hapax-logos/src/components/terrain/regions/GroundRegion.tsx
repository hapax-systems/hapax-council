import { Region } from "../Region";

export function GroundRegion() {
  return (
    <Region name="ground">
      {(depth) => (
        <div className="h-full flex flex-col justify-center items-center">
          <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-600">ground</div>
          {depth !== "surface" && (
            <div className="text-xs text-zinc-500 mt-1">
              Ambient canvas, self-state, signals, studio
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
