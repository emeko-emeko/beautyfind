-- Кэш выдачи поиска (запись 032 в JOURNAL.md). Применено в Supabase (проект aqlbpakvqkvlbcztbbgg).
create table if not exists public.search_cache (
  key text primary key,
  saved_at double precision not null,
  payload jsonb not null,
  unavailable jsonb not null default '[]'::jsonb
);
create index if not exists search_cache_saved_at_idx on public.search_cache (saved_at);
alter table public.search_cache enable row level security;
