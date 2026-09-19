import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "vitest";

test("키 없이 로컬 Parquet를 저장하고 DuckDB로 집계한다", () => {
  const directory = mkdtempSync(join(tmpdir(), "gilmok-smoke-"));
  try {
    const stdout = execFileSync("uv", [
      "run", "--frozen", "python", "-m", "ingest.smoke", "--local-root", directory,
    ], { encoding: "utf8" });
    const result = JSON.parse(stdout);
    expect(result.storage).toBe("local");
    expect(existsSync(join(directory, "raw/sample/2026-01.parquet"))).toBe(true);
    expect(result.rows).toEqual([
      { code: "001", observed_count: 2, total: 30 },
      { code: "002", observed_count: 0, total: null },
    ]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}, 30_000);
