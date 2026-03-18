import { Region } from "../Region";

export function FieldRegion() {
  return (
    <Region name="field">
      {(depth) => (
        <div className="h-full flex flex-col justify-center px-4">
          <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-600">field</div>
          {depth !== "surface" && (
            <div className="text-xs text-zinc-500 mt-1">
              Perception, agents, drift
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
