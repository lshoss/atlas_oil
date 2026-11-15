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

export interface UIContext {
  selected_symbol?: string;
  selected_range?: RangeKey;
  active_news_url?: string;
}

export type UiActionEvent =
  | { type: 'ui_action'; action: 'select_chart'; symbol: string; range?: RangeKey }
  | { type: 'ui_action'; action: 'refresh_portfolio' };

export interface PortfolioPosition {
  symbol: string;
  name: string;
  quantity: number;
  avg_price: number;
  current_price: number | null;
  currency: string;
  total_cost: number;
  current_value: number | null;
  pnl_value: number | null;
  pnl_pct: number | null;
  updated_at: string;
}

export interface PortfolioResponse {
  positions: PortfolioPosition[];
}

export interface TradeRequest {
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
}

export interface TradeResponse {
  symbol: string;
  side: string;
  quantity: number;
  price: number;
  new_quantity: number;
  new_avg_price: number;
}
