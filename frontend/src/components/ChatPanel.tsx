import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { LuBot, LuRotateCw, LuSendHorizontal, LuTrash2 } from 'react-icons/lu';
import { useChat } from '../hooks/useChat';

const MAX_QUESTION_LENGTH = 2000;
const GREETING =
  'Olá! Sou seu analista de petróleo. Pergunte como o mercado funciona e eu explico de forma simples. Por enquanto, não vejo as cotações e as notícias desta tela.';

export function ChatPanel() {
  const { messages, draft, error, streaming, send, retry, clear } = useChat();
  const [question, setQuestion] = useState('');
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
  }, [messages, draft, error]);

  const submit = () => {
    if (!question.trim() || streaming) return;
    send(question);
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
          <p>Explica o mercado sem jargão</p>
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
              <span className="sr-only">Escrevendo a resposta</span>
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
