import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "./api";
import type { Job } from "./types";

const ACTIVE = ["queued", "pending", "running"];
export const isTerminal = (s?: string) => !!s && !ACTIVE.includes(s.toLowerCase());

/** Polls a background job until it reaches a terminal state, then calls onDone once. */
export function useJob(jobId: number | null | undefined, onDone?: (job: Job) => void) {
  const qc = useQueryClient();
  const done = useRef<number | null>(null);
  const cb = useRef(onDone);
  cb.current = onDone;
  const q = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get<Job>(`/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : 1200),
  });
  useEffect(() => {
    const j = q.data;
    if (j && isTerminal(j.status) && done.current !== j.id) {
      done.current = j.id;
      qc.invalidateQueries({ queryKey: ["jobs"] });
      cb.current?.(j);
    }
  }, [q.data, qc]);
  return q.data ?? null;
}
