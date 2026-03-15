export interface OverviewData {
  balanceCents: number;
  equityCents: number;
  todayPnlCents: number;
  weekPnlCents: number;
  monthPnlCents: number;
  allTimePnlCents: number;
  activePositions: number;
  openOrders: number;
  mode: "paper" | "live";
  connected: boolean;
  lastTradeAt: string | null;
  circuitBreakerState: string;
  circuitBreakerReason: string | null;
  isRunning: boolean;
  isPaused: boolean;
}

export interface PortfolioPoint {
  snapshotAt: string;
  equityCents: number;
  balanceCents: number;
}

export interface PositionRow {
  id: string;
  ticker: string;
  title: string;
  side: string;
  size: number;
  entryPriceCents: number;
  currentPriceCents: number;
  unrealizedPnlCents: number;
  isOpen: boolean;
}

export interface OrderRow {
  id: string;
  externalOrderId: string;
  ticker: string;
  side: string;
  action: string;
  priceCents: number;
  size: number;
  status: string;
  createdAt: string;
}

export interface TradeRow {
  id: string;
  ticker: string;
  side: string;
  action: string;
  count: number;
  priceCents: number;
  feeCents: number;
  isMaker: boolean;
  pnlCents: number;
  createdAt: string;
}

export interface MarketRow {
  id: string;
  ticker: string;
  title: string;
  enabled: boolean;
  excluded: boolean;
}

export interface AnalyticsData {
  winRate: number;
  profitFactor: number;
  sharpeRatio: number;
  makerRatio: number;
  totalFills: number;
  totalFeesCents: number;
  totalPnlCents: number;
  depositsCents: number;
  tradingPnlCents: number;
}

export interface NotificationItem {
  id: string;
  type: string;
  title: string;
  message: string;
  read: boolean;
  createdAt: string;
}

export interface BotSettings {
  mode: string;
  maxPositionPerMarket: number;
  globalExposureLimitCents: number;
  dailyLossLimitCents: number;
  drawdownLimit: number;
  baseGamma: number;
  sigma: number;
  minSpreadCents: number;
  orderSize: number;
  signalWeight: number;
  minVolume: number;
  maxMarketSpreadCents: number;
  minTimeToExpiry: number;
  paperMilestoneDays: number;
  telegramToken: string | null;
  telegramChatId: string | null;
  kalshiApiKeyId: string | null;
  settingsPollIntervalSec: number;
  reconciliationIntervalSec: number;
  snapshotIntervalSec: number;
}

export interface PaperMilestoneData {
  targetDays: number;
  profitableDays: number;
  achieved: boolean;
  achievedAt: string | null;
}
