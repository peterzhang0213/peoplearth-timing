-- Keep each timed entry and wristband intact; member bibs are additional metadata.
alter table public.participants
  add column if not exists member_bib_numbers jsonb not null default '[]'::jsonb;

alter table public.participants drop constraint if exists participants_nanxi_entry_check;

-- Organizer-confirmed men's singles on September 19. These six bibs do not
-- follow the legacy C = men's doubles convention. Never discard team members
-- to repair a conflicting registration: require review of that record instead.
do $$
begin
  if exists (
    select 1 from public.participants
    where race_id = 'nanxi-race-20260919'
      and upper(btrim(bib_number)) in ('C-015','C-016','C-017','C-018','C-019','C-020')
      and (entry_type is distinct from 'individual'
        or jsonb_typeof(member_names) is distinct from 'array'
        or jsonb_array_length(member_names) is distinct from 1)
  ) then
    raise exception 'C-015 through C-020 are confirmed singles; review conflicting member records before migrating';
  end if;
end $$;

update public.participants
set category_code = 'A', female_count = 0
where race_id = 'nanxi-race-20260919'
  and upper(btrim(bib_number)) in ('C-015','C-016','C-017','C-018','C-019','C-020');

-- Backfill legacy fixed bibs so existing female and male singles immediately
-- appear in their group tab after the API is upgraded.
update public.participants
set category_code = left(upper(bib_number), 1)
where race_id in ('nanxi-race-20260919', 'nanxi-race-20260920')
  and category_code is null
  and bib_number ~ '^[A-G]-[0-9]{3}$';

-- Singles/doubles have a fixed composition. Relay composition must be confirmed
-- by the organizer and is deliberately not inferred from a bib or a name.
update public.participants
set female_count = case category_code
  when 'A' then 0 when 'B' then 1 when 'C' then 0 when 'D' then 2 when 'E' then 1 end
where race_id = 'nanxi-race-20260919'
  and category_code in ('A','B','C','D','E') and female_count is null;

alter table public.participants add constraint participants_nanxi_entry_check check (
  race_id not in ('nanxi-race-20260919', 'nanxi-race-20260920') or (
    bib_number is not null and category_code is not null and female_count is not null
    and bib_number ~ '^[A-Z0-9][A-Z0-9_-]{0,19}$'
    and ((race_id = 'nanxi-race-20260919' and category_code in ('A','B','C','D','E'))
      or (race_id = 'nanxi-race-20260920' and category_code in ('F','G')))
    and ((category_code in ('A','B') and entry_type = 'individual' and jsonb_array_length(member_names) = 1)
      or (category_code in ('C','D','E','F') and entry_type = 'doubles' and jsonb_array_length(member_names) = 2)
      or (category_code = 'G' and entry_type = 'team' and jsonb_array_length(member_names) = 4))
    and female_count between 0 and jsonb_array_length(member_names)
    and (category_code in ('F','G') or female_count = case category_code when 'A' then 0 when 'B' then 1 when 'C' then 0 when 'D' then 2 when 'E' then 1 end)
  )
);

-- Legacy entries have no per-person bibs. Validate any newly supplied roster.
create or replace function public.validate_nanxi_member_bibs()
returns trigger language plpgsql set search_path = '' as $$
declare
  v_bibs text[];
  v_numbers text[];
begin
  if new.race_id not in ('nanxi-race-20260919', 'nanxi-race-20260920') then return new; end if;
  if jsonb_typeof(new.member_bib_numbers) <> 'array' then raise exception '成员选手号必须为数组'; end if;
  select coalesce(array_agg(value), array[]::text[]) into v_bibs
    from jsonb_array_elements_text(new.member_bib_numbers);
  if cardinality(v_bibs) > 0 then
    if cardinality(v_bibs) <> jsonb_array_length(new.member_names)
       or exists (select 1 from unnest(v_bibs) b where b is null or b !~ '^[A-Z0-9][A-Z0-9_-]{0,19}$') then
      raise exception '请填写全部成员的选手号';
    end if;
    if cardinality(v_bibs) <> (select count(distinct b) from unnest(v_bibs) b) then
      raise exception '同一组内成员选手号不能重复';
    end if;
  end if;
  v_numbers := array_append(v_bibs, new.bib_number);
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('nanxi-roster:' || new.race_id, 0));
  if exists (select 1 from public.participants p where p.race_id = new.race_id
    and p.id is distinct from new.id
    and (p.bib_number = any(v_numbers) or p.member_bib_numbers ?| v_numbers)) then
    raise exception '选手号或队伍查询号已绑定本场其他参赛单位';
  end if;
  return new;
end $$;
drop trigger if exists participants_nanxi_member_bibs on public.participants;
create trigger participants_nanxi_member_bibs
  before insert or update of race_id, bib_number, member_names, member_bib_numbers
  on public.participants for each row execute function public.validate_nanxi_member_bibs();
notify pgrst, 'reload schema';
