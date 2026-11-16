import { useCallback, useEffect, useRef, useState } from 'react';
import type { NewsItem } from '../lib/types';

export function useNotifications(items: NewsItem[]) {
  const supported = typeof window !== 'undefined' && 'Notification' in window;
  const [permission, setPermission] = useState<NotificationPermission>(
    supported ? Notification.permission : 'denied',
  );
  const [enabled, setEnabled] = useState(false);
  const notified = useRef(new Set<string>());

  const enable = useCallback(async () => {
    if (!supported) return;
    const result = await Notification.requestPermission();
    setPermission(result);
    setEnabled(result === 'granted');
  }, [supported]);

  useEffect(() => {
    if (!enabled || permission !== 'granted') return;
    for (const item of items) {
      if (item.urgency_score < 60 || notified.current.has(item.url)) continue;
      notified.current.add(item.url);
      const notification = new Notification('AtlasOil · notícia urgente', {
        body: `${item.source}: ${item.title}`,
        tag: item.url,
      });
      notification.onclick = () => window.open(item.url, '_blank', 'noopener,noreferrer');
    }
  }, [enabled, items, permission]);

  return { supported, permission, enabled, enable };
}
