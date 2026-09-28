-- Account-isolated Star library used by the paper cards and mind-tree view.
-- Starred payloads are snapshots and intentionally do not reference
-- user_papers, because replace_user_papers refreshes that table atomically.

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

alter table public.user_starred_papers enable row level security;

revoke all on table public.user_starred_papers from anon, authenticated;
grant select, insert, update, delete on table public.user_starred_papers to authenticated;

drop policy if exists "manage own starred papers" on public.user_starred_papers;
create policy "manage own starred papers" on public.user_starred_papers
  for all to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);
