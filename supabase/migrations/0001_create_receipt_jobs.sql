create table if not exists receipt_jobs (
    id            uuid primary key default gen_random_uuid(),
    status        text not null default 'pending',
    result        jsonb,
    error_code    text,
    error_message text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create or replace function set_updated_at() returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

drop trigger if exists receipt_jobs_set_updated_at on receipt_jobs;
create trigger receipt_jobs_set_updated_at
before update on receipt_jobs
for each row execute function set_updated_at();
