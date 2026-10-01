import { labels } from '../../lib/scoring/axes';
import type { AxisKey } from '../../lib/scoring/types';
import { useComparisonStore } from '../../lib/compare/store';
export function WeightSlider({ axis, value, prefix }: { axis: AxisKey; value: number; prefix: string }) {
  const id = `${prefix}-${axis}`;
  const state = useComparisonStore.getState;
  return <div className="weight-slider"><label htmlFor={id}>{labels[axis]} <output htmlFor={id}>{value}</output></label>
    <input id={id} type="range" min="0" max="40" step="1" value={value}
      aria-label={`${labels[axis]} 가중치`} onPointerDown={() => state().beginAdjustment()}
      onPointerUp={() => state().endAdjustment()} onPointerCancel={() => state().endAdjustment()}
      onKeyDown={event => { if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) state().beginAdjustment(); }}
      onKeyUp={() => state().endAdjustment()} onBlur={() => state().endAdjustment()}
      onChange={event => state().setWeight(axis, Number(event.target.value))}/>
  </div>;
}
