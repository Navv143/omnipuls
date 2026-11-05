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
