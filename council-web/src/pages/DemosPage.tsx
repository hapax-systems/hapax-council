import { DemoList } from "../components/demos/DemoList";

export function DemosPage() {
  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
      <h1 className="text-lg font-semibold text-zinc-100">Demos</h1>
      <DemoList />
    </div>
  );
}
