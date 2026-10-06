import { RuntimeHealth } from "./status";
import { checkService } from "./health-check";

export function startMonitor(
  targets: { service: string; url: string }[],
  onReport: (report: RuntimeHealth[]) => void,
  intervalMs = 30000,
) {
  const tick = async () => {
    const report = await Promise.all(targets.map((t) => checkService(t.service, t.url)));
    onReport(report);
  };
  tick();
  const timer = setInterval(tick, intervalMs);
  return () => clearInterval(timer);
}
