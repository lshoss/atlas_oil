import { LuArrowDownRight, LuArrowUpRight, LuMinus } from 'react-icons/lu';
import { formatPercent, formatPrice } from '../lib/format';
import type { Quote } from '../lib/types';

function Change({ value }: { value: number }) {
  if (value === 0) {
    return (
      <span className="change">
        <LuMinus aria-hidden="true" />
        {formatPercent(value)}
      </span>
    );
  }
  const rising = value > 0;
  const Icon = rising ? LuArrowUpRight : LuArrowDownRight;
  return (
    <span className={`change change--${rising ? 'up' : 'down'}`}>
      <Icon aria-hidden="true" />
      <span className="sr-only">{rising ? 'Alta de ' : 'Queda de '}</span>
      {formatPercent(value)}
    </span>
  );
}

interface QuoteCardProps {
  quote: Quote;
  selected: boolean;
  onSelect: (symbol: string) => void;
}

export function QuoteCard({ quote, selected, onSelect }: QuoteCardProps) {
  return (
    <article
      className={`quote-card${selected ? ' quote-card--selected' : ''}`}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      aria-label={`Selecionar ${quote.name}`}
      onClick={() => onSelect(quote.symbol)}
      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(quote.symbol)}
    >
      <h3 className="quote-card__symbol">{quote.symbol}</h3>
      <p className="quote-card__name">{quote.name}</p>
      <p className="quote-card__price">
        {quote.price === null ? '—' : formatPrice(quote.price, quote.currency)}
      </p>
      <div className="quote-card__foot">
        <span>{quote.unit}</span>
        {quote.change_percent !== null && <Change value={quote.change_percent} />}
        {quote.price === null && <span className="quote-card__missing">sem dados</span>}
      </div>
    </article>
  );
}
