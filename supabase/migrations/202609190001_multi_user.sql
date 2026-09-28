-- Multi-user storage for Se Mechanism Daily.
-- Run this migration in a Supabase project before enabling MULTI_USER_MODE.

create extension if not exists pgcrypto;

create table if not exists public.user_settings (
  user_id uuid primary key references auth.users(id) on delete cascade,
  config jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.user_papers (
  user_id uuid not null references auth.users(id) on delete cascade,
  paper_id text not null,
  payload jsonb not null,
  first_seen_at timestamptz,
  last_seen_at timestamptz,
  collection_dates date[] not null default '{}',
  updated_at timestamptz not null default now(),
  primary key (user_id, paper_id)
);

create index if not exists user_papers_user_last_seen_idx
  on public.user_papers (user_id, last_seen_at desc);

-- Starred papers are stored as account-owned snapshots so a collection refresh
-- cannot remove a user's reading list or its mind-tree content.
create table if not exists public.user_starred_papers (
  user_id uuid not null references auth.users(id) on delete cascade,
  paper_id text not null,
  payload jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, paper_id)
);

create index if not exists user_starred_papers_user_created_idx
  on public.user_starred_papers (user_id, created_at desc);

create table if not exists public.collection_runs (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  status text not null check (status in ('running', 'completed', 'failed')),
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  stats jsonb not null default '{}'::jsonb,
  error_message text not null default ''
);

create index if not exists collection_runs_user_started_idx
  on public.collection_runs (user_id, started_at desc);

create table if not exists public.collection_requests (
  id bigint generated always as identity primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  clear_cache boolean not null default false,
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed')),
  requested_at timestamptz not null default now(),
  processed_at timestamptz,
  error_message text not null default ''
);

create index if not exists collection_requests_pending_idx
  on public.collection_requests (status, requested_at);

-- This table is intentionally unavailable to browser roles. Ciphertext is
-- written by the authenticated Edge Function and read by the service job.
create table if not exists public.user_api_credentials (
  user_id uuid not null references auth.users(id) on delete cascade,
  provider text not null check (provider in ('zhipu', 'gemini', 'openai', 'deepseek', 'custom', 'serpapi')),
  ciphertext text not null,
  iv text not null,
  key_last4 text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (user_id, provider)
);

alter table public.user_settings enable row level security;
alter table public.user_papers enable row level security;
alter table public.user_starred_papers enable row level security;
alter table public.collection_runs enable row level security;
alter table public.collection_requests enable row level security;
alter table public.user_api_credentials enable row level security;

revoke all on table public.user_settings from anon, authenticated;
revoke all on table public.user_papers from anon, authenticated;
revoke all on table public.user_starred_papers from anon, authenticated;
revoke all on table public.collection_runs from anon, authenticated;
revoke all on table public.collection_requests from anon, authenticated;
revoke all on table public.user_api_credentials from anon, authenticated;

grant select, insert, update on table public.user_settings to authenticated;
grant select on table public.user_papers to authenticated;
grant select, insert, update, delete on table public.user_starred_papers to authenticated;
grant select on table public.collection_runs to authenticated;
grant select, insert on table public.collection_requests to authenticated;
grant usage, select on sequence public.collection_requests_id_seq to authenticated;

drop policy if exists "read own settings" on public.user_settings;
create policy "read own settings" on public.user_settings
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "insert own settings" on public.user_settings;
create policy "insert own settings" on public.user_settings
  for insert to authenticated with check ((select auth.uid()) = user_id);

drop policy if exists "update own settings" on public.user_settings;
create policy "update own settings" on public.user_settings
  for update to authenticated using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "read own papers" on public.user_papers;
create policy "read own papers" on public.user_papers
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "manage own starred papers" on public.user_starred_papers;
create policy "manage own starred papers" on public.user_starred_papers
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

drop policy if exists "read own runs" on public.collection_runs;
create policy "read own runs" on public.collection_runs
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "read own requests" on public.collection_requests;
create policy "read own requests" on public.collection_requests
  for select to authenticated using ((select auth.uid()) = user_id);

drop policy if exists "create own requests" on public.collection_requests;
create policy "create own requests" on public.collection_requests
  for insert to authenticated with check ((select auth.uid()) = user_id);

-- There is deliberately no browser policy for user_api_credentials.

create or replace function public.replace_user_papers(target_user uuid, paper_rows jsonb)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  item jsonb;
begin
  if coalesce(auth.role(), '') <> 'service_role' then
    raise exception 'service role required';
  end if;

  delete from public.user_papers where user_id = target_user;
  for item in select value from jsonb_array_elements(coalesce(paper_rows, '[]'::jsonb))
  loop
    insert into public.user_papers (
      user_id,
      paper_id,
      payload,
      first_seen_at,
      last_seen_at,
      collection_dates,
      updated_at
    ) values (
      target_user,
      coalesce(nullif(item->>'id', ''), encode(extensions.digest(item::text, 'sha256'), 'hex')),
      item,
      nullif(item->>'first_seen_at', '')::timestamptz,
      nullif(item->>'last_seen_at', '')::timestamptz,
      array(select value::date from jsonb_array_elements_text(coalesce(item->'collection_dates', '[]'::jsonb))),
      now()
    );
  end loop;
end;
$$;

revoke all on function public.replace_user_papers(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.replace_user_papers(uuid, jsonb) to service_role;
