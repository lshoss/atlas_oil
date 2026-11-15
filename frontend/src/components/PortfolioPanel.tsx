import { LuBriefcase, LuTrendingDown, LuTrendingUp } from 'react-icons/lu';
import { usePolling } from '../hooks/usePolling';
import { fetchPortfolio } from '../lib/api';
import { formatNumber, formatPercent, formatPrice, formatSignedPercent } from '../lib/format';
import type { PortfolioPosition } from '../lib/types';

const REFRESH_MS = 60_000;

function PnlBadge({ pct, value, currency }: { pct: number | null; value: number | null; currency: string }) {
  if (pct === null || value === null) return null;
  const up = pct >= 0;
  const Icon = up ? LuTrendingUp : LuTrendingDown;
  return (
    <span className={`portfolio-pnl portfolio-pnl--${up ? 'up' : 'down'}`}>
      <Icon aria-hidden="true" />
      <span className="sr-only">{up ? 'Lucro de' : 'Prejuízo de'}</span>
      {formatSignedPercent(pct)}
      <span className="portfolio-pnl__value">
        {up ? '+' : ''}
        {formatPrice(value, currency)}
      </span>
    </span>
  );
}

function HoldingRow({ pos }: { pos: PortfolioPosition }) {
  return (
    <li className="portfolio-row">
      <div className="portfolio-row__head">
        <span className="portfolio-row__symbol">{pos.symbol}</span>
        <span className="portfolio-row__name">{pos.name}</span>
      </div>
      <div className="portfolio-row__data">
        <span className="portfolio-row__qty">
          {formatNumber(pos.quantity)} × PM {formatPrice(pos.avg_price, pos.currency)}
        </span>
        <span className="portfolio-row__price">
          {pos.current_price !== null ? formatPrice(pos.current_price, pos.currency) : '—'}
        </span>
      </div>
      <div className="portfolio-row__pnl">
        <PnlBadge pct={pos.pnl_pct} value={pos.pnl_value} currency={pos.currency} />
        {pos.current_value !== null && (
          <span className="portfolio-row__total">
            {formatPrice(pos.current_value, pos.currency)}
          </span>
        )}
      </div>
    </li>
  );
}

interface PortfolioPanelProps {
  refreshKey: number;
}

export function PortfolioPanel({ refreshKey }: PortfolioPanelProps) {
  const { data, error, loading, reload } = usePolling(fetchPortfolio, REFRESH_MS, String(refreshKey));

  if (!data && loading) return null; // Don't show panel until first load
  if (!data && error) return null;   // Hide silently if portfolio not available yet

  const positions = data?.positions ?? [];
  if (positions.length === 0) return null; // Don't show empty panel

  return (
    <section className="panel portfolio-panel" aria-labelledby="portfolio-title">
      <header className="portfolio-panel__head">
        <div className="portfolio-panel__title">
          <LuBriefcase aria-hidden="true" />
          <h2 id="portfolio-title">Minha Carteira</h2>
        </div>
        {data && (
          <button
            type="button"
            className="button"
            style={{ fontSize: '11px', padding: '3px 8px' }}
            onClick={reload}
          >
            Atualizar
          </button>
        )}
      </header>
      <ul className="portfolio-list">
        {positions.map((pos) => (
          <HoldingRow key={pos.symbol} pos={pos} />
        ))}
      </ul>
    </section>
  );
}
