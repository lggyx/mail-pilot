import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../src/lib/api";

afterEach(() => vi.restoreAllMocks());

describe("api 客户端", () => {
  it("解包 {data} 信封", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { id: 1 } }), { status: 200 })));
    const data = await api<{ id: number }>("/api/anything");
    expect(data).toEqual({ id: 1 });
  });

  it("裸对象响应原样返回", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 })));
    expect(await api("/api/x")).toEqual({ ok: true });
  });

  it("FastAPI detail 错误转中文消息", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: "活动不存在" }), { status: 404 })));
    await expect(api("/api/x")).rejects.toMatchObject({ message: "活动不存在", status: 404 });
  });

  it("信封 error.message 错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "x", message: "限速中" } }), { status: 429 })),
    );
    await expect(api("/api/x")).rejects.toMatchObject({ message: "限速中", status: 429 });
  });

  it("401 跳登录", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const loc = { href: "" };
    vi.stubGlobal("window", { location: loc });
    await expect(api("/api/contacts")).rejects.toBeInstanceOf(ApiError);
    expect(loc.href).toBe("/login");
  });

  it("POST json 自动设置 Content-Type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/x", { method: "POST", json: { a: 1 } });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/x");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(init.body).toBe('{"a":1}');
  });
});
