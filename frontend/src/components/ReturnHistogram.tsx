import { dailyReturns, histogram, mean, median, stdDev } from '../lib/stats';
import type { PricePoint, RangeKey } from '../lib/types';

const WIDTH = 720;
const HEIGHT = 210;
const PADDING = { top: 16, right: 16, bottom: 36, left: 34 };
const formatPercent = (value: number) => `${value >= 0 ? '+' : ''}${value.toLocaleString('pt-BR', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}%`;

export function ReturnHistogram({
  points,
  symbol,
  range,
}: {
  points: PricePoint[];
  symbol: string;
  range: RangeKey;
}) {
  const returns = dailyReturns(points);
  if (points.length < 3 || returns.length < 2) {
    return (
      <section className="panel histogram-panel" aria-labelledby="histogram-title">
        <h2 id="histogram-title">Distribuição dos retornos</h2>
        <p className="news-panel__empty">Dados insuficientes para histograma.</p>
      </section>
    );
  }

  const binCount = Math.max(3, Math.min(Math.ceil(Math.sqrt(returns.length)), 30));
  const bins = histogram(returns, binCount);
  const maxCount = Math.max(...bins.map((bin) => bin.count), 1);
  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = HEIGHT - PADDING.top - PADDING.bottom;
  const barWidth = plotWidth / bins.length;

  return (
    <section className="panel histogram-panel" aria-labelledby="histogram-title">
      <header>
        <h2 id="histogram-title">Distribuição dos retornos diários</h2>
        <p>{symbol} · {range} · frequência por intervalo percentual</p>
      </header>
      <svg className="histogram" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={`Histograma dos retornos diários de ${symbol}`}>
        <line x1={PADDING.left} y1={PADDING.top + plotHeight} x2={WIDTH - PADDING.right} y2={PADDING.top + plotHeight} />
        <text x={PADDING.left - 8} y={PADDING.top + 5} textAnchor="end">{maxCount}</text>
        {bins.map((bin, index) => {
          const height = (bin.count / maxCount) * plotHeight;
          const x = PADDING.left + index * barWidth + 1;
          const y = PADDING.top + plotHeight - height;
          return (
            <g key={`${bin.midpoint}-${index}`}>
              <rect x={x} y={y} width={Math.max(barWidth - 2, 1)} height={height} fill={bin.midpoint >= 0 ? '#22c55e' : '#ef4444'}>
                <title>{formatPercent(bin.midpoint)}: {bin.count} dia(s)</title>
              </rect>
              {(index === 0 || index === bins.length - 1 || index === Math.floor(bins.length / 2)) && (
                <text x={x + barWidth / 2} y={HEIGHT - 12} textAnchor="middle">{formatPercent(bin.midpoint)}</text>
              )}
            </g>
          );
        })}
      </svg>
      <div className="histogram-stats">
        <span>Média: {formatPercent(mean(returns))}</span>
        <span>Mediana: {formatPercent(median(returns))}</span>
        <span>Desvio-padrão: {formatPercent(stdDev(returns))}</span>
      </div>
    </section>
  );
}
