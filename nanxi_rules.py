"""Nanxi registration and scoring rules, shared by the local API's write paths."""
import re

RACES = {"nanxi-race-20260919": "ABCDE", "nanxi-race-20260920": "FG"}
CATEGORIES = {
    "A": ("男子单人", "individual", 1, 0),
    "B": ("女子单人", "individual", 1, 1),
    "C": ("男子双人", "doubles", 2, 0),
    "D": ("女子双人", "doubles", 2, 2),
    "E": ("混合双人", "doubles", 2, 1),
    "F": ("双人接力", "doubles", 2, None),
    "G": ("四人接力", "team", 4, None),
}


def registration(payload, entry):
    race_id = payload.get("raceId")
    if race_id not in RACES:
        return {"category_code": None, "female_count": None}
    bib = str(payload.get("bibNumber") or "").strip().upper()
    if not re.fullmatch(r"[A-G]-\d{3}", bib) or bib.endswith("-000"):
        raise ValueError("选手号格式为 A-001 至 G-999，不能使用 000")
    category = bib[0]
    if category not in RACES[race_id]:
        raise ValueError("该选手号不属于所选比赛日期：19 日 A–E，20 日 F/G")
    label, entry_type, members, female_count = CATEGORIES[category]
    if entry["entry_type"] != entry_type or len(entry["member_names"]) != members:
        raise ValueError(f"{label}需要 {members} 位成员，参赛类型为 {entry_type}")
    if payload.get("categoryCode") not in (None, "", category):
        raise ValueError("组别与固定选手号不一致")
    if female_count is None:
        value = payload.get("femaleCount")
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= members:
            raise ValueError(f"请确认女性参赛人数（0–{members}）")
        female_count = value
    return {"category_code": category, "female_count": female_count}


def result_fields(participant, adjustments):
    category = participant.get("category_code")
    if not category and participant.get("race_id") in RACES:
        category = str(participant.get("bib_number") or "")[:1]
    if participant.get("race_id") not in RACES or category not in CATEGORIES:
        return {}
    female_count = participant.get("female_count")
    deduction = min(int(female_count or 0), 2) * 300000 if category in "FG" else 0
    return {
        "categoryCode": category, "categoryLabel": CATEGORIES[category][0],
        "femaleCount": female_count, "deductionMs": deduction,
        "penaltyMs": sum(max(0, row["adjustment_ms"]) for row in adjustments),
    }


def rank_categories(results):
    """Only finished entries have an official rank; equal totals share a rank."""
    for category in CATEGORIES:
        entries = [row for row in results if row.get("categoryCode") == category]
        finished = sorted(
            (row for row in entries if row["status"] == "finished" and row["elapsedMs"] is not None),
            key=lambda row: (row["elapsedMs"], row["bibNumber"]),
        )
        for row in entries:
            row.update(rank=None, categoryRank=None, gapMs=None)
        previous_time, rank = None, 0
        for index, row in enumerate(finished, 1):
            if row["elapsedMs"] != previous_time:
                rank = index
            previous_time = row["elapsedMs"]
            row.update(rank=rank, categoryRank=rank, gapMs=row["elapsedMs"] - finished[0]["elapsedMs"])
