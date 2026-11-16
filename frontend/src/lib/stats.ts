import type { PricePoint } from './types';

export interface HistogramBin {
  midpoint: number;
  count: number;
}

export function dailyReturns(points: PricePoint[]): number[] {
  const values: number[] = [];
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1].close;
    if (previous !== 0) values.push(((points[index].close / previous) - 1) * 100);
  }
  return values;
}

export function mean(values: number[]): number {
  return values.length ? values.reduce((total, value) => total + value, 0) / values.length : 0;
}

export function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function stdDev(values: number[]): number {
  if (!values.length) return 0;
  const average = mean(values);
  return Math.sqrt(mean(values.map((value) => (value - average) ** 2)));
}

export function histogram(values: number[], requestedBins: number): HistogramBin[] {
  if (!values.length) return [];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const count = Math.max(1, requestedBins);
  if (minimum === maximum) return [{ midpoint: minimum, count: values.length }];
  const width = (maximum - minimum) / count;
  const bins = Array.from({ length: count }, (_, index) => ({
    midpoint: minimum + width * (index + 0.5),
    count: 0,
  }));
  for (const value of values) {
    const index = Math.min(Math.floor((value - minimum) / width), count - 1);
    bins[index].count += 1;
  }
  return bins;
}
