-- Omnipuls: saved files kept across Streamlit Cloud restarts (see cloudstore.py).
-- Row level security is on with no policies: only the server-side secret key (in the app's Secrets) can read or
-- write. The public/publishable key cannot see password hashes or watchlists.
create table if not exists public.app_files (
  name text primary key,
  body jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.app_files enable row level security;

create or replace function public.app_files_touch() returns trigger
language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end $$;

drop trigger if exists app_files_touch on public.app_files;
create trigger app_files_touch before update on public.app_files
  for each row execute function public.app_files_touch();

-- Trading Desk signal log (desk_log.py): the six daily desk checkpoints and the paper trades. One row per
-- (date, checkpoint, kind, name, side), so a checkpoint logged again after an app restart replaces the first copy.
create table if not exists public.desk_log (
  id bigint generated always as identity primary key,
  date text not null,
  checkpoint text not null,
  logged_at text not null default '',
  kind text not null,
  name text not null,
  side text not null default '',
  price double precision,
  chg_pct double precision,
  score double precision,
  why text not null default '',
  extra text not null default '',
  inserted_at timestamptz not null default now(),
  unique (date, checkpoint, kind, name, side)
);
alter table public.desk_log enable row level security;
create index if not exists desk_log_date on public.desk_log (date);

-- Setup Finder (bot.py): one row per run with the full result (rules tried, best rules on unseen days, Nifty MACD).
create table if not exists public.bot_results (
  run_at text primary key,
  result jsonb not null,
  inserted_at timestamptz not null default now()
);
alter table public.bot_results enable row level security;

-- Ideas the master bot passed or put on watch (bots.py), with their result at the close.
create table if not exists public.bot_ideas (
  id bigint generated always as identity primary key,
  day date not null,
  stock text not null,
  side text not null,
  status text,
  first_at text,
  price double precision,
  checks jsonb,
  reasons text,
  result_pct double precision,
  updated_at timestamptz not null default now(),
  unique (day, stock, side)
);
alter table public.bot_ideas enable row level security;

-- Radar events (bots.py): every sudden change with its past-days odds and, after the close, what happened.
create table if not exists public.radar_events (
  id bigint generated always as identity primary key,
  day date not null,
  stock text not null,
  kind text not null,
  side smallint,
  first_at text,
  price double precision,
  text text,
  odds_win double precision,
  odds_n integer,
  result_pct double precision,
  updated_at timestamptz not null default now(),
  unique (day, stock, kind)
);
alter table public.radar_events enable row level security;

-- AI Desk paper calls (agents.py): every TRADE call with its target / stop result.
create table if not exists public.desk_calls (
  id bigint generated always as identity primary key,
  time text not null, symbol text not null, name text, class text, side smallint,
  entry double precision, stop double precision, target double precision, rr double precision, setup text,
  result text, exit double precision, r double precision,
  updated_at timestamptz not null default now(),
  unique (time, symbol)
);
alter table public.desk_calls enable row level security;

-- AI Desk - Intraday paper calls (agents.py / desk_intraday.py, every 5 minutes): crypto, gold, energy, forex.
create table if not exists public.desk_intraday_calls (
  id bigint generated always as identity primary key,
  time text not null, symbol text not null, name text, class text, session text, side smallint,
  entry double precision, stop double precision, target double precision, rr double precision, setup text,
  result text, exit double precision, exit_at text, r double precision, pct double precision,
  updated_at timestamptz not null default now(),
  unique (time, symbol)
);
alter table public.desk_intraday_calls enable row level security;

-- Momentum Funnel snapshots (bots.py, every 5 minutes): stocks that pass step 1, with each step's reading.
create table if not exists public.funnel_log (
  id bigint generated always as identity primary key,
  day date not null, time text not null, stock text not null, side smallint, price double precision,
  day_x double precision, now_x double precision, range_x double precision, sec_net double precision,
  net double precision, net_before double precision, mkt_move double precision, room_atr double precision,
  prev_rng_atr double precision, score double precision, step smallint, suggest boolean,
  updated_at timestamptz not null default now(),
  unique (day, time, stock)
);
alter table public.funnel_log enable row level security;

-- Index snapshots (bots.py, every 5 minutes): funnel steps, index money, futures OI and option OI per index.
create table if not exists public.index_log (
  id bigint generated always as identity primary key,
  day date not null, time text not null, index text not null,
  price double precision, move_pct double precision, side smallint,
  day_x double precision, now_x double precision, range_x double precision,
  net double precision, net_before double precision, buy_share double precision, breadth double precision,
  vix_chg double precision, fut_oi double precision, fut_oi_chg double precision, fut_buildup text, fut_buildup_15m text,
  ce_oi double precision, pe_oi double precision, ce_chg_near double precision, pe_chg_near double precision,
  pcr double precision, support double precision, resistance double precision, writers smallint,
  step smallint, oi_pass boolean,
  updated_at timestamptz not null default now(),
  unique (day, time, index)
);
alter table public.index_log enable row level security;

-- Every live signal with its plan (bots.py): funnel stocks, index funnel, Bank Nifty fade; tracked and scored.
create table if not exists public.trade_signals (
  id bigint generated always as identity primary key,
  day date not null, time text, source text not null, symbol text not null, side smallint,
  entry double precision, sl double precision, tp1 double precision, tp2 double precision, risk_pct double precision,
  score double precision, status text, outcome text, r double precision, pct double precision,
  updated_at timestamptz not null default now(),
  unique (day, source, symbol)
);
alter table public.trade_signals enable row level security;

-- Closing picks (buy near the close, sell next day): recorded at 15:15 by bots.py, scored on the next trading day
create table if not exists public.closing_picks (
  id bigint generated always as identity primary key,
  day date not null, time text, kind text not null, symbol text not null, side smallint,
  price double precision, score double precision, tested boolean, verdict text, reasons text, readings jsonb,
  next_day date, next_open double precision, next_close double precision,
  open_pct double precision, close_pct double precision, next_high_pct double precision,
  updated_at timestamptz not null default now(),
  unique (day, kind, symbol)
);
alter table public.closing_picks enable row level security;

-- How long each page takes on the server (app.py, at most one row a minute per page and viewer)
create table if not exists public.app_perf (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  page text not null, secs double precision, market boolean, sections jsonb
);
alter table public.app_perf enable row level security;

-- Auto Trader (paper): every signal's decision (trade / rejected and why), size and paper result
create table if not exists public.auto_trades (
  id bigint generated always as identity primary key,
  day date not null, time text, source text not null, symbol text not null, side smallint,
  decision text, stage text, reason text, qty double precision, entry double precision, sl double precision,
  tp1 double precision, tp2 double precision, value double precision, risk double precision,
  r double precision, pnl double precision, status text, exit text,
  updated_at timestamptz not null default now(),
  unique (day, source, symbol)
);
alter table public.auto_trades enable row level security;

-- Crypto paper trades (btc_sniper.py via agents.py): one row per day and setup, with the result
create table if not exists public.crypto_paper (
  id bigint generated always as identity primary key,
  day date not null, setup text not null, symbol text, side smallint, signal_at text, entry_at text, entry_at_ist text,
  entry double precision, sl double precision, tp double precision, stop_pct double precision,
  result text, exit_at text, exit_px double precision, r double precision, pct double precision,
  updated_at timestamptz not null default now(),
  unique (day, setup)
);
alter table public.crypto_paper enable row level security;

-- Momentum Funnel quality flags (5 Nov 2026): market with the trade, no gap with it, not chasing
alter table public.funnel_log add column if not exists quality smallint, add column if not exists q_mkt boolean,
  add column if not exists q_gap boolean, add column if not exists q_calm boolean,
  add column if not exists gap_atr double precision, add column if not exists mkt_prev double precision;

-- Index Desk paper trades (bots.py / index_desk.py, every 3-min candle): Nifty, Bank Nifty, Fin Nifty, Sensex, Midcap.
create table if not exists public.index_desk_trades (
  id bigint generated always as identity primary key,
  day date not null, index text not null, signal_at text not null, side smallint, status text, trigger text,
  plan_entry double precision, entry double precision, entry_at text, stop double precision, tp1 double precision,
  tp2 double precision, wall double precision, half_done boolean, half_at text, exit_px double precision, exit_at text,
  result text, points double precision, r double precision, pct double precision,
  updated_at timestamptz not null default now(),
  unique (day, index, signal_at)
);
alter table public.index_desk_trades enable row level security;
