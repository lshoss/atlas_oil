import type {
  ApiMessage,
  HistoryResponse,
  NewsResponse,
  QuotesResponse,
  RangeKey,
  SseToolCallEvent,
} from './types';

const BACKEND_DOWN = 'O backend não respondeu. Confira se ele está rodando na porta 8000.';

async function errorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === 'object' && 'detail' in body && typeof body.detail === 'string') {
      return body.detail;
    }
  } catch {
    // Sem JSON: o proxy do Vite não alcançou o backend.
  }
  return BACKEND_DOWN;
}

async function request(input: string, init: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (error) {
    if (init.signal?.aborted) throw error;
    throw new Error(BACKEND_DOWN);
  }
  if (!response.ok) throw new Error(await errorMessage(response));
  return response;
}

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await request(path, { signal });
  return (await response.json()) as T;
}

export function fetchQuotes(signal: AbortSignal): Promise<QuotesResponse> {
  return getJson('/api/market/quotes', signal);
}

export function fetchHistory(
  symbol: string,
  range: RangeKey,
  signal: AbortSignal,
): Promise<HistoryResponse> {
  return getJson(`/api/market/history/${symbol}?range=${range}`, signal);
}

export function fetchNews(signal: AbortSignal): Promise<NewsResponse> {
  return getJson('/api/news', signal);
}

type ChatEvent =
  | { type: 'delta'; text: string }
  | { type: 'done'; truncated: boolean }
  | { type: 'error'; message: string }
  | SseToolCallEvent;

export interface ChatOutcome {
  truncated: boolean;
}

export async function streamChat(
  messages: ApiMessage[],
  onDelta: (text: string) => void,
  signal: AbortSignal,
  onToolCall?: (event: SseToolCallEvent) => void,
): Promise<ChatOutcome> {
  const response = await request('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
    signal,
  });
  if (!response.body) throw new Error('O navegador não recebeu a resposta do chat.');

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = '';

  for (;;) {
    const { value, done } = await reader.read();
    if (done) throw new Error('A conexão caiu antes do fim da resposta.');
    buffer += value;

    let boundary = buffer.indexOf('\n\n');
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf('\n\n');

      if (!frame.startsWith('data: ')) continue;
      const event = JSON.parse(frame.slice('data: '.length)) as ChatEvent;
      if (event.type === 'delta') onDelta(event.text);
      if (event.type === 'tool_call') onToolCall?.(event);
      if (event.type === 'done') return { truncated: event.truncated };
      if (event.type === 'error') throw new Error(event.message);
    }
  }
}
