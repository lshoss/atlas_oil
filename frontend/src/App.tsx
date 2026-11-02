import { LuBuilding2, LuDroplet } from 'react-icons/lu';
import { ChatPanel } from './components/ChatPanel';
import { Header } from './components/Header';
import { NewsPanel } from './components/NewsPanel';
import { PricePanel } from './components/PricePanel';
import { QuoteGroup } from './components/QuoteGroup';
import { usePolling } from './hooks/usePolling';
import { fetchQuotes } from './lib/api';

const CHART_SYMBOL = 'BRENT';
const QUOTES_REFRESH_MS = 60_000;

export function App() {
  const quotes = usePolling(fetchQuotes, QUOTES_REFRESH_MS);
  const allQuotes = quotes.data?.quotes ?? [];

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
              selectedSymbol={CHART_SYMBOL}
            />
            <QuoteGroup
              title="Ações"
              description="Empresas do setor na B3, em reais"
              tone="teal"
              icon={<LuBuilding2 aria-hidden="true" />}
              quotes={allQuotes.filter((quote) => quote.kind === 'stock')}
              selectedSymbol={CHART_SYMBOL}
            />
          </div>
          <PricePanel symbol={CHART_SYMBOL} />
          <NewsPanel />
        </main>
        <ChatPanel />
      </div>
    </div>
  );
}
