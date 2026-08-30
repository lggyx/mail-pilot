import { describe, expect, it } from "vitest";
import { fmtBytes, fmtPct, fmtTime } from "../src/lib/format";

describe("fmtTime", () => {
  it("空值显示 —", () => {
    expect(fmtTime(null)).toBe("—");
    expect(fmtTime(undefined)).toBe("—");
  });

  it("非法值原样返回", () => {
    expect(fmtTime("not-a-date")).toBe("not-a-date");
  });

  it("1 小时内显示相对时间", () => {
    const now = new Date();
    const tenMinAgo = new Date(now.getTime() - 10 * 60 * 1000);
    // 无时区后缀按 UTC 补 Z —— 本机 UTC+8，偏移后仍在 1 小时内
    const iso = tenMinAgo.toISOString().replace("Z", "");
    expect(fmtTime(iso)).toBe("10 分钟前");
  });

  it("超过 7 天显示绝对时间", () => {
    const d = new Date(Date.now() - 30 * 86400 * 1000);
    const pad = (n: number) => String(n).padStart(2, "0");
    const iso = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`;
    expect(fmtTime(iso)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  });
});

describe("fmtBytes / fmtPct", () => {
  it("字节单位换算", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(2048)).toBe("2.0 KB");
    expect(fmtBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("百分比空值", () => {
    expect(fmtPct(null)).toBe("—");
    expect(fmtPct(87.5)).toBe("87.5%");
  });
});
