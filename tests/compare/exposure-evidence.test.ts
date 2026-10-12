import * as React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {it,expect,vi} from 'vitest';
import {ExposureEvidence} from '../../components/compare/ExposureEvidence';
import type {ComparisonCandidate} from '../../lib/compare/store';
import {score} from '../../lib/scoring/score';
import {academyV0} from '../../lib/scoring/presets';
import {computeVisibility} from '../../lib/visibility/compute';
import {scene} from '../visibility/fixtures';
import {candidate,inputs,reference,context} from '../scoring/fixtures';
vi.stubGlobal('React',React);
function render(floor:number,pending=false,covered=true){
 const c={...candidate,floor},primary=inputs(),school=inputs(1000);primary.meta.floor=floor;school.meta.floor=floor;primary.building!.elevators.passenger=null;if(pending)primary.meta.building_lookup.status='pending';
 const sc={...scene(),floor};sc.coverage.score_ring_within_loaded_region=covered;const exposure=computeVisibility(sc);
 const result=score(primary,school,[],exposure,c,academyV0,reference(),context);
 const row={candidate:c,result,inputs:{scene:sc,exposure}} as ComparisonCandidate;
 return renderToStaticMarkup(React.createElement(ExposureEvidence,{row}));
}
it('describes unknown elevator penalty only on high floors, pending hold and basement model',()=>{
 expect(render(3)).toContain('신뢰도 −5 (0대로 간주하지 않음)');
 expect(render(1)).not.toContain('신뢰도 −5 (0대로 간주하지 않음)');
 expect(render(2)).not.toContain('신뢰도 −5 (0대로 간주하지 않음)');
 expect(render(-1)).toContain('입구 간판 기준 노출');expect(render(-1)).toContain('건물 R7 −25 적용');
 const pending=render(-1,true);expect(pending).toContain('60점 유지·신뢰도 −15');expect(pending).not.toContain('건물 R7 −25 적용');
});
it('missing scenes do not imply zero visible points or fabricate geometry on mobile',()=>{
 const html=render(3,false,false);expect(html).toContain('미확인');expect(html).not.toContain('0/0');expect(html).toContain('시각화 자료 없음/계산 중');expect(html).toContain('샘플점 지도는 데스크톱에서 확인');expect(html).not.toContain('data-sample-evidence');
});
