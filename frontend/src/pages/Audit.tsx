import { Fragment, useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, Search } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import { fmtDate, qs } from "@/lib/utils";
import { Badge, Card, EmptyState, ErrorBox, Input, Loading, PageHeader, Pager, Select, StatusBadge, Table, Td, Th } from "@/components/ui";

const CATEGORIES = ["auth", "config", "import", "ai", "draft", "submission", "incident", "folder"];

export default function Audit() {
  const { project } = useProject();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [f, setF] = useState({ category: "", outcome: "", platform: "" });
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<number | null>(null);
  useEffect(() => { const t = setTimeout(() => setQ(search), 250); return () => clearTimeout(t); }, [search]);
  useEffect(() => setPage(1), [q, f]);

  const list = useQuery({
    queryKey: ["audit", project?.id, q, f, page],
    queryFn: () => api.get<any>(`/audit${qs({ project_id: project?.id, q, ...f, page, page_size: 50 })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <>
      <PageHeader title="Audit Log" description="Every sign-in, configuration change, AI run, approval and external write. Secrets are never recorded." />
      <Card>
        <div className="flex flex-wrap gap-2 border-b p-3">
          <div className="relative w-full max-w-xs">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="pl-8" placeholder="Search summary or action" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <Select className="w-36" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}><option value="">All categories</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</Select>
          <Select className="w-32" value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })}><option value="">All outcomes</option>{["success", "failure", "partial", "unknown"].map((c) => <option key={c}>{c}</option>)}</Select>
          <Select className="w-32" value={f.platform} onChange={(e) => setF({ ...f, platform: e.target.value })}><option value="">All platforms</option>{["spira", "jira", "ai"].map((c) => <option key={c}>{c}</option>)}</Select>
        </div>
        {list.isLoading ? <Loading /> : list.error ? <ErrorBox error={list.error} className="m-3" /> : list.data?.items.length ? (
          <>
            <Table>
              <thead><tr><Th>Time</Th><Th>Outcome</Th><Th>Category</Th><Th>Summary</Th><Th>User</Th></tr></thead>
              <tbody>
                {list.data.items.map((a: any) => (
                  <Fragment key={a.id}>
                    <tr className="cursor-pointer hover:bg-muted/50" onClick={() => setOpen(open === a.id ? null : a.id)}>
                      <Td className="whitespace-nowrap text-xs text-muted-foreground">{fmtDate(a.created_at)}</Td>
                      <Td><StatusBadge status={a.outcome} /></Td>
                      <Td><span className="text-xs">{a.category}</span>{a.platform && <Badge className="ml-1">{a.platform}</Badge>}</Td>
                      <Td>{a.summary}{a.is_demo && <Badge tone="violet" className="ml-1">demo</Badge>}</Td>
                      <Td className="text-xs text-muted-foreground">{a.user ?? "system"}</Td>
                    </tr>
                    {open === a.id && (
                      <tr><td colSpan={5} className="border-b bg-muted/30 px-3 py-2">
                        <div className="mb-1 font-mono text-xs text-muted-foreground">{a.action}{a.entity_type ? ` · ${a.entity_type} #${a.entity_id}` : ""}</div>
                        <pre className="max-h-64 overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(a.details ?? {}, null, 2)}</pre>
                      </td></tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </Table>
            <Pager page={page} pageSize={50} total={list.data.total} onPage={setPage} />
          </>
        ) : <EmptyState icon={<Activity className="h-5 w-5" />} title="No audit entries" />}
      </Card>
    </>
  );
}
