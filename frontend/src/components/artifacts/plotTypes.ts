import type { KeyboardEvent, RefObject } from 'react';
import type { NormChart } from './normalize';

export interface PlotProps {
  chart: NormChart;
  width: number;
  /** Target height for the whole SVG (plot + axis bands). */
  height: number;
  visible: boolean[];
  svgRef: RefObject<SVGSVGElement | null>;
  variant: 'inline' | 'full';
  /** Accessible name for the plot. */
  label: string;
}

/** Arrow / Home / End / Escape stepping through `count` marks. */
export function stepKey(e: KeyboardEvent, count: number, current: number | null): number | null | undefined {
  if (!count) return undefined;
  switch (e.key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return current === null ? 0 : Math.min(count - 1, current + 1);
    case 'ArrowLeft':
    case 'ArrowUp':
      return current === null ? count - 1 : Math.max(0, current - 1);
    case 'Home':
      return 0;
    case 'End':
      return count - 1;
    case 'Escape':
      return current === null ? undefined : null;
    default:
      return undefined;
  }
}
