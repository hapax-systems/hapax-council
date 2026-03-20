import { lazy, Suspense } from "react";
import { useHealthHistory } from "../../api/hooks";

const RechartsChart = lazy(() => import("./HealthHistoryChartInner"));

export function HealthHistoryChart() {
  const { data } = useHealthHistory(7);

  if (!data?.entries?.length) return null;

  return (
    <Suspense fallback={<div className="h-24 w-full" />}>
      <RechartsChart entries={data.entries} />
    </Suspense>
  );
}
