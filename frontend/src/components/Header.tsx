import { RiDropFill } from 'react-icons/ri';
import type { Polled } from '../hooks/usePolling';
import { formatClock } from '../lib/format';
import type { QuotesResponse } from '../lib/types';

interface MarketStatus {
  tone: 'idle' | 'ok' | 'warn' | 'down';
  source?: string;
  text: string;
}

function describe({ data, error }: Polled<QuotesResponse>): MarketStatus {
  if (!data) {
    return error
      ? { tone: 'down', text: 'cotações indisponíveis' }
      : { tone: 'idle', text: 'carregando cotações' };
  }
  if (!data.updated_at) return { tone: 'down', text: `${data.source} não respondeu` };

  const text = `atualizado às ${formatClock(data.updated_at)}`;
  const incomplete = data.quotes.some((quote) => quote.price === null || quote.stale);
  return incomplete
    ? { tone: 'warn', source: `${data.source}, dados parciais · `, text }
    : { tone: 'ok', source: `${data.source}, com atraso · `, text };
}

export function Header({ quotes }: { quotes: Polled<QuotesResponse> }) {
  const { tone, source, text } = describe(quotes);

  return (
    <header className="topbar">
      <div className="topbar__brand">
        <RiDropFill aria-hidden="true" />
        <span>Barril</span>
      </div>
      <p className={`topbar__status topbar__status--${tone}`} role="status">
        <span>
          {source && <span className="topbar__source">{source}</span>}
          {text}
        </span>
      </p>
    </header>
  );
}
