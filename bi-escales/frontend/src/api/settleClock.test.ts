import { afterEach, describe, expect, it, vi } from "vitest";
import { settleClock } from "./escales";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("settleClock", () => {
  it("posts /clock/settle with the treasurer key and refuses an empty key", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ settled: [] }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(settleClock("  ")).rejects.toThrow(/treasurer key required/);
    expect(fetchMock).not.toHaveBeenCalled();

    await settleClock(" secret-admin ");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [path, init] = fetchMock.mock.calls[0];
    expect(String(path)).toContain("/api/escales/clock/settle");
    expect(init.method).toBe("POST");
    expect(init.headers["x-admin-key"]).toBe("secret-admin");
  });
});
