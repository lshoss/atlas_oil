export type AssetKind = 'commodity' | 'stock';
export type RangeKey = '7d' | '30d' | '90d' | '1a';

export interface Quote {
  symbol: string;
  name: string;
  kind: AssetKind;
  currency: string;
  unit: string;
  price: number | null;
  change_percent: number | null;
  as_of: string | null;
  stale: boolean;
}

export interface QuotesResponse {
  quotes: Quote[];
  source: string;
  updated_at: string | null;
}

export interface PricePoint {
  date: string;
  close: number;
}

export interface HistoryResponse {
  symbol: string;
  name: string;
  kind: AssetKind;
  unit: string;
  range: RangeKey;
  points: PricePoint[];
  source: string;
  updated_at: string;
  stale: boolean;
}

export interface NewsItem {
  title: string;
  url: string;
  source: string;
  published_at: string;
  tags: string[];
}

export interface NewsSourceStatus {
  name: string;
  status: 'ok' | 'no_key' | 'error';
}

export interface NewsResponse {
  items: NewsItem[];
  sources: NewsSourceStatus[];
  updated_at: string;
  stale: boolean;
}

export interface ApiMessage {
  role: 'user' | 'assistant';
  content: string;
}
