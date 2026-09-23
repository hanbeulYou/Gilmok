/** Local file bridge. No database, API, personal candidate, or percentile calculation. */
import { createReadStream, createWriteStream, writeFileSync } from "node:fs";
import { once } from "node:events";
import { createInterface } from "node:readline";
import { academyV0 } from "../lib/scoring/presets.ts";
import { extractReferenceRaw, parseReferenceInputs, referenceKeys } from "../lib/scoring/raw.ts";

async function main(): Promise<void> {
  const [inputPath, outputPath, metadataPath] = process.argv.slice(2);
  if (!inputPath || !outputPath || !metadataPath) throw new Error("Expected input/output/metadata paths");
  writeFileSync(metadataPath, JSON.stringify({ preset: academyV0, keys: referenceKeys }));
  const output = createWriteStream(outputPath, { flags: "wx" });
  const finished = once(output, "finish");
  const lines = createInterface({ input: createReadStream(inputPath), crlfDelay: Infinity });
  for await (const line of lines) {
    const row = JSON.parse(line) as Record<string, unknown>;
    if (typeof row.cell_id !== "string" || row.cell_id.length === 0 || typeof row.inside_seoul !== "boolean")
      throw new Error("Invalid reference cell envelope");
    const primary = parseReferenceInputs(row.primary), school = parseReferenceInputs(row.school);
    const values = extractReferenceRaw(primary, school, { inside_seoul: row.inside_seoul });
    const chunk = referenceKeys.map(axis_key => JSON.stringify({
      cell_id: row.cell_id, radius_m: primary.meta.radius_m, axis_key,
      raw_value: values[axis_key].value, notes: values[axis_key].notes,
    }) + "\n").join("");
    if (!output.write(chunk)) await once(output, "drain");
  }
  output.end();
  await finished;
}
main().catch(() => { process.stderr.write("Reference raw extraction failed; no snapshot promoted\n"); process.exitCode = 1; });
