/** Shared roving focus keys for ordered candidate controls and tabs. */
export function navigationIndex(key: string, index: number, length: number): number | null {
  if (!length) return null;
  if (key === 'Home') return 0;
  if (key === 'End') return length - 1;
  if (key === 'ArrowRight' || key === 'ArrowDown') return (index + 1) % length;
  if (key === 'ArrowLeft' || key === 'ArrowUp') return (index - 1 + length) % length;
  return null;
}
