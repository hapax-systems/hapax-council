import { Region } from "../Region";

export function WatershedRegion() {
  return (
    <Region name="watershed">
      {(depth) => (
        <div className="h-full flex flex-col justify-center px-4">
          <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-600">watershed</div>
          {depth !== "surface" && (
            <div className="text-xs text-zinc-500 mt-1">
              Flow topology, data flows, profile
            </div>
          )}
        </div>
      )}
    </Region>
  );
}
