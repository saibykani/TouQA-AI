import { useQuery } from "@tanstack/react-query";
import { Rocket } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { fmtDate } from "@/lib/utils";
import { Badge, Card, EmptyState, ErrorBox, Loading, PageHeader, StatusBadge, Table, Td, Th } from "@/components/ui";
import NoProject from "@/components/NoProject";

export default function Releases() {
  const { project } = useProject();
  const q = useQuery({ queryKey: ["releases", project?.id], queryFn: () => api.get<any[]>(`/releases?project_id=${project!.id}`), enabled: !!project });
  if (!project) return <NoProject />;
  return (
    <>
      <PageHeader title="Releases" description="Release and iteration hierarchy with linked requirements and detected incidents." />
      <Card>
        {q.isLoading ? <Loading /> : q.error ? <ErrorBox error={q.error} className="m-3" /> : q.data?.length ? (
          <Table>
            <thead><tr><Th>Version</Th><Th>Name</Th><Th>Type</Th><Th>Status</Th><Th>Dates</Th><Th className="text-right">Requirements</Th><Th className="text-right">Incidents</Th></tr></thead>
            <tbody>
              {q.data.map((r) => {
                const depth = Math.max(0, ((r.indent_level?.length ?? 3) / 3) - 1);
                return (
                  <tr key={r.id} className={r.active ? "" : "opacity-60"}>
                    <Td className="font-mono text-xs">{r.version}</Td>
                    <Td><span style={{ paddingLeft: depth * 16 }} className="inline-flex items-center gap-2">{r.name}{r.is_iteration && <Badge tone="blue">iteration</Badge>}{r.is_deleted_externally && <Badge tone="red">deleted</Badge>}</span></Td>
                    <Td>{r.type ?? "—"}</Td>
                    <Td><StatusBadge status={r.status} /></Td>
                    <Td className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(r.start_date, false)} → {fmtDate(r.end_date, false)}</Td>
                    <Td className="text-right tabular-nums">{r.requirements}</Td>
                    <Td className="text-right tabular-nums">{r.incidents_detected}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        ) : <EmptyState icon={<Rocket className="h-5 w-5" />} title="No releases imported" description="Run a sync including releases." />}
      </Card>
    </>
  );
}
