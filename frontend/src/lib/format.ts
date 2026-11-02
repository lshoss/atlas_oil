const decimal = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatNumber(value: number): string {
  return decimal.format(value);
}

export function formatPrice(value: number, currency: string): string {
  const number = formatNumber(value);
  return currency === 'BRL' ? `R$ ${number}` : number;
}

export function formatPercent(value: number): string {
  return `${formatNumber(Math.abs(value))}%`;
}

export function formatSignedPercent(value: number): string {
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${formatPercent(value)}`;
}

export function formatClock(iso: string): string {
  return new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit' }).format(
    new Date(iso),
  );
}

/** Recebe AAAA-MM-DD. Não passa por Date para o fuso não mudar o dia. */
export function formatDay(day: string): string {
  const [, month, date] = day.split('-');
  return `${date}/${month}`;
}

export function formatFullDay(day: string): string {
  const [year, month, date] = day.split('-');
  return `${date}/${month}/${year}`;
}

export function timeAgo(iso: string, now = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000);
  if (minutes < 1) return 'agora';
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  return `há ${Math.floor(hours / 24)} d`;
}
