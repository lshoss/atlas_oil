import { useCallback, useEffect, useRef, useState } from 'react';
import { streamChat } from '../lib/api';
import type { ApiMessage } from '../lib/types';

const STORAGE_KEY = 'barril.chat.v1';
const MAX_HISTORY = 20;

export interface ChatEntry {
  id: string;
  role: ApiMessage['role'];
  content: string;
  truncated?: boolean;
}

function isChatEntry(value: unknown): value is ChatEntry {
  if (!value || typeof value !== 'object') return false;
  const entry = value as Partial<ChatEntry>;
  return (
    typeof entry.id === 'string' &&
    (entry.role === 'user' || entry.role === 'assistant') &&
    typeof entry.content === 'string' &&
    entry.content.length > 0
  );
}

function loadMessages(): ChatEntry[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    return Array.isArray(parsed) ? parsed.filter(isChatEntry) : [];
  } catch {
    return [];
  }
}

function saveMessages(messages: ChatEntry[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(messages));
  } catch {
    // Sem armazenamento, a conversa só dura até recarregar a página.
  }
}

/** Limita o custo por pergunta. A conversa enviada precisa começar pelo usuário. */
function toApiMessages(messages: ChatEntry[]): ApiMessage[] {
  const recent = messages.slice(-MAX_HISTORY);
  const firstUser = recent.findIndex((message) => message.role === 'user');
  return recent.slice(firstUser).map(({ role, content }) => ({ role, content }));
}

function createEntry(role: ChatEntry['role'], content: string, truncated = false): ChatEntry {
  const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return { id, role, content, ...(truncated && { truncated }) };
}

export function useChat() {
  const [messages, setMessages] = useState<ChatEntry[]>(loadMessages);
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const streaming = draft !== null;

  useEffect(() => saveMessages(messages), [messages]);
  useEffect(() => () => abortRef.current?.abort(), []);

  const answer = useCallback(async (history: ChatEntry[]) => {
    const controller = new AbortController();
    abortRef.current = controller;
    setMessages(history);
    setError(null);
    setDraft('');

    let text = '';
    try {
      const { truncated } = await streamChat(
        toApiMessages(history),
        (delta) => {
          text += delta;
          setDraft(text);
        },
        controller.signal,
      );
      setMessages([...history, createEntry('assistant', text, truncated)]);
    } catch (cause) {
      if (controller.signal.aborted) return;
      if (text) setMessages([...history, createEntry('assistant', text)]);
      setError(cause instanceof Error ? cause.message : 'Erro inesperado.');
    } finally {
      if (abortRef.current === controller) setDraft(null);
    }
  }, []);

  const send = useCallback(
    (text: string) => {
      const question = text.trim();
      if (!question || streaming) return;
      void answer([...messages, createEntry('user', question)]);
    },
    [answer, messages, streaming],
  );

  const retry = useCallback(() => {
    const lastQuestion = messages.findLastIndex((message) => message.role === 'user');
    if (lastQuestion === -1 || streaming) return;
    void answer(messages.slice(0, lastQuestion + 1));
  }, [answer, messages, streaming]);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setDraft(null);
    setError(null);
    setMessages([]);
  }, []);

  return { messages, draft, error, streaming, send, retry, clear };
}
