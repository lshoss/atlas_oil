import { useCallback, useEffect, useRef, useState } from 'react';

export interface Polled<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/** Busca ao montar e a cada intervalo. Mudar `key` refaz a busca sem apagar o dado atual. */
export function usePolling<T>(
  load: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  key = '',
): Polled<T> & { reload: () => void } {
  const [state, setState] = useState<Polled<T>>({ data: null, error: null, loading: true });
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    const controller = new AbortController();

    const run = async () => {
      setState((current) => ({ ...current, loading: true }));
      try {
        const data = await loadRef.current(controller.signal);
        setState({ data, error: null, loading: false });
      } catch (error) {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : 'Erro inesperado.';
        setState((current) => ({ ...current, error: message, loading: false }));
      }
    };

    void run();
    const timer = setInterval(() => {
      if (!document.hidden) void run();
    }, intervalMs);

    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [intervalMs, key, attempt]);

  const reload = useCallback(() => setAttempt((value) => value + 1), []);
  return { ...state, reload };
}
