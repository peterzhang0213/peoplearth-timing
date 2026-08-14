from __future__ import annotations

import json
import uuid

import requests

import server


RACE_ID = "hoka-race-demo"
RACE_NAME = "HOKA 团队挑战赛 - 测试数据"
EXPECTED_CARD_CODES = {f"HOKA-TEST-{index:03d}" for index in range(1, 21)}


def database_request(
    method: str,
    resource: str,
    *,
    params: dict[str, str] | None = None,
    records: list[dict] | dict | None = None,
    prefer: str | None = None,
) -> list[dict]:
    api_key = server.timing_api_key()
    if not api_key:
        raise RuntimeError("Supabase sync needs .timing-api-key or TIMING_API_KEY")
    headers = {
        "apikey": server.SUPABASE_PUBLISHABLE_KEY,
        "X-Timing-API-Key": api_key,
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    response = requests.request(
        method,
        f"{server.SUPABASE_URL}/rest/v1/{resource}",
        params=params,
        headers=headers,
        json=records,
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Supabase {resource} returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    if not response.content or prefer == "return=minimal":
        return []
    payload = response.json()
    return payload if isinstance(payload, list) else [payload]


def edge_request(route: str, payload: dict) -> dict:
    response = requests.post(
        f"{server.SUPABASE_URL}/functions/v1/timing-api/{route}",
        headers={
            "apikey": server.SUPABASE_PUBLISHABLE_KEY,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Supabase timing-api {route} returned HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    result = response.json()
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError(f"Supabase timing-api {route} did not confirm success")
    return result


def local_rows(table: str) -> list:
    with server.connect_db() as db:
        return db.execute(
            f"SELECT * FROM {table} WHERE race_id = ? ORDER BY id",
            (RACE_ID,),
        ).fetchall()


def load_local_data() -> dict[str, list | dict]:
    server.init_db()
    with server.connect_db() as db:
        profile_row = db.execute(
            "SELECT * FROM race_profiles WHERE race_id = ?",
            (RACE_ID,),
        ).fetchone()
    if not profile_row:
        raise RuntimeError("Run seed_hoka_test_data.py before syncing")
    profile = server.race_profile_from_row(profile_row)
    participants = local_rows("participants")
    if profile["name"] != RACE_NAME or len(participants) != 20:
        raise RuntimeError("Local HOKA test race is not the expected 20-team seed")
    card_codes = {row["card_code"] for row in participants}
    if card_codes != EXPECTED_CARD_CODES:
        raise RuntimeError("Local HOKA test card codes do not match the expected seed")
    return {
        "profile": profile,
        "participants": participants,
        "timing_events": local_rows("timing_events"),
        "participant_timing_controls": local_rows("participant_timing_controls"),
        "start_checkins": local_rows("start_checkins"),
        "judge_station_accounts": local_rows("judge_station_accounts"),
    }


def verify_remote_target() -> None:
    profiles = database_request(
        "GET",
        "race_profiles",
        params={"select": "race_id,name", "race_id": f"eq.{RACE_ID}"},
    )
    if profiles and profiles[0].get("name") != RACE_NAME:
        raise RuntimeError("Refusing to replace a remote race with a different name")
    participants = database_request(
        "GET",
        "participants",
        params={"select": "card_code", "race_id": f"eq.{RACE_ID}"},
    )
    unexpected = {
        row.get("card_code") for row in participants
        if row.get("card_code") not in EXPECTED_CARD_CODES
    }
    if unexpected:
        raise RuntimeError("Refusing to replace remote participants outside the HOKA test seed")


def reset_remote_test_rows() -> None:
    admin_code = server.leaderboard_clear_code()
    if len(admin_code) < 8:
        raise RuntimeError("Local administrator code is not configured")
    edge_request(
        "reset-race",
        {
            "raceId": RACE_ID,
            "adminCode": admin_code,
            "confirmation": "SECOND_CONFIRMATION",
        },
    )


def sync() -> dict:
    if server.TIMING_ENVIRONMENT != "development":
        raise RuntimeError("HOKA test data sync must run from the development workspace")
    data = load_local_data()
    verify_remote_target()
    reset_remote_test_rows()

    profile = server.supabase_row(data["profile"], server.RACE_PROFILE_COLUMNS)
    database_request(
        "POST",
        "race_profiles",
        params={"on_conflict": "race_id"},
        records=profile,
        prefer="resolution=merge-duplicates,return=minimal",
    )

    participant_records = []
    local_participant_by_id = {}
    for row in data["participants"]:
        record = server.supabase_row(row, server.PARTICIPANT_COLUMNS)
        local_participant_by_id[int(row["id"])] = row
        record.pop("id", None)
        participant_records.append(record)
    remote_participants = database_request(
        "POST",
        "participants",
        records=participant_records,
        prefer="return=representation",
    )
    participant_ids = {
        row["card_code"]: int(row["id"]) for row in remote_participants
    }
    if set(participant_ids) != EXPECTED_CARD_CODES:
        raise RuntimeError("Supabase did not return all inserted test participants")

    event_records = []
    for row in data["timing_events"]:
        local_participant = local_participant_by_id[int(row["participant_id"])]
        record = server.supabase_row(row, server.TIMING_EVENT_COLUMNS)
        record.pop("id", None)
        record["race_id"] = RACE_ID
        record["participant_id"] = participant_ids[local_participant["card_code"]]
        record["event_id"] = row["event_id"]
        raw_payload = dict(record.get("raw_json") or {})
        raw_payload.update(
            {
                "eventId": record["event_id"],
                "raceId": RACE_ID,
                "participantId": record["participant_id"],
            }
        )
        record["raw_json"] = raw_payload
        event_records.append(record)
    if event_records:
        database_request(
            "POST",
            "timing_events",
            records=event_records,
            prefer="return=minimal",
        )

    checkin_records = []
    for row in data["start_checkins"]:
        local_participant = local_participant_by_id[int(row["participant_id"])]
        card_code = local_participant["card_code"]
        record = server.supabase_row(row, server.START_CHECKIN_COLUMNS)
        record["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{RACE_ID}:{card_code}:checkin"))
        record["race_id"] = RACE_ID
        record["participant_id"] = participant_ids[card_code]
        checkin_records.append(record)
    if checkin_records:
        database_request(
            "POST",
            "start_checkins",
            params={"on_conflict": "race_id,participant_id"},
            records=checkin_records,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    control_records = []
    for row in data["participant_timing_controls"]:
        local_participant = local_participant_by_id[int(row["participant_id"])]
        record = server.supabase_row(row, server.PARTICIPANT_TIMING_CONTROL_COLUMNS)
        record.pop("id", None)
        record["race_id"] = RACE_ID
        record["participant_id"] = participant_ids[local_participant["card_code"]]
        control_records.append(record)
    if control_records:
        database_request(
            "POST",
            "participant_timing_controls",
            records=control_records,
            prefer="return=minimal",
        )

    account_records = []
    for row in data["judge_station_accounts"]:
        account_records.append(
            {
                "race_id": RACE_ID,
                "role": row["role"],
                "username": row["username"],
                "password_hash": row["password_hash"],
                "password_salt": row["password_salt"],
                "display_name": row["display_name"],
                "active": bool(row["active"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    if account_records:
        database_request(
            "POST",
            "judge_station_accounts",
            params={"on_conflict": "race_id,role"},
            records=account_records,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    verification = {
        "participants": len(database_request(
            "GET", "participants",
            params={"select": "id", "race_id": f"eq.{RACE_ID}"},
        )),
        "timingEvents": len(database_request(
            "GET", "timing_events",
            params={"select": "id", "race_id": f"eq.{RACE_ID}"},
        )),
        "startCheckins": len(database_request(
            "GET", "start_checkins",
            params={"select": "id", "race_id": f"eq.{RACE_ID}"},
        )),
        "timingControls": len(database_request(
            "GET", "participant_timing_controls",
            params={"select": "id", "race_id": f"eq.{RACE_ID}"},
        )),
        "judgeAccounts": len(database_request(
            "GET", "judge_station_accounts",
            params={"select": "id", "race_id": f"eq.{RACE_ID}"},
        )),
    }
    return {"ok": True, "raceId": RACE_ID, **verification}


if __name__ == "__main__":
    print(json.dumps(sync(), ensure_ascii=False, indent=2))
