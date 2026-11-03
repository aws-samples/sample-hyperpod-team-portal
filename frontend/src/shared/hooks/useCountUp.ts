import { useEffect, useRef, useState } from 'react';

/**
 * Lightweight count-up animation — drives a number from its previous value to
 * `target` over `durationMs` using a cubic-out ease curve. Zero dependencies,
 * rAF-based, with safe teardown on unmount.
 *
 * Returns a formatted string so the caller doesn't have to worry about locale
 * commas or decimal precision.
 */
export function useCountUp(
  target: number,
  options: {
    durationMs?: number;
    decimals?: number;
    /** Format thousand separators — default true for large numbers. */
    thousand?: boolean;
  } = {},
): string {
  const { durationMs = 600, decimals = 0, thousand = true } = options;
  const [value, setValue] = useState<number>(target);
  const startValRef = useRef<number>(target);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    // First render: settle immediately so SSR / initial paint isn't janky.
    if (startValRef.current === target && value === target) {
      return;
    }
    const start = startValRef.current;
    const delta = target - start;
    const t0 = performance.now();

    const tick = (now: number) => {
      const elapsed = now - t0;
      const pct = Math.min(1, elapsed / durationMs);
      // Cubic ease-out — fast at start, settles gently at the end.
      const eased = 1 - Math.pow(1 - pct, 3);
      const current = start + delta * eased;
      setValue(current);
      if (pct < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        startValRef.current = target;
        rafRef.current = null;
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      startValRef.current = target;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, durationMs]);

  const fixed = value.toFixed(decimals);
  if (!thousand) return fixed;
  const [intPart, decPart] = fixed.split('.');
  const withCommas = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return decPart ? `${withCommas}.${decPart}` : withCommas;
}
