import { useQuery } from "@tanstack/react-query";
import { Activity, AlertCircle, Clock3, Coins, LoaderCircle, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { EmptyState, PageHeader } from "../components/AppShell";

export function MonitoringPage() {
  const summary = useQuery({ queryKey: ["monitoring"], queryFn: () => api.monitoring(), refetchInterval: 30_000 });
  const data = summary.data;
  return <div className="page"><PageHeader eyebrow="OPERATIONS" title="System health and usage." description="Inspect backend workload, failures, latency, model tokens, and configured cost estimates." action={<button className="secondary" onClick={() => summary.refetch()}><RefreshCw size={17}/>Refresh</button>}/>
    {summary.isLoading ? <div className="loading-row"><LoaderCircle className="spin"/>Loading operational data…</div> : summary.isError ? <div className="notice error">Monitoring data could not be loaded.</div> : <><section className="metric-grid"><MetricCard icon={<Activity/>} label="Total calls" value={String(data?.total_calls ?? 0)}/><MetricCard icon={<AlertCircle/>} label="Failures" value={String(data?.total_failures ?? 0)}/><MetricCard icon={<Coins/>} label="Estimated cost" value={`$${(data?.total_cost_usd ?? 0).toFixed(4)}`}/><MetricCard icon={<Clock3/>} label="Window" value="Last 24h"/></section>{data?.warning && <div className="notice warning">{data.warning}</div>}<section className="panel table-panel"><div className="panel-title"><div><h2>Operations</h2><p>Requests recorded by backend instrumentation.</p></div></div>{data?.operations.length ? <div className="table-scroll"><table><thead><tr><th>Operation</th><th>Calls</th><th>Failures</th><th>Avg latency</th><th>P95</th><th>Tokens</th><th>Cost</th></tr></thead><tbody>{data.operations.map(metric => <tr key={metric.operation}><td><strong>{metric.operation}</strong></td><td>{metric.calls}</td><td><span className={metric.failures ? "bad" : "ok"}>{metric.failures} ({(metric.failure_rate * 100).toFixed(1)}%)</span></td><td>{metric.average_latency_ms.toFixed(1)} ms</td><td>{metric.p95_latency_ms.toFixed(1)} ms</td><td>{(metric.input_tokens + metric.output_tokens + metric.embedding_tokens).toLocaleString()}</td><td>${metric.cost_usd.toFixed(4)}</td></tr>)}</tbody></table></div> : <EmptyState icon={<Activity/>} title="No activity recorded">Use the tutor, ingestion, or execution APIs to populate operational metrics.</EmptyState>}</section></>}
  </div>;
}

function MetricCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) { return <article className="metric-card"><div>{icon}</div><span>{label}</span><strong>{value}</strong></article>; }
