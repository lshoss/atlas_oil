import type { ReactNode } from 'react';
import type { Quote } from '../lib/types';
import { QuoteCard } from './QuoteCard';

const PLACEHOLDER_CARDS = 3;

interface QuoteGroupProps {
  title: string;
  description: string;
  tone: 'amber' | 'teal';
  icon: ReactNode;
  quotes: Quote[];
  selectedSymbol: string;
  onSelect: (symbol: string) => void;
}

export function QuoteGroup({
  title,
  description,
  tone,
  icon,
  quotes,
  selectedSymbol,
  onSelect,
}: QuoteGroupProps) {
  return (
    <section className={`quote-group quote-group--${tone}`} aria-label={title}>
      <header className="quote-group__head">
        {icon}
        <h2>{title}</h2>
        <p>{description}</p>
      </header>
      <div className="quote-group__cards">
        {quotes.map((quote) => (
          <QuoteCard
            key={quote.symbol}
            quote={quote}
            selected={quote.symbol === selectedSymbol}
            onSelect={onSelect}
          />
        ))}
        {quotes.length === 0 &&
          Array.from({ length: PLACEHOLDER_CARDS }, (_, index) => (
            <div key={index} className="quote-card quote-card--placeholder" aria-hidden="true" />
          ))}
      </div>
    </section>
  );
}
