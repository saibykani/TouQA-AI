import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronRight, ExternalLink, FileText, ListTree, Rows3, Search, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { useProject } from "@/lib/project";
import type { Page, RequirementDetail, RequirementRow } from "@/lib/types";
import { cn, fmtDate, qs } from "@/lib/utils";
import {
  Badge, Button, Card, CardBody, CardHeader, EmptyState, ErrorBox, Input, KV, Loading, PageHeader, Pager, Select, StatusBadge, Tabs,
} from "@/components/ui";
import NoProject from "@/components/NoProject";

interface TreeNode { id: number; external_id: string; name: string; is_summary: boolean; status: string | null; children: TreeNode[] }

function useDebounced<T>(v: T, ms = 250) {
  const [d, setD] = useState(v);
  useEffect(() => {
    const t = setTimeout(() => setD(v), ms);
    return () => clearTimeout(t);
  }, [v, ms]);
  return d;
}

function CoverageBar({ c }: { c: RequirementRow["coverage"] }) {
  const total = c?.total ?? 0;
  if (!total) return <span className="text-xs text-muted-foreground">No tests</span>;
  const seg = (n: number | null | undefined, color: string) =>
    n ? <div style={{ width: `${(100 * n) / total}%` }} className={color} /> : null;
  const notRun = total - (c?.passed ?? 0) - (c?.failed ?? 0) - (c?.caution ?? 0) - (c?.blocked ?? 0);
  return (
    <div className="flex items-center gap-2" title={`${total} tests: ${c?.passed ?? 0} passed, ${c?.failed ?? 0} failed`}>
      <div className="flex h-1.5 w-16 overflow-hidden rounded-full bg-muted">
        {seg(c?.passed, "bg-emerald-500")}{seg(c?.failed, "bg-red-500")}{seg(c?.caution, "bg-amber-500")}{seg(c?.blocked, "bg-slate-500")}
        {seg(notRun, "bg-muted-foreground/30")}
      </div>
      <span className="text-xs tabular-nums text-muted-foreground">{total}</span>
    </div>
  );
}

function Tree({ nodes, selected, onSelect, depth = 0 }: { nodes: TreeNode[]; selected?: number; onSelect: (id: number) => void; depth?: number }) {
  const [open, setOpen] = useState<Record<number, boolean>>({});
  return (
    <ul>
      {nodes.map((n) => {
        const isOpen = open[n.id] ?? depth < 1;
        return (
          <li key={n.id}>
            <div
              className={cn("flex cursor-pointer items-center gap-1 rounded px-1 py-1 text-sm hover:bg-muted", selected === n.id && "bg-accent text-accent-foreground")}
              style={{ paddingLeft: depth * 14 + 4 }}
              onClick={() => onSelect(n.id)}
            >
              {n.children.length ? (
                <button onClick={(e) => { e.stopPropagation(); setOpen((o) => ({ ...o, [n.id]: !isOpen })); }} className="rounded p-0.5 hover:bg-background" aria-label="Toggle">
                  <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", isOpen && "rotate-90")} />
                </button>
              ) : <span className="w-4" />}
              <span className="shrink-0 font-mono text-[11px] text-muted-foreground">RQ:{n.external_id}</span>
              <span className={cn("truncate", n.is_summary && "font-medium")}>{n.name}</span>
            </div>
            {isOpen && n.children.length > 0 && <Tree nodes={n.children} selected={selected} onSelect={onSelect} depth={depth + 1} />}
          </li>
        );
      })}
    </ul>
  );
}

export function RequirementPanel({ id }: { id: number }) {
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["requirement", id], queryFn: () => api.get<RequirementDetail>(`/requirements/${id}`) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} className="m-4" />;
  const r = q.data!;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={<span><span className="mr-2 font-mono text-xs text-muted-foreground">RQ:{r.external_id}</span>{r.name}</span>}
          description={r.parent ? <>Parent: <Link className="hover:underline" to={`/requirements/${r.parent.id}`}>RQ:{r.parent.external_id} {r.parent.name}</Link></> : undefined}
          actions={
            <>
              {r.url && <a href={r.url} target="_blank" rel="noreferrer"><Button size="sm" variant="outline"><ExternalLink className="h-3.5 w-3.5" />Spira</Button></a>}
              {!r.is_summary && <Button size="sm" onClick={() => navigate(`/designer?requirement=${r.id}`)}><Sparkles className="h-3.5 w-3.5" />Design tests</Button>}
            </>
          }
        />
        <CardBody className="grid gap-5 md:grid-cols-[1fr_240px]">
          <div className="min-w-0">
            <div className="mb-1 text-xs font-medium text-muted-foreground">Description</div>
            {r.description_text ? <p className="whitespace-pre-wrap text-sm leading-relaxed">{r.description_text}</p>
              : <p className="text-sm italic text-muted-foreground">No description in Spira.</p>}
            {r.steps?.length > 0 && (
              <>
                <div className="mb-1 mt-4 text-xs font-medium text-muted-foreground">Requirement steps</div>
                <ol className="list-decimal space-y-1 pl-5 text-sm">{r.steps.map((s) => <li key={s.position}>{s.description}</li>)}</ol>
              </>
            )}
            {r.custom_properties?.length > 0 && (
              <>
                <div className="mb-1 mt-4 text-xs font-medium text-muted-foreground">Custom fields</div>
                <div className="divide-y rounded-md border px-3">
                  {r.custom_properties.map((c) => <KV key={c.name} label={c.name}>{String(c.value ?? "—")}</KV>)}
                </div>
              </>
            )}
          </div>
          <div className="space-y-0.5 text-sm">
            <KV label="Status"><StatusBadge status={r.status} /></KV>
            <KV label="Type">{r.type}</KV>
            <KV label="Importance">{r.importance}</KV>
            <KV label="Release">{r.release}</KV>
            <KV label="Owner">{r.owner}</KV>
            <KV label="Author">{r.author}</KV>
            <KV label="Updated">{fmtDate(r.updated_at)}</KV>
            <KV label="Synced">{fmtDate(r.synced_at)}</KV>
            <KV label="Coverage"><CoverageBar c={r.coverage} /></KV>
          </div>
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={`Linked test cases (${r.linked_test_cases.length})`} />
          {r.linked_test_cases.length ? (
            <ul className="divide-y">
              {r.linked_test_cases.map((t) => (
                <li key={t.id} className="flex items-center gap-2 px-4 py-2 text-sm">
                  <span className="font-mono text-[11px] text-muted-foreground">TC:{t.external_id}</span>
                  <Link to={`/test-cases?open=${t.id}`} className="min-w-0 flex-1 truncate hover:underline">{t.name}</Link>
                  <StatusBadge status={t.execution_status} />
                </li>
              ))}
            </ul>
          ) : <EmptyState title="No linked test cases" description="Use the AI Test Designer to draft coverage." />}
          {r.unresolved_test_case_links.length > 0 && (
            <p className="border-t px-4 py-2 text-xs text-muted-foreground">Not yet imported: {r.unresolved_test_case_links.map((x) => `TC:${x}`).join(", ")}</p>
          )}
        </Card>
        <Card>
          <CardHeader title="AI analyses" />
          {r.analyses.length ? (
            <ul className="divide-y">
              {r.analyses.map((a) => (
                <li key={a.id} className="flex items-center gap-2 px-4 py-2 text-sm">
                  <StatusBadge status={a.status} />
                  <span className="flex-1 truncate text-muted-foreground">{a.provider} · {a.model}</span>
                  {a.is_simulated && <Badge tone="violet">simulated</Badge>}
                  <span className="text-xs text-muted-foreground">{fmtDate(a.created_at)}</span>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="Not analysed yet" />}
        </Card>
      </div>

      {r.children.length > 0 && (
        <Card>
          <CardHeader title={`Child requirements (${r.children.length})`} />
          <ul className="divide-y">
            {r.children.map((c) => (
              <li key={c.id} className="flex items-center gap-2 px-4 py-2 text-sm">
                <span className="font-mono text-[11px] text-muted-foreground">RQ:{c.external_id}</span>
                <Link to={`/requirements/${c.id}`} className="min-w-0 flex-1 truncate hover:underline">{c.name}</Link>
                <StatusBadge status={c.status} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

export default function Requirements() {
  const { project } = useProject();
  const { id } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<"list" | "tree">("list");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ status: "", release: "", importance: "", owner: "" });
  const [page, setPage] = useState(1);
  const q = useDebounced(search);
  const pid = project?.id;

  const facets = useQuery({ queryKey: ["req-facets", pid], queryFn: () => api.get<any>(`/requirements/facets?project_id=${pid}`), enabled: !!pid });
  const list = useQuery({
    queryKey: ["requirements", pid, q, filters, page],
    queryFn: () => api.get<Page<RequirementRow>>(`/requirements${qs({ project_id: pid, q, ...filters, page, page_size: 50 })}`),
    enabled: !!pid && view === "list",
    placeholderData: keepPreviousData,
  });
  const tree = useQuery({ queryKey: ["req-tree", pid], queryFn: () => api.get<TreeNode[]>(`/requirements/tree?project_id=${pid}`), enabled: !!pid && view === "tree" });

  useEffect(() => setPage(1), [q, filters]);
  if (!project) return <NoProject />;
  const selected = id ? Number(id) : undefined;
  const select = (rid: number) => navigate(`/requirements/${rid}`);
  const f = facets.data;

  return (
    <>
      <PageHeader title="Requirements" description="Imported from Spira. Select a requirement to review it or design tests." />
      <div className="grid gap-4 xl:grid-cols-[minmax(380px,460px)_1fr]">
        <Card className="flex max-h-[calc(100vh-170px)] flex-col">
          <div className="space-y-2 border-b p-3">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input className="pl-8" placeholder="Search name, text or RQ:id" value={search} onChange={(e) => setSearch(e.target.value)} />
              </div>
              <Tabs value={view} onChange={setView} tabs={[{ value: "list", label: <Rows3 className="h-4 w-4" /> }, { value: "tree", label: <ListTree className="h-4 w-4" /> }]} />
            </div>
            {view === "list" && (
              <div className="grid grid-cols-2 gap-2">
                <Select className="h-8 text-xs" value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
                  <option value="">All statuses</option>{f?.statuses.map((s: string) => <option key={s}>{s}</option>)}
                </Select>
                <Select className="h-8 text-xs" value={filters.release} onChange={(e) => setFilters({ ...filters, release: e.target.value })}>
                  <option value="">All releases</option>{f?.releases.map((r: any) => <option key={r.external_id} value={r.external_id}>{r.version ?? r.name}</option>)}
                </Select>
                <Select className="h-8 text-xs" value={filters.importance} onChange={(e) => setFilters({ ...filters, importance: e.target.value })}>
                  <option value="">All importance</option>{f?.importances.map((s: string) => <option key={s}>{s}</option>)}
                </Select>
                <Select className="h-8 text-xs" value={filters.owner} onChange={(e) => setFilters({ ...filters, owner: e.target.value })}>
                  <option value="">All owners</option>{f?.owners.map((s: string) => <option key={s}>{s}</option>)}
                </Select>
              </div>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-1">
            {view === "tree" ? (
              tree.isLoading ? <Loading /> : tree.data?.length ? <Tree nodes={tree.data} selected={selected} onSelect={select} />
                : <EmptyState icon={<FileText className="h-5 w-5" />} title="No requirements" description="Run a sync to import requirements." />
            ) : list.isLoading ? <Loading /> : list.error ? <ErrorBox error={list.error} className="m-2" /> : list.data?.items.length ? (
              list.data.items.map((r) => (
                <button
                  key={r.id}
                  onClick={() => select(r.id)}
                  className={cn("flex w-full items-start gap-2 rounded-md px-2 py-2 text-left hover:bg-muted", selected === r.id && "bg-accent text-accent-foreground")}
                >
                  <span className="mt-0.5 w-14 shrink-0 font-mono text-[11px] text-muted-foreground">RQ:{r.external_id}</span>
                  <span className="min-w-0 flex-1">
                    <span className={cn("block truncate text-sm", r.is_summary && "font-medium")}>{r.name}</span>
                    <span className="mt-1 flex flex-wrap items-center gap-1.5">
                      {r.status && <StatusBadge status={r.status} />}
                      {r.importance && <Badge>{r.importance}</Badge>}
                      {r.release && <Badge tone="blue">{r.release}</Badge>}
                      {r.is_deleted_externally && <Badge tone="red">deleted in Spira</Badge>}
                    </span>
                  </span>
                  {!r.is_summary && <CoverageBar c={r.coverage} />}
                </button>
              ))
            ) : <EmptyState icon={<FileText className="h-5 w-5" />} title="No matching requirements" />}
          </div>
          {view === "list" && list.data && <div className="border-t"><Pager page={page} pageSize={50} total={list.data.total} onPage={setPage} /></div>}
        </Card>
        <div className="min-w-0">
          {selected ? <RequirementPanel id={selected} /> : (
            <Card><EmptyState icon={<FileText className="h-6 w-6" />} title="Select a requirement" description="Its description, acceptance criteria, linked tests and AI analyses will appear here." /></Card>
          )}
        </div>
      </div>
    </>
  );
}
