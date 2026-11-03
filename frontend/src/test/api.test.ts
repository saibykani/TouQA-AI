import { api, ApiError, setCsrfToken } from "@/lib/api";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockImplementation(async () => new Response(body === undefined ? "" : JSON.stringify(body), { status }));
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

describe("api client", () => {
  it("sends the CSRF token on writes but not on reads", async () => {
    setCsrfToken("tok123");
    const fn = mockFetch(200, { ok: true });
    await api.get("/x");
    expect(fn.mock.calls[0][1].headers["X-CSRF-Token"]).toBeUndefined();
    await api.post("/x", { a: 1 });
    const init = fn.mock.calls[1][1];
    expect(init.headers["X-CSRF-Token"]).toBe("tok123");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(init.body)).toEqual({ a: 1 });
  });

  it("surfaces the backend error envelope message", async () => {
    mockFetch(409, { error: { code: "conflict", message: "The drafts changed since you reviewed the preview." } });
    await expect(api.post("/submissions/test-cases", {})).rejects.toMatchObject({
      status: 409, code: "conflict", message: "The drafts changed since you reviewed the preview.",
    });
  });

  it("flattens FastAPI validation errors", async () => {
    mockFetch(422, { detail: [{ msg: "field required" }, { msg: "too long" }] });
    await expect(api.put("/x", {})).rejects.toThrow("field required; too long");
  });

  it("reports an unreachable backend clearly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err: any = await api.get("/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(0);
  });
});
