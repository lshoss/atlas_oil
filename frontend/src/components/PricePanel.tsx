import { useCallback, useState } from 'react';
import { usePolling } from '../hooks/usePolling';
import { fetchHistory } from '../lib/api';
import { formatFullDay, formatNumber, formatSignedPercent } from '../lib/format';
import type { PricePoint, RangeKey } from '../lib/types';
import { AreaChart } from './AreaChart';

const RANGES: RangeKey[] = ['7d', '30d', '90d', '1a'];
const REFRESH_MS = 5 * 60_000;

function periodChange(points: PricePoint[]): number | null {
  if (points.length < 2 || points[0].close === 0) return null;
  return (points[points.length - 1].close / points[0].close - 1) * 100;
}

interface PricePanelProps {
  symbol: string;
  range: RangeKey;
  onRangeChange: (range: RangeKey) => void;
}

export function PricePanel({ symbol, range, onRangeChange }: PricePanelProps) {
  const load = useCallback(
    (signal: AbortSignal) => fetchHistory(symbol, range, signal),
    [symbol, range],
  );
  const { data, error, loading, reload } = usePolling(load, REFRESH_MS, `${symbol}:${range}`);

  const points = data?.points ?? [];
  const change = periodChange(points);
  const first = points[0];
  const last = points[points.length - 1];

  return (
    <section className="panel price-panel" aria-labelledby="price-title">
      <header className="price-panel__head">
        <div>
          <div className="price-panel__title">
            <h2 id="price-title">{data?.name ?? 'Petróleo Brent'}</h2>
            <span className="badge">commodity</span>
          </div>
          <p className="price-panel__meta">
            Série histórica · {symbol}
            {change !== null && (
              <>
                {' '}
                · no período:{' '}
                <span className={`period-change period-change--${change >= 0 ? 'up' : 'down'}`}>
                  {formatSignedPercent(change)}
                </span>
              </>
            )}
          </p>
        </div>
        <div className="range-picker" role="group" aria-label="Período do gráfico">
          {RANGES.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={option === range}
              onClick={() => onRangeChange(option)}
            >
              {option}
            </button>
          ))}
        </div>
      </header>

      <div className={`price-panel__plot${loading && data ? ' price-panel__plot--loading' : ''}`}>
        <AreaChart
          points={points}
          label={
            first && last
              ? `Preço do ${symbol} de ${formatFullDay(first.date)} a ${formatFullDay(last.date)}, último valor ${formatNumber(last.close)} ${data?.unit}`
              : `Preço do ${symbol}`
          }
        />
        {!data && !loading && error && (
          <div className="notice notice--overlay">
            <p>{error}</p>
            <button type="button" className="button" onClick={reload}>
              Tentar de novo
            </button>
          </div>
        )}
      </div>

      {data?.stale && (
        <p className="price-panel__warning">
          O {data.source} não respondeu. O gráfico mostra o último dado recebido.
        </p>
      )}

      <p className="price-panel__credit">
        Dados: {data?.source ?? 'Yahoo Finance'}. Gráfico:{' '}
        <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
          TradingView Lightweight Charts™
        </a>
        , © 2025 TradingView, Inc.
      </p>

      <table className="sr-only">
        <caption>Fechamentos do {symbol} no período</caption>
        <thead>
          <tr>
            <th scope="col">Data</th>
            <th scope="col">Preço</th>
          </tr>
        </thead>
        <tbody>
          {points.map((point) => (
            <tr key={point.date}>
              <td>{formatFullDay(point.date)}</td>
              <td>{formatNumber(point.close)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
