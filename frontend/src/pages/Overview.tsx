import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Bug, FileText, FlaskConical, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { humanize, qs, timeAgo } from "@/lib/utils";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, Loading, Notice, PageHeader, Select, Stat, StatusBadge } from "@/components/ui";
import NoProject from "@/components/NoProject";

const PALETTE = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#64748b"];

const tooltipStyle = {
  contentStyle: { background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: 6, fontSize: 12 },
  labelStyle: { color: "hsl(var(--muted-foreground))" },
};

export default function Overview() {
  const { project } = useProject();
  const [days, setDays] = useState(30);
  const q = useQuery({
    queryKey: ["dashboard", project?.id, days],
    queryFn: () => api.get<any>(`/dashboard${qs({ project_id: project?.id, days })}`),
    enabled: !!project,
  });
  if (!project) return <NoProject />;
  const d = q.data;
  // Only plot series that have at least one non-zero day.
  const trendKeys: string[] = d?.trend?.length
    ? Object.keys(d.trend[0]).filter((k) => k !== "date" && d.trend.some((p: any) => p[k] > 0))
    : [];

  return (
    <>
      <PageHeader
        title="Overview"
        description={<>Quality snapshot for <b>{project.name}</b> · last synced {timeAgo(project.last_synced_at)}</>}
        actions={
          <Select className="h-8 w-36 text-xs" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90, 180].map((n) => <option key={n} value={n}>Last {n} days</option>)}
          </Select>
        }
      />
      {q.isLoading && <Loading />}
      <ErrorBox error={q.error} />
      {d && (
        <div className="space-y-5">
          {!project.last_synced_at && !project.is_demo && (
            <Notice tone="amber">This project has not been synchronised yet. <Link className="underline" to="/sync">Run a sync</Link> to import requirements, test cases and incidents.</Notice>
          )}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Requirements" value={d.counts.requirements} icon={<FileText className="h-4 w-4" />} />
            <Stat label="Test cases" value={d.counts.test_cases} icon={<FlaskConical className="h-4 w-4" />} />
            <Stat label="Open incidents" value={d.counts.open_incidents} hint={`${d.counts.incidents} total`} icon={<Bug className="h-4 w-4" />} />
            <Stat
              label="Requirement coverage"
              value={d.coverage.percent != null ? `${d.coverage.percent}%` : "—"}
              hint={`${d.coverage.covered}/${d.coverage.leaf_requirements} leaf requirements`}
            />
            <Stat label="AI test cases created" value={d.counts.test_cases_created} hint={`${d.counts.test_cases_generated} generated`} icon={<Sparkles className="h-4 w-4" />} />
            <Stat label="Pending review" value={d.counts.pending_drafts + d.counts.pending_incident_drafts}
              hint={d.counts.failed_jobs ? <span className="text-destructive">{d.counts.failed_jobs} failed jobs</span> : "drafts awaiting approval"} />
          </div>
          {d.coverage.note && <Notice tone="amber"><AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{d.coverage.note}</Notice>}

          <div className="grid gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader title="Activity trend" description={`AI generation and submissions over ${days} days`} />
              <CardBody className="h-64">
                {trendKeys.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={d.trend} margin={{ left: -20, right: 8, top: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                      <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={(v: string) => v.slice(5)} minTickGap={16} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip {...tooltipStyle} cursor={{ fill: "hsl(var(--muted))" }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      {trendKeys.map((k, i) => (
                        <Bar key={k} dataKey={k} name={humanize(k)} stackId="a" fill={PALETTE[i % PALETTE.length]} maxBarSize={18} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState title="No activity in this period" />}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Incidents by status" />
              <CardBody className="h-64">
                {d.incident_status?.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={d.incident_status} layout="vertical" margin={{ left: 10, right: 16 }}>
                      <XAxis type="number" allowDecimals={false} hide />
                      <YAxis type="category" dataKey="name" width={90} tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
                      <Tooltip {...tooltipStyle} cursor={{ fill: "hsl(var(--muted))" }} />
                      <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                        {d.incident_status.map((_: any, i: number) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : <EmptyState title="No incidents imported" />}
              </CardBody>
            </Card>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader title="Requirements by status" />
              <CardBody className="space-y-2">
                {d.requirement_status?.length ? d.requirement_status.map((s: any, i: number) => {
                  const max = Math.max(...d.requirement_status.map((x: any) => x.count));
                  return (
                    <div key={s.name} className="text-xs">
                      <div className="mb-0.5 flex justify-between"><span>{s.name}</span><span className="tabular-nums text-muted-foreground">{s.count}</span></div>
                      <div className="h-1.5 rounded-full bg-muted"><div className="h-full rounded-full" style={{ width: `${(100 * s.count) / max}%`, background: PALETTE[i % PALETTE.length] }} /></div>
                    </div>
                  );
                }) : <EmptyState title="No requirements imported" />}
              </CardBody>
            </Card>
            <Card className="lg:col-span-2">
              <CardHeader title="Recent activity" actions={<Link to="/audit" className="text-xs text-primary hover:underline">View audit log</Link>} />
              <ul className="divide-y">
                {d.recent_activity?.length ? d.recent_activity.map((a: any) => (
                  <li key={a.id} className="flex items-center gap-3 px-4 py-2 text-sm">
                    <StatusBadge status={a.outcome} />
                    <span className="min-w-0 flex-1 truncate">{a.summary}</span>
                    {a.platform && <Badge>{a.platform}</Badge>}
                    <span className="shrink-0 text-xs text-muted-foreground">{timeAgo(a.created_at)}</span>
                  </li>
                )) : <li><EmptyState title="Nothing yet" /></li>}
              </ul>
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
