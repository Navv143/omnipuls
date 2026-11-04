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
