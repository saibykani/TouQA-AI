import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import type { Page } from "@/lib/types";
import { qs } from "@/lib/utils";
import { Card, EmptyState, ErrorBox, Input, Loading, Pager, Table, Td, Th } from "./ui";

export interface Column<T> { header: string; cell: (row: T) => ReactNode; className?: string }

/** Searchable, paginated table over a project-scoped list endpoint; row click opens ?open=<id>. */
export default function RecordTable<T extends { id: number }>({ endpoint, projectId, columns, filters, extra, placeholder, empty }: {
  endpoint: string; projectId: number; columns: Column<T>[]; filters?: Record<string, unknown>; extra?: ReactNode;
  placeholder?: string; empty?: string;
}) {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  useEffect(() => { const t = setTimeout(() => setQ(search.trim()), 250); return () => clearTimeout(t); }, [search]);
  useEffect(() => setPage(1), [q, JSON.stringify(filters)]);

  const list = useQuery({
    queryKey: [endpoint, projectId, q, filters, page],
    queryFn: () => api.get<Page<T>>(`${endpoint}${qs({ project_id: projectId, q, page, page_size: 50, ...filters })}`),
    placeholderData: keepPreviousData,
  });

  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b p-3">
        <div className="relative w-full max-w-xs">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input className="pl-8" placeholder={placeholder ?? "Search…"} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        {extra}
      </div>
      {list.isLoading ? <Loading /> : list.error ? <ErrorBox error={list.error} className="m-3" /> : list.data?.items.length ? (
        <>
          <Table>
            <thead><tr>{columns.map((c) => <Th key={c.header} className={c.className}>{c.header}</Th>)}</tr></thead>
            <tbody>
              {list.data.items.map((row) => (
                <tr key={row.id} className="cursor-pointer hover:bg-muted/50" onClick={() => { params.set("open", String(row.id)); setParams(params); }}>
                  {columns.map((c) => <Td key={c.header} className={c.className}>{c.cell(row)}</Td>)}
                </tr>
              ))}
            </tbody>
          </Table>
          <Pager page={page} pageSize={50} total={list.data.total} onPage={setPage} />
        </>
      ) : <EmptyState title={empty ?? "Nothing found"} description="Adjust the filters or run a sync to import records." />}
    </Card>
  );
}

export function useOpenParam(): [number | null, () => void] {
  const [params, setParams] = useSearchParams();
  const v = params.get("open");
  return [v ? Number(v) : null, () => { params.delete("open"); setParams(params); }];
}
