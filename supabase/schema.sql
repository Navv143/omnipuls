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
