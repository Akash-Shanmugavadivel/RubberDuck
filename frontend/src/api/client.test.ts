import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, getToken, setToken } from "./client";

describe("API client", () => {
  beforeEach(() => { sessionStorage.clear(); vi.stubGlobal("fetch", vi.fn()); });
  afterEach(() => vi.unstubAllGlobals());

  it("stores and clears a session token", () => {
    setToken("abc");
    expect(getToken()).toBe("abc");
    setToken(null);
    expect(getToken()).toBeNull();
  });

  it("adds the bearer token to authenticated requests", async () => {
    setToken("classroom-token");
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } }));
    await api.documents();
    const [, options] = vi.mocked(fetch).mock.calls[0];
    expect(new Headers(options?.headers).get("Authorization")).toBe("Bearer classroom-token");
  });

  it("does not authenticate public health requests", async () => {
    setToken("classroom-token");
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ status: "ok", service: "pydebugger-api" }), { status: 200 }));
    await api.health();
    const [, options] = vi.mocked(fetch).mock.calls[0];
    expect(new Headers(options?.headers).has("Authorization")).toBe(false);
  });

  it("surfaces API detail and removes an expired token", async () => {
    setToken("expired");
    const expired = vi.fn();
    window.addEventListener("rubberduck:unauthorized", expired, { once: true });
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ detail: "Session expired" }), { status: 401, headers: { "Content-Type": "application/json" } }));
    await expect(api.me()).rejects.toEqual(expect.objectContaining({ status: 401, message: "Session expired" }));
    expect(getToken()).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
  });
});
