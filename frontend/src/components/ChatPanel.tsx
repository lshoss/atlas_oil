import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { LuBot, LuRotateCw, LuSendHorizontal, LuTrash2 } from 'react-icons/lu';
import { useChat } from '../hooks/useChat';
import type { RangeKey, UiActionEvent } from '../lib/types';

const MAX_QUESTION_LENGTH = 2000;
const GREETING =
  'Olá! Sou o Agente Barril. Posso consultar cotações, histórico e notícias em tempo real para responder suas perguntas. O que você quer saber sobre o mercado de petróleo?';

interface ChatPanelProps {
  selectedSymbol: string;
  selectedRange: RangeKey;
  onUiAction: (symbol: string, range?: RangeKey) => void;
  onSendReady: (send: (q: string) => void) => void;
}

export function ChatPanel({ selectedSymbol, selectedRange, onUiAction, onSendReady }: ChatPanelProps) {
  const handleUiAction = (event: UiActionEvent) => {
    if (event.action === 'select_chart') {
      onUiAction(event.symbol, event.range);
    }
  };

  const { messages, draft, error, streaming, send, retry, clear } = useChat({
    context: { selected_symbol: selectedSymbol, selected_range: selectedRange },
    onUiAction: handleUiAction,
  });

  const [question, setQuestion] = useState('');
  const logRef = useRef<HTMLDivElement>(null);

  // Expose send to parent so external components (NewsPanel) can fire questions
  useEffect(() => { onSendReady(send); }, [onSendReady, send]);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, draft, error]);

  const submit = (text?: string) => {
    const q = (text ?? question).trim();
    if (!q || streaming) return;
    send(q);
    setQuestion('');
  };

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    submit();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <aside className="chat" aria-label="Chat com o Agente Barril">
      <header className="chat__head">
        <span className="chat__avatar">
          <LuBot aria-hidden="true" />
        </span>
        <div className="chat__identity">
          <h2>Agente Barril</h2>
          <p>Vê cotações e notícias em tempo real</p>
        </div>
        {messages.length > 0 && (
          <button
            type="button"
            className="icon-button"
            aria-label="Apagar conversa"
            title="Apagar conversa"
            onClick={clear}
          >
            <LuTrash2 aria-hidden="true" />
          </button>
        )}
      </header>

      <div className="chat__log" ref={logRef} role="log" aria-live="polite">
        <p className="bubble">{GREETING}</p>
        {messages.map((message) => (
          <div key={message.id} className="chat__turn">
            <p className={`bubble${message.role === 'user' ? ' bubble--user' : ''}`}>
              {message.content}
            </p>
            {message.truncated && (
              <p className="chat__hint">A resposta foi cortada pelo limite de tamanho.</p>
            )}
          </div>
        ))}
        {draft !== null &&
          (draft ? (
            <p className="bubble">{draft}</p>
          ) : (
            <p className="bubble bubble--typing">
              <span className="sr-only">Consultando dados e escrevendo a resposta</span>
              <span aria-hidden="true" />
              <span aria-hidden="true" />
              <span aria-hidden="true" />
            </p>
          ))}
        {error && (
          <div className="chat__error" role="alert">
            <p>{error}</p>
            <button type="button" className="button" onClick={retry}>
              <LuRotateCw aria-hidden="true" />
              Tentar de novo
            </button>
          </div>
        )}
      </div>

      <form className="chat__composer" onSubmit={handleSubmit}>
        <textarea
          aria-label="Sua pergunta"
          placeholder="Pergunte sobre o mercado"
          rows={2}
          maxLength={MAX_QUESTION_LENGTH}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleKeyDown}
        />
        <button
          type="submit"
          className="chat__send"
          aria-label="Enviar pergunta"
          disabled={streaming || !question.trim()}
        >
          <LuSendHorizontal aria-hidden="true" />
        </button>
      </form>
    </aside>
  );
}
