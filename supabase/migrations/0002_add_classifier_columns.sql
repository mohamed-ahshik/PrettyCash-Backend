alter table receipt_jobs
    add column if not exists classifier_score double precision,
    add column if not exists classifier_model text;

alter table receipt_jobs
    drop constraint if exists receipt_jobs_classifier_score_range;
alter table receipt_jobs
    add constraint receipt_jobs_classifier_score_range
    check (classifier_score is null or classifier_score between 0 and 1);
