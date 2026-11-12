import { LuMessageSquare, LuNewspaper } from 'react-icons/lu';
import { usePolling } from '../hooks/usePolling';
import { fetchNews } from '../lib/api';
import { timeAgo } from '../lib/format';
import type { NewsSourceStatus } from '../lib/types';

const REFRESH_MS = 5 * 60_000;

function sourceNote(sources: NewsSourceStatus[]): string | null {
  const finnhub = sources.find((source) => source.name === 'Finnhub');
  if (finnhub?.status === 'no_key') {
    return 'Adicione FINNHUB_API_KEY para incluir notícias em inglês.';
  }
  const failed = sources.filter((source) => source.status === 'error');
  if (failed.length > 0) {
    return `${failed.map((source) => source.name).join(' e ')} não respondeu.`;
  }
  return null;
}

interface NewsPanelProps {
  onAsk: (question: string) => void;
}

export function NewsPanel({ onAsk }: NewsPanelProps) {
  const { data, error, loading, reload } = usePolling(fetchNews, REFRESH_MS);
  const note = data && sourceNote(data.sources);

  return (
    <section className="panel news-panel" aria-labelledby="news-title">
      <header className="news-panel__head">
        <div className="news-panel__title">
          <LuNewspaper aria-hidden="true" />
          <h2 id="news-title">Notícias do setor</h2>
        </div>
        {note && <p className="news-panel__note">{note}</p>}
      </header>

      {data?.stale && (
        <p className="news-panel__note">As fontes não responderam. Esta é a última lista recebida.</p>
      )}

      {!data && loading && <p className="news-panel__empty">Carregando notícias.</p>}

      {!data && !loading && error && (
        <div className="notice">
          <p>{error}</p>
          <button type="button" className="button" onClick={reload}>
            Tentar de novo
          </button>
        </div>
      )}

      {data?.items.length === 0 && (
        <p className="news-panel__empty">Nenhuma notícia do setor nos últimos 3 dias.</p>
      )}

      {data && data.items.length > 0 && (
        <ul className="news-list">
          {data.items.map((item) => (
            <li key={item.title} className="news-item">
              <div className="news-item__row">
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.title}
                </a>
                <button
                  type="button"
                  className="icon-button news-item__ask"
                  title="Perguntar ao Agente Barril sobre esta notícia"
                  aria-label={`Perguntar ao agente sobre: ${item.title}`}
                  onClick={() => onAsk(`O que você sabe sobre esta notícia? "${item.title}"`)}
                >
                  <LuMessageSquare aria-hidden="true" />
                </button>
              </div>
              <div className="news-item__meta">
                <span>
                  {item.source} · {timeAgo(item.published_at)}
                </span>
                {item.tags.map((tag) => (
                  <span key={tag} className="tag">
                    {tag}
                  </span>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
