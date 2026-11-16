import { LuBuilding2, LuDroplet } from 'react-icons/lu';
import { ChatPanel } from './components/ChatPanel';
import { Header } from './components/Header';
import { NewsPanel } from './components/NewsPanel';
import { PricePanel } from './components/PricePanel';
import { QuoteGroup } from './components/QuoteGroup';
import { ReturnHistogram } from './components/ReturnHistogram';
import { usePolling } from './hooks/usePolling';
import { fetchHistory, fetchQuotes } from './lib/api';
import type { RangeKey } from './lib/types';

const QUOTES_REFRESH_MS = 60_000;
const HISTORY_REFRESH_MS = 5 * 60_000;

export function App() {
  const quotes = usePolling(fetchQuotes, QUOTES_REFRESH_MS);
  const allQuotes = quotes.data?.quotes ?? [];
  const [chartSymbol, setChartSymbol] = useState('BRENT');
  const [range, setRange] = useState<RangeKey>('30d');
  const loadHistory = useCallback(
    (signal: AbortSignal) => fetchHistory(chartSymbol, range, signal),
    [chartSymbol, range],
  );
  const history = usePolling(
    loadHistory,
    HISTORY_REFRESH_MS,
    `${chartSymbol}:${range}`,
  );

  useEffect(() => {
    const selectFromChat = (event: Event) => {
      const symbol = (event as CustomEvent<unknown>).detail;
      if (
        typeof symbol === 'string' &&
        (allQuotes.length === 0 || allQuotes.some((quote) => quote.symbol === symbol))
      ) {
        setChartSymbol(symbol);
      }
    };
    window.addEventListener('atlasoil:symbol-selected', selectFromChat);
    return () => window.removeEventListener('atlasoil:symbol-selected', selectFromChat);
  }, [allQuotes]);

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
              selectedSymbol={chartSymbol}
              onSelectSymbol={setChartSymbol}
            />
            <QuoteGroup
              title="Ações e ETFs"
              description="Empresas e fundos ligados ao setor"
              tone="teal"
              icon={<LuBuilding2 aria-hidden="true" />}
              quotes={allQuotes.filter((quote) => quote.kind === 'stock')}
              selectedSymbol={chartSymbol}
              onSelectSymbol={setChartSymbol}
            />
          </div>
          <PricePanel
            symbol={chartSymbol}
            range={range}
            setRange={setRange}
            data={history.data}
            error={history.error}
            loading={history.loading}
            reload={history.reload}
          />
          <ReturnHistogram
            points={history.data?.points ?? []}
            symbol={chartSymbol}
            range={range}
          />
          <NewsPanel />
        </main>
        <ChatPanel />
      </div>
    </div>
  );
}
import { useCallback, useEffect, useState } from 'react';
