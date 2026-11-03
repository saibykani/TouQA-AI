/** Thin fetch wrapper: cookie session, CSRF double-submit, typed errors. */
const BASE = `${(import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "")}/api/v1`;

export class ApiError extends Error {
  constructor(public status: number, message: string, public code?: string, public detail?: unknown) {
    super(message);
  }
}

let csrfToken: string | null = null;
export function setCsrfToken(t: string | null | undefined) {
  csrfToken = t ?? null;
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (method !== "GET") {
    const token = csrfToken ?? readCookie("touqa_csrf");
    if (token) headers["X-CSRF-Token"] = token;
  }
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : isForm ? (body as FormData) : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the TouQA backend. Check that it is running.");
  }
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized?.();
  const text = await res.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const err = data?.error;
    let message: string =
      err?.message ?? (typeof data?.detail === "string" ? data.detail : null) ?? `Request failed (${res.status})`;
    if (Array.isArray(data?.detail)) message = data.detail.map((d: any) => d.msg).join("; ");
    throw new ApiError(res.status, message, err?.code, err?.detail);
  }
  return data as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  patch: <T>(p: string, b?: unknown) => request<T>("PATCH", p, b ?? {}),
  del: <T>(p: string) => request<T>("DELETE", p),
  upload: <T>(p: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", p, fd);
  },
  url: (p: string) => `${BASE}${p}`,
};

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
