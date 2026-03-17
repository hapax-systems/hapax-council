import { useHealthHistory } from "../../api/hooks";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

export function HealthHistoryChart() {
  const { data } = useHealthHistory(7);

  if (!data?.entries?.length) return null;

  const chartData = data.entries.map((e) => ({
    time: new Date(e.timestamp).toLocaleDateString("en", { weekday: "short", hour: "numeric" }),
    healthy: e.healthy,
    degraded: e.degraded,
    failed: e.failed,
  }));

  return (
    <div className="h-24 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
          <XAxis dataKey="time" tick={{ fontSize: 8, fill: "#928374" }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 8, fill: "#928374" }} width={25} />
          <Tooltip
            contentStyle={{ backgroundColor: "#3c3836", border: "1px solid #504945", fontSize: 10, color: "#ebdbb2" }}
            labelStyle={{ color: "#bdae93" }}
          />
          <Area type="monotone" dataKey="healthy" stackId="1" stroke="#b8bb26" fill="#b8bb26" fillOpacity={0.3} />
          <Area type="monotone" dataKey="degraded" stackId="1" stroke="#fabd2f" fill="#fabd2f" fillOpacity={0.3} />
          <Area type="monotone" dataKey="failed" stackId="1" stroke="#fb4934" fill="#fb4934" fillOpacity={0.3} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
