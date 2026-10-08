export type SliderPolicy = 'ci' | 'production';

export function sliderPolicy(value = 'production'): SliderPolicy {
  if (value !== 'ci' && value !== 'production') throw new Error(`Unknown slider policy: ${value}`);
  return value;
}

export function summarizeSliderSets(sets: number[][], policy: SliderPolicy) {
  if (sets.length !== 3 || sets.some(set => set.length !== 100
    || set.some(ms => !Number.isFinite(ms) || ms < 0))) {
    throw new Error('Slider benchmark requires 3 complete sets of 100 finite durations');
  }
  const results = sets.map((times, index) => {
    const sorted = [...times].sort((a, b) => a - b);
    return { set: index + 1, samples: times.length, p95: sorted[94], max: sorted[99], times };
  });
  const medianP95 = results.map(set => set.p95).sort((a, b) => a - b)[1];
  return {
    policy, limitMs: 100, sets: results, medianP95, max: Math.max(...results.map(set => set.max)),
    passed: policy === 'ci' ? medianP95 <= 100 : results.every(set => set.p95 <= 100),
  };
}

// Self-contained so Playwright can serialize it into either dev or production pages.
export async function measureSliderSet() {
  const input = document.querySelector<HTMLInputElement>('#desktop-demand')!;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  const settle = () => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  const totals = () => [...document.querySelectorAll<HTMLElement>('.desktop-matrix [data-total]')]
    .map(node => [node.dataset.candidateId, node.dataset.total]);
  const order = () => [...document.querySelectorAll<HTMLElement>('.desktop-matrix th[data-candidate-id]')]
    .map(node => node.dataset.candidateId).join();
  const original = input.value, before = JSON.stringify(totals()), originalOrder = order();
  const times: number[] = [];
  let scoresChanged: boolean;
  input.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
  try {
    for (let i = 0; i < 100; i++) {
      const start = window.performance.now();
      setter.call(input, String(i % 41));
      input.dispatchEvent(new Event('input', { bubbles: true }));
      await settle();
      times.push(window.performance.now() - start);
      if (order() !== originalOrder) throw new Error('Column order changed during slider adjustment');
    }
    scoresChanged = JSON.stringify(totals()) !== before;
  } finally {
    setter.call(input, original);
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    input.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
    await settle();
  }
  return { times, scoresChanged, restored: input.value === original
    && JSON.stringify(totals()) === before && order() === originalOrder };
}
