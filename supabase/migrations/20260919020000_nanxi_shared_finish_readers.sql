-- Keep one assignment per phone and the existing station exclusivity. Nanxi's
-- finish may have several readers; timing writes remain locked per participant.
alter table public.device_bindings
  drop constraint if exists device_bindings_assignment_unique;
create unique index device_bindings_exclusive_assignment
  on public.device_bindings(race_id, assignment)
  where not (race_id in ('nanxi-race-20260919', 'nanxi-race-20260920') and assignment = 'END');
notify pgrst, 'reload schema';
