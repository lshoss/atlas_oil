import { LuNewspaper } from 'react-icons/lu';
import { usePolling } from '../hooks/usePolling';
import { useNotifications } from '../hooks/useNotifications';
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

export function NewsPanel() {
  const { data, error, loading, reload } = usePolling(fetchNews, REFRESH_MS);
  const note = data && sourceNote(data.sources);
  const items = [...(data?.items ?? [])].sort((a, b) => b.urgency_score - a.urgency_score);
  const notifications = useNotifications(items);

  return (
    <section className="panel news-panel" aria-labelledby="news-title">
      <header className="news-panel__head">
        <div className="news-panel__title">
          <LuNewspaper aria-hidden="true" />
          <h2 id="news-title">Notícias do setor</h2>
        </div>
        {note && <p className="news-panel__note">{note}</p>}
      </header>

      {notifications.supported && notifications.permission !== 'denied' && (
        <div className="notifications-banner">
          <p>Notificações só funcionam enquanto esta aba estiver aberta no browser.</p>
          {!notifications.enabled && (
            <button type="button" className="button" onClick={() => void notifications.enable()}>
              Ativar alertas
            </button>
          )}
          {notifications.enabled && <span>Alertas ativados</span>}
        </div>
      )}

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
          {items.map((item) => (
            <li key={item.url} className="news-item">
              <a href={item.url} target="_blank" rel="noreferrer">
                {item.title}
              </a>
              <div className="news-item__meta">
                <span>
                  {item.source} · {timeAgo(item.published_at)} ·{' '}
                  {new Date(item.published_at).toLocaleString('pt-BR', {
                    dateStyle: 'short',
                    timeStyle: 'short',
                  })}
                </span>
                {item.urgency_score >= 60 && <span className="tag tag--urgent">URGENTE</span>}
                {item.urgency_score >= 30 && item.urgency_score < 60 && (
                  <span className="tag tag--relevant">RELEVANTE</span>
                )}
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
