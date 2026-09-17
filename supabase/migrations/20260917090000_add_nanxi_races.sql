-- Nanxi is independent of the existing HOKA profiles and timing history.
alter table public.participants
  add column if not exists category_code text,
  add column if not exists female_count integer;

alter table public.participants add constraint participants_nanxi_entry_check check (
  race_id not in ('nanxi-race-20260919', 'nanxi-race-20260920') or (
    bib_number is not null and category_code is not null and female_count is not null
    and bib_number ~ '^[A-G]-[0-9]{3}$' and right(bib_number, 3) <> '000'
    and category_code = left(bib_number, 1)
    and ((race_id = 'nanxi-race-20260919' and category_code in ('A','B','C','D','E'))
      or (race_id = 'nanxi-race-20260920' and category_code in ('F','G')))
    and ((category_code in ('A','B') and entry_type = 'individual' and jsonb_array_length(member_names) = 1)
      or (category_code in ('C','D','E','F') and entry_type = 'doubles' and jsonb_array_length(member_names) = 2)
      or (category_code = 'G' and entry_type = 'team' and jsonb_array_length(member_names) = 4))
    and female_count between 0 and jsonb_array_length(member_names)
    and (category_code in ('F','G') or female_count = case category_code when 'A' then 0 when 'B' then 1 when 'C' then 0 when 'D' then 2 when 'E' then 1 end)
  )
);

-- The original cloud schema capped station numbers at 8. Nanxi uses nine
-- stations, and the admin UI allows future profiles up to twenty.
alter table public.timing_events drop constraint if exists timing_events_station_number_check;
alter table public.timing_events add constraint timing_events_station_number_check
  check (station_number is null or station_number between 1 and 20);

create unique index participants_nanxi_bib_unique on public.participants(race_id, bib_number)
  where race_id in ('nanxi-race-20260919', 'nanxi-race-20260920');
create unique index timing_events_nanxi_checkpoint_unique
  on public.timing_events(race_id, participant_id, station_id)
  where status = 'accepted' and participant_id is not null
    and race_id in ('nanxi-race-20260919', 'nanxi-race-20260920');

alter table public.judge_station_accounts drop constraint judge_station_accounts_role_check;
alter table public.judge_station_accounts add constraint judge_station_accounts_role_check
  check (role = 'start' or role ~ '^station_([1-9]|1[0-9]|20)$');

insert into public.race_profiles (race_id, name, mode, station_count, checkpoints, entry_type,
  start_group_size, status, is_template, created_at, updated_at)
select race_id, name, 'station_checkpoints', 9,
  '["START","STATION_2_START","STATION_3_START","STATION_4_START","STATION_5_START","STATION_6_START","STATION_7_START","STATION_8_START","STATION_9_START","END"]'::jsonb,
  'individual', 1, 'active', false, now(), now()
from (values ('nanxi-race-20260919', '南希运动季 · 9 月 19 日'),
             ('nanxi-race-20260920', '南希运动季 · 9 月 20 日')) as races(race_id, name)
on conflict (race_id) do nothing;

-- Both Nanxi input paths take the same lock as the NFC routine before reading progress.
-- Only the Edge API can execute this routine; it authenticates station judges first.
create or replace function public.process_nanxi_checkpoint(p_payload jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_race text := p_payload->>'raceId';
  v_card text := upper(btrim(coalesce(p_payload->>'cardCode', '')));
  v_station text := upper(btrim(coalesce(p_payload->>'stationId', '')));
  v_judge boolean := p_payload->>'source' = 'judge-manual-checkpoint';
  v_participant public.participants%rowtype;
  v_profile public.race_profiles%rowtype;
  v_control text;
  v_previous timestamptz;
  v_time timestamptz := (p_payload->>'eventTime')::timestamptz;
  v_forward jsonb := p_payload;
  v_result jsonb;
begin
  if v_race not in ('nanxi-race-20260919', 'nanxi-race-20260920') then
    raise exception 'This endpoint is for Nanxi only';
  end if;
  select * into v_profile from public.race_profiles where race_id = v_race;
  if v_profile.race_id is null or v_profile.status = 'finalized' then
    return jsonb_build_object('ok', false, 'status', 'race_finalized', 'error', '比赛不存在或已经结束');
  end if;
  if v_judge then
    select * into v_participant from public.participants
      where race_id = v_race and id = (p_payload->>'participantId')::bigint;
    if v_participant.id is null then raise exception 'Participant was not found in this race'; end if;
    v_card := v_participant.card_code;
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_race || ':' || v_card, 0));
  select * into v_participant from public.participants where race_id = v_race and card_code = v_card;
  if v_judge and v_participant.id is distinct from (p_payload->>'participantId')::bigint then
    raise exception '手环绑定已变化，请刷新';
  end if;
  if v_participant.id is not null then
    select action into v_control from public.participant_timing_controls
      where race_id = v_race and participant_id = v_participant.id order by created_at desc, id desc limit 1;
    if v_control in ('pause', 'dnf') then
      return jsonb_build_object('ok', true, 'status', case v_control when 'pause' then 'participant_paused' else 'participant_dnf' end);
    end if;
    if exists (select 1 from public.manual_results where race_id = v_race and participant_id = v_participant.id) then
      return jsonb_build_object('ok', true, 'status', 'already_finished');
    end if;
    select max(event_time) into v_previous from public.timing_events
      where race_id = v_race and participant_id = v_participant.id and status = 'accepted';
    if v_time is null or v_time < v_previous then
      return jsonb_build_object('ok', true, 'status', 'invalid_progress', 'error', '时间不能早于上一站');
    end if;
  end if;
  v_forward := v_forward || jsonb_build_object('cardCode', v_card, 'timingMode', 'manual',
    'gateRole', '', 'stationId', v_station,
    'stationNumber', case when v_station ~ '^STATION_[0-9]+_START$' then split_part(v_station, '_', 2)::integer else null end);
  v_result := public.process_timing_event_v3(v_forward);
  if v_result->>'status' = 'accepted' and v_station = 'START' then
    insert into public.start_checkins (id, race_id, participant_id, device_id, status, confirmed_at, started_at, updated_at)
      values (extensions.gen_random_uuid(), v_race, v_participant.id, p_payload->>'deviceId', 'started', v_time, v_time, now())
      on conflict (race_id, participant_id) do update set status = 'started', started_at = excluded.started_at, updated_at = now();
  end if;
  return v_result;
end;
$$;
revoke all on function public.process_nanxi_checkpoint(jsonb) from public, anon, authenticated;
grant execute on function public.process_nanxi_checkpoint(jsonb) to service_role;
