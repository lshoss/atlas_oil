import { useEffect, useRef } from 'react';
import {
  AreaSeries,
  ColorType,
  createChart,
  CrosshairMode,
  isBusinessDay,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts';
import { formatDay, formatFullDay, formatNumber } from '../lib/format';
import type { PricePoint } from '../lib/types';

const AMBER = '#f4a024';
const GRID = '#29231f';
const AXIS_TEXT = '#a39a8e';
const CROSSHAIR = '#6e6459';
const SURFACE = '#1a1511';
const FONT_FAMILY = "'DM Sans', system-ui, sans-serif";
const TOOLTIP_GAP = 14;

function toDay(time: Time): string {
  if (typeof time === 'string') return time;
  if (isBusinessDay(time)) {
    const month = String(time.month).padStart(2, '0');
    const day = String(time.day).padStart(2, '0');
    return `${time.year}-${month}-${day}`;
  }
  return new Date(time * 1000).toISOString().slice(0, 10);
}

/** Cada ponto ocupa uma barra inteira. Cortar meia barra encosta a linha nas bordas. */
function fitToEdges(chart: IChartApi, pointCount: number) {
  if (pointCount > 1) {
    chart.timeScale().setVisibleLogicalRange({ from: 0.5, to: pointCount - 1.5 });
  }
}

function placeTooltip(tooltip: HTMLElement, container: HTMLElement, x: number, y: number) {
  const fitsRight = x + TOOLTIP_GAP + tooltip.offsetWidth <= container.clientWidth;
  const left = fitsRight ? x + TOOLTIP_GAP : x - TOOLTIP_GAP - tooltip.offsetWidth;
  const lowest = container.clientHeight - tooltip.offsetHeight;
  const top = Math.max(0, Math.min(y - tooltip.offsetHeight / 2, lowest));
  tooltip.style.transform = `translate(${left}px, ${top}px)`;
}

export function AreaChart({ points, label }: { points: PricePoint[]; label: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Area'> | null>(null);
  const pointCountRef = useRef(0);

  useEffect(() => {
    const container = containerRef.current;
    const tooltip = tooltipRef.current;
    if (!container || !tooltip) return;

    const chart = createChart(container, {
      autoSize: true,
      handleScale: false,
      handleScroll: false,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: AXIS_TEXT,
        fontFamily: FONT_FAMILY,
        fontSize: 12,
        attributionLogo: false,
      },
      localization: {
        locale: 'pt-BR',
        priceFormatter: formatNumber,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: GRID, style: LineStyle.Solid },
      },
      leftPriceScale: {
        visible: true,
        borderVisible: false,
        scaleMargins: { top: 0.06, bottom: 0.06 },
      },
      rightPriceScale: { visible: false },
      timeScale: {
        borderVisible: false,
        allowBoldLabels: false,
        tickMarkFormatter: (time: Time) => formatDay(toDay(time)),
      },
      crosshair: {
        mode: CrosshairMode.Magnet,
        horzLine: { visible: false, labelVisible: false },
        vertLine: { color: CROSSHAIR, style: LineStyle.Solid, width: 1, labelVisible: false },
      },
    });

    const series = chart.addSeries(AreaSeries, {
      priceScaleId: 'left',
      lineColor: AMBER,
      lineWidth: 2,
      topColor: 'rgba(244, 160, 36, 0.26)',
      bottomColor: 'rgba(244, 160, 36, 0)',
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: SURFACE,
      crosshairMarkerBorderWidth: 2,
    });

    chart.timeScale().subscribeSizeChange(() => fitToEdges(chart, pointCountRef.current));

    chart.subscribeCrosshairMove((param) => {
      const data = param.seriesData.get(series);
      if (!param.point || !param.time || !data || !('value' in data)) {
        tooltip.hidden = true;
        return;
      }
      tooltip.hidden = false;
      tooltip.firstElementChild!.textContent = formatNumber(data.value);
      tooltip.lastElementChild!.textContent = formatFullDay(toDay(param.time));
      placeTooltip(tooltip, container, param.point.x, param.point.y);
    });

    chartRef.current = chart;
    seriesRef.current = series;

    // A fonte da web pode chegar depois do primeiro desenho no canvas.
    let disposed = false;
    void document.fonts?.ready.then(() => {
      if (!disposed) chart.applyOptions({ layout: { fontFamily: FONT_FAMILY } });
    });

    return () => {
      disposed = true;
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    pointCountRef.current = points.length;
    seriesRef.current?.setData(points.map((point) => ({ time: point.date, value: point.close })));
    if (chartRef.current) fitToEdges(chartRef.current, points.length);
  }, [points]);

  return (
    <div className="area-chart" role="img" aria-label={label}>
      <div ref={containerRef} className="area-chart__canvas" />
      <div ref={tooltipRef} className="area-chart__tooltip" hidden>
        <strong />
        <span />
      </div>
    </div>
  );
}
