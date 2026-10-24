alter table public.receipt_jobs add column if not exists request_id text;

create unique index if not exists receipt_jobs_request_id_key
  on public.receipt_jobs (request_id)
  where request_id is not null;
