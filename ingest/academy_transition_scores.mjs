/** Local-only impact replay, using unchanged v0.4.0 and actual exposure computation. */
import {readFileSync, writeFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import process from 'node:process';
import console from 'node:console';
import {score} from '../.local/scoring-build/lib/scoring/score.js';
import {academyV0} from '../.local/scoring-build/lib/scoring/presets.js';
import {computeVisibility} from '../.local/scoring-build/lib/visibility/compute.js';
const [directory, ...labels] = process.argv.slice(2);
if (!directory || !labels.length) throw new Error('Expected local directory and stage labels');
const output = {};
for (const label of labels) {
  const cases = JSON.parse(gunzipSync(readFileSync(`${directory}/${label}-inputs.json.gz`)));
  output[label] = cases.map(c => {
    const exposure = computeVisibility(c.scene);
    const result = score(c.primary,c.school,c.scene.buildings,exposure,c.candidate,
      academyV0,c.reference,c.context);
    return {key:c.key,result,visible_ratio:exposure.visible_ratio,snapshot:c.reference.snapshot};
  });
}
writeFileSync(`${directory}/scores.json`,JSON.stringify(output,null,2)+'\n');
for (const [label,cases] of Object.entries(output)) for (const c of cases)
  console.log(label,c.key,c.result.total,c.result.confidence.value,
    c.result.axes.map(a=>`${a.key}=${a.normalized}`).join(' '));
