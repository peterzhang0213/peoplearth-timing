-- Rollback preserves the original timing event and marks it reverted.
-- The prior status constraint omitted that audit state, causing mobile rollback
-- to fail with a timing_events check-constraint violation.
alter table public.timing_events
  drop constraint if exists timing_events_status_check;

alter table public.timing_events
  add constraint timing_events_status_check
  check (
    status in (
      'accepted',
      'unbound_card',
      'duplicate_tap',
      'wrong_gate',
      'wrong_checkpoint',
      'already_finished',
      'invalid_progress',
      'reverted'
    )
  );
