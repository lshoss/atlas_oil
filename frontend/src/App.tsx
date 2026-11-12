import { useCallback, useRef, useState } from 'react';
import { LuBuilding2, LuDroplet } from 'react-icons/lu';
import { ChatPanel } from './components/ChatPanel';
import { Header } from './components/Header';
import { NewsPanel } from './components/NewsPanel';
import { PricePanel } from './components/PricePanel';
import { QuoteGroup } from './components/QuoteGroup';
import { usePolling } from './hooks/usePolling';
import { fetchQuotes } from './lib/api';
import type { RangeKey } from './lib/types';

const DEFAULT_SYMBOL = 'BRENT';
const DEFAULT_RANGE: RangeKey = '30d';
const QUOTES_REFRESH_MS = 60_000;

export function App() {
  const [selectedSymbol, setSelectedSymbol] = useState<string>(DEFAULT_SYMBOL);
  const [selectedRange, setSelectedRange] = useState<RangeKey>(DEFAULT_RANGE);
  // Ref populated by ChatPanel so NewsPanel can trigger a question without prop drilling
  const sendQuestionRef = useRef<((q: string) => void) | null>(null);

  const quotes = usePolling(fetchQuotes, QUOTES_REFRESH_MS);
  const allQuotes = quotes.data?.quotes ?? [];

  const handleUiAction = useCallback((symbol: string, range?: RangeKey) => {
    setSelectedSymbol(symbol);
    if (range) setSelectedRange(range);
  }, []);

  return (
    <div className="app">
      <Header quotes={quotes} />
      <div className="layout">
        <main className="layout__main">
          <div className="quote-groups">
            <QuoteGroup
              title="Commodities"
              description="Matérias-primas negociadas em dólar"
              tone="amber"
              icon={<LuDroplet aria-hidden="true" />}
              quotes={allQuotes.filter((quote) => quote.kind === 'commodity')}
              selectedSymbol={selectedSymbol}
              onSelect={setSelectedSymbol}
            />
            <QuoteGroup
              title="Ações"
              description="Empresas do setor na B3, em reais"
              tone="teal"
              icon={<LuBuilding2 aria-hidden="true" />}
              quotes={allQuotes.filter((quote) => quote.kind === 'stock')}
              selectedSymbol={selectedSymbol}
              onSelect={setSelectedSymbol}
            />
          </div>
          <PricePanel
            symbol={selectedSymbol}
            range={selectedRange}
            onRangeChange={setSelectedRange}
          />
          <NewsPanel onAsk={(q) => sendQuestionRef.current?.(q)} />
        </main>
        <ChatPanel
          selectedSymbol={selectedSymbol}
          selectedRange={selectedRange}
          onUiAction={handleUiAction}
          onSendReady={(fn) => { sendQuestionRef.current = fn; }}
        />
      </div>
    </div>
  );
}
