"""Database-driven Eclipse Phase 2e Life Path character creation engine."""
from __future__ import annotations

import copy
import random
import re
from typing import Any

from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from spacemarches.models import (
    CharacterDossier,
    GeneratedCharacter,
    LifepathEntry,
    LifepathSession,
    LifepathTable,
)

# Canonical EP2e linked aptitudes & multipliers (from EP2 CRB / meshnet-pack-designs)
SKILL_LINKED_APTITUDE: dict[str, tuple[str, int]] = {
    "Athletics": ("som", 1),
    "Deceive": ("sav", 1),
    "Fray": ("ref", 2),
    "Free Fall": ("som", 1),
    "Guns": ("ref", 1),
    "Infiltrate": ("ref", 1),
    "Infosec": ("cog", 1),
    "Interface": ("cog", 1),
    "Kinesics": ("sav", 1),
    "Melee": ("som", 1),
    "Perceive": ("int", 2),
    "Persuade": ("sav", 1),
    "Program": ("cog", 1),
    "Provoke": ("sav", 1),
    "Psi": ("wil", 1),
    "Research": ("int", 1),
    "Survival": ("int", 1),
    # Hardware
    "Hardware: Aerospace": ("cog", 1),
    "Hardware: Armorer": ("cog", 1),
    "Hardware: Demolitions": ("cog", 1),
    "Hardware: Electronics": ("cog", 1),
    "Hardware: Groundcraft": ("cog", 1),
    "Hardware: Industrial": ("cog", 1),
    "Hardware: Nautical": ("cog", 1),
    "Hardware: Robotics": ("cog", 1),
    # Medicine
    "Medicine: Biotech": ("cog", 1),
    "Medicine: Forensics": ("cog", 1),
    "Medicine: Paramedic": ("cog", 1),
    "Medicine: Pharmacology": ("cog", 1),
    "Medicine: Psychosurgery": ("cog", 1),
    "Medicine: Veterinary": ("cog", 1),
    # Pilot
    "Pilot: Air": ("ref", 1),
    "Pilot: Ground": ("ref", 1),
    "Pilot: Nautical": ("ref", 1),
    "Pilot: Space": ("ref", 1),
    "Pilot: Spacecraft": ("ref", 1),
    # Exotic
    "Exotic Skill: Animal Handling": ("sav", 1),
    "Exotic Skill: Bow": ("ref", 1),
    "Exotic Skill: Bows": ("ref", 1),
    "Exotic Skill: Disguise": ("int", 1),
    "Exotic Skill: Escape Artist": ("ref", 1),
    "Exotic Skill: Monowire Garrote": ("som", 1),
    "Exotic Skill: Plasma Cutters": ("ref", 1),
    "Exotic Skill: Sleight of Hand": ("ref", 1),
    "Exotic Skill: Throwing Knives": ("ref", 1),
    "Exotic Skill: Whips": ("ref", 1),
}

APT_KEYS = ("cog", "int", "ref", "sav", "som", "wil")
REP_NETWORKS = ("@-rep", "c-rep", "f-rep", "g-rep", "i-rep", "r-rep", "x-rep")

STEP_TITLES: dict[int, str] = {
    1: "Step 1: Starting Ego Flex",
    2: "Step 2: Aptitude Template",
    3: "Step 3: Native Tongue",
    4: "Step 4: Background Path",
    5: "Step 5: Youth Event",
    6: "Step 6: Starting Age",
    7: "Step 7: Pre-Fall Life Event",
    8: "Step 8: The Fall",
    9: "Step 9: Career Path",
    10: "Step 10: Interests",
    11: "Step 11: Faction",
    12: "Step 12: Post-Fall Event",
    13: "Step 13: Campaign Event",
    14: "Step 14: Story Event (Optional)",
    15: "Step 15: Final Stats, Gear & Save",
}

DEFAULT_STEP_TABLE: dict[int, str] = {
    1: "starting-flex",
    2: "aptitude-template",
    3: "native-tongue",
    4: "background-path",
    5: "youth-event",
    6: "age",
    7: "pre-fall-event",
    8: "fall-event",
    9: "career-path",
    10: "interest",
    11: "faction",
    12: "post-fall-event",
    13: "",  # player picks Firewall / Gatecrashing / Crime / Skip
    14: "story-event",
    15: "",  # finalization step
}

CAREER_TO_GEAR_PACK: dict[str, str] = {
    "Academic": "Academic",
    "Covert Operative": "Covert Operative",
    "Enforcer": "Enforcer",
    "Explorer": "Explorer",
    "Face": "Face / Dealer",
    "Genehacker": "Genehacker",
    "Hacker": "Hacker",
    "Investigator": "Investigator",
    "Medic": "Medic",
    "Mindhacker": "Mindhacker",
    "Scavenger": "Scavenger",
    "Scientist": "Scientist",
    "Soldier": "Soldier",
    "Techie": "Techie",
}

SYNTHMORPH_KEYWORDS = (
    "case", "synth", "arachnoid", "arachnikoma", "biocore", "blackbird", "cetus",
    "cloud skimmer", "courier", "daitya", "dragonfly", "fenrir", "kite", "flexbot",
    "galatea", "gargoyle", "golem", "griefer", "guard", "liquid silver", "mimic",
    "nautiloid", "oobleck", "opteryx", "ornithope", "prime", "q-morph", "raptor",
    "reaper", "saver", "slitheroid", "spare", "steel morph", "sundiver", "swarmanoid",
    "takko", "whiplash", "xu fu", "operator",
)


def ensure_lifepath_seeded() -> None:
    """Seed LifepathTable/LifepathEntry from fixture if the tables are empty."""
    if not LifepathTable.objects.exists():
        call_command("seed_lifepath_data")


def _new_initial_state(character_name: str = "Unnamed Lifepath Ego") -> dict[str, Any]:
    return {
        "character_name": (character_name or "Unnamed Lifepath Ego").strip()[:160],
        "flex_total": 1,
        "flex_rerolls_remaining": 1,
        "flex_spent_count": 0,
        "aptitudes": {k: 15 for k in APT_KEYS},
        "aptitude_template": "",
        "languages": [],
        "background_group": "",
        "background_sub": "",
        "age_label": "",
        "age_years": None,
        "age_decade": None,
        "subjective_age_years": None,
        "career_group": "",
        "career_sub": "",
        "interest": "",
        "faction": "",
        "morph": {"name": "", "category": "", "module": ""},
        "skills": {},
        "skill_debt": {},
        "know_skills": {},
        "know_debt": {},
        "specializations": [],
        "rep": {},
        "rep_debt": {},
        "traits": [],
        "sleights": [],
        "strain": "",
        "motivations_pool": [],
        "motivations": [],
        "gear": [],
        "gear_pack_campaign": "",
        "gear_pack_profession": "",
        "starting_stress": 0,
        "notes": [],
        "flags": {
            "skip_steps": [],
            "force_interest": "",
            "age_rule": "",
            "extra_prefall_rolls": 0,
            "prefall_rolls_done": 0,
        },
        "active_table_slug": "aptitude-template",
        "pending_sub_rolls": [],
        "pending_choices": [],
        "step_snapshot": None,
        "last_roll": None,
        "history": [
            {
                "step": 1,
                "table": "starting-flex",
                "title": "Starting Ego Flex (+1)",
                "detail": "Every character begins with 1 point of ego Flex.",
            }
        ],
    }


def start_lifepath_session(
    *,
    character_name: str = "Unnamed Lifepath Ego",
    user=None,
    discord_user_id: str = "",
    discord_channel_id: str = "",
    hardcore_flex: bool = False,
    dossier: CharacterDossier | None = None,
) -> LifepathSession:
    """Create and persist a new LifepathSession ready at Step 2 (Step 1 Flex pre-applied)."""
    ensure_lifepath_seeded()
    clean_name = (character_name or "Unnamed Lifepath Ego").strip()[:160] or "Unnamed Lifepath Ego"
    state = _new_initial_state(clean_name)
    return LifepathSession.objects.create(
        user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
        discord_user_id=str(discord_user_id or "").strip(),
        discord_channel_id=str(discord_channel_id or "").strip(),
        character_name=clean_name,
        status=LifepathSession.STATUS_IN_PROGRESS,
        current_step=2,
        hardcore_flex=bool(hardcore_flex),
        state=state,
        dossier=dossier,
    )


def get_active_lifepath_session(
    *,
    user=None,
    discord_user_id: str = "",
    include_completed: bool = False,
) -> LifepathSession | None:
    qs = LifepathSession.objects.all()
    if not include_completed:
        qs = qs.filter(status=LifepathSession.STATUS_IN_PROGRESS)
    else:
        qs = qs.exclude(status=LifepathSession.STATUS_ARCHIVED)
    did = str(discord_user_id or "").strip()
    if did:
        hit = qs.filter(discord_user_id=did).first()
        if hit is not None:
            return hit
    if user is not None and getattr(user, "is_authenticated", False):
        return qs.filter(user=user).first()
    return None


def _take_snapshot(state: dict[str, Any], current_step: int) -> dict[str, Any]:
    snap = copy.deepcopy(state)
    snap.pop("step_snapshot", None)
    snap["__snapshot_step"] = current_step
    return snap


def _roll_d10(rng: random.Random) -> int:
    return rng.randint(1, 10)


def _roll_d100(rng: random.Random) -> int:
    return rng.randint(0, 99)


def _fmt_d10(n: int) -> str:
    return "0" if n == 10 else str(n)


def _lookup_entry_by_roll(
    table: LifepathTable,
    roll_val: int,
    sub_roll_val: int | None = None,
) -> LifepathEntry | None:
    qs = table.entries.filter(is_active=True, roll_min__lte=roll_val, roll_max__gte=roll_val)
    if sub_roll_val is not None:
        sub_hit = qs.filter(sub_roll_min__lte=sub_roll_val, sub_roll_max__gte=sub_roll_val).first()
        if sub_hit is not None:
            return sub_hit
        # Fall back to rows with no sub_roll requirement
        plain_hit = qs.filter(sub_roll_min__isnull=True).first()
        if plain_hit is not None:
            return plain_hit
    return qs.order_by("sort_order", "id").first()


def roll_table_entry(
    table: LifepathTable,
    rng: random.Random,
    *,
    modifier: int = 0,
    ignore_morph_categories: list[str] | None = None,
) -> tuple[LifepathEntry, str]:
    """Roll on any LifepathTable respecting die type, sub-rolls, re-rolls, and print quirks."""
    entries = list(table.entries.filter(is_active=True))
    if not entries:
        raise ValueError(f"Lifepath table '{table.slug}' has no active entries.")

    if table.die_type == LifepathTable.DIE_FIXED:
        return entries[0], "Fixed"

    if table.die_type == LifepathTable.DIE_CHOICE:
        chosen = rng.choice(entries)
        return chosen, "Random Pick"

    if table.die_type == LifepathTable.DIE_D6:
        r = rng.randint(1, 6)
        hit = _lookup_entry_by_roll(table, r) or entries[0]
        return hit, f"1d6={r}"

    if table.die_type == LifepathTable.DIE_D10:
        for _ in range(20):
            r = _roll_d10(rng)
            effective = min(10, max(1, r + modifier)) if modifier else r
            hit = _lookup_entry_by_roll(table, effective)
            if hit is None:
                continue
            # Handle Table 2.0 sub-roll rows (`8`, `9`, `0`)
            if hit.sub_roll_min is not None:
                sr = _roll_d10(rng)
                sub_hit = _lookup_entry_by_roll(table, effective, sr)
                if sub_hit is not None:
                    return sub_hit, f"1d10={_fmt_d10(r)} -> sub 1d10={_fmt_d10(sr)}"
            mod_note = f"+{modifier}={effective}" if modifier else _fmt_d10(r)
            return hit, f"1d10={mod_note}"
        return rng.choice(entries), "1d10 (fallback)"

    if table.die_type == LifepathTable.DIE_D10_PAIR:
        r1 = _roll_d10(rng)
        rerolls = []
        for _ in range(25):
            r2 = _roll_d10(rng)
            hit = _lookup_entry_by_roll(table, r1, r2)
            if hit is not None and (hit.effects or {}).get("flags", {}).get("reroll_sub"):
                rerolls.append(_fmt_d10(r2))
                continue
            if hit is not None:
                note = f"1d10#1={_fmt_d10(r1)}, 1d10#2={_fmt_d10(r2)}"
                if rerolls:
                    note += f" (rerolled {','.join(rerolls)})"
                return hit, note
        return rng.choice(entries), "1d10 pair (fallback)"

    # DIE_D100
    ignored = {c.strip().lower() for c in (ignore_morph_categories or []) if c}
    for _ in range(30):
        r = _roll_d100(rng)
        hit = _lookup_entry_by_roll(table, r)
        if hit is None:
            continue
        mcat = str((hit.effects or {}).get("morph_category") or "").lower()
        if ignored and mcat and any(ig in mcat for ig in ignored):
            continue
        return hit, f"1d100={r:02d}"
    return rng.choice(entries), "1d100 (fallback)"


def _apply_delta_with_debt(
    pool: dict[str, int],
    debt_pool: dict[str, int],
    key: str,
    delta: int,
) -> None:
    if delta == 0:
        return
    if delta > 0:
        existing_debt = debt_pool.get(key, 0)
        if existing_debt > 0:
            if delta >= existing_debt:
                net = delta - existing_debt
                debt_pool.pop(key, None)
                if net > 0:
                    pool[key] = pool.get(key, 0) + net
            else:
                debt_pool[key] = existing_debt - delta
        else:
            pool[key] = pool.get(key, 0) + delta
    else:
        loss = abs(delta)
        current = pool.get(key, 0)
        if current >= loss:
            new_val = current - loss
            if new_val == 0:
                pool.pop(key, None)
            else:
                pool[key] = new_val
        else:
            rem = loss - current
            pool.pop(key, None)
            debt_pool[key] = debt_pool.get(key, 0) + rem


def _add_trait(traits: list[dict[str, Any]], name: str, *, level: int | None = None, delta: int | None = None) -> bool:
    """Apply or stack a trait. Returns False if reducing a trait not possessed."""
    norm = name.strip()
    existing = next((t for t in traits if t["name"].lower() == norm.lower()), None)
    if delta is not None and delta < 0:
        if existing is None:
            return False
        new_lvl = int(existing.get("level", 1)) + delta
        if new_lvl <= 0:
            traits.remove(existing)
        else:
            existing["level"] = new_lvl
        return True
    lvl = level if level is not None else 2
    if existing is not None:
        existing["level"] = int(existing.get("level", 1)) + lvl
    else:
        traits.append({"name": norm, "level": lvl})
    return True


def _apply_aptitude_1d6(rng: random.Random) -> str:
    idx = rng.randint(1, 6)
    return APT_KEYS[idx - 1]


def _apply_aptitude_1d10(rng: random.Random) -> str:
    r = _roll_d10(rng)
    if r == 1:
        return "cog"
    if r in (2, 3):
        return "int"
    if r == 4:
        return "ref"
    if r in (5, 6):
        return "sav"
    if r == 7:
        return "som"
    return "wil"


def _normalize_skill_name(name: str) -> str:
    clean = name.strip()
    if clean == "Pilot: Spacecraft":
        return "Pilot: Space"
    if clean == "Resource":
        return "Resources"
    return clean


def _apply_entry_effects(
    state: dict[str, Any],
    entry: LifepathEntry,
    *,
    roll_label: str,
    step_num: int,
    rng: random.Random,
    is_age_step: bool = False,
) -> list[str]:
    """Apply an entry's structured effects onto state and return human-readable effect highlights."""
    eff = copy.deepcopy(entry.effects or {})
    notes_out: list[str] = []

    # 1. Target entry redirection (e.g., Interest 10.0 -> Interest Package)
    target_code = eff.get("target_entry_code")
    if target_code and entry.next_table_slug:
        sub_entry = LifepathEntry.objects.filter(
            table__slug=entry.next_table_slug, code=target_code, is_active=True
        ).first()
        if sub_entry is not None:
            state["interest"] = sub_entry.title
            sub_notes = _apply_entry_effects(
                state,
                sub_entry,
                roll_label=f"{roll_label} -> {sub_entry.title}",
                step_num=step_num,
                rng=rng,
            )
            return sub_notes

    # 2. Flex
    if eff.get("flex"):
        delta = int(eff["flex"])
        state["flex_total"] = max(0, int(state.get("flex_total", 1)) + delta)
        if delta > 0:
            state["flex_rerolls_remaining"] = int(state.get("flex_rerolls_remaining", 0)) + delta
        else:
            state["flex_rerolls_remaining"] = min(int(state.get("flex_rerolls_remaining", 0)), state["flex_total"])
        notes_out.append(f"Ego Flex {delta:+d}")

    # 3. Aptitudes
    if isinstance(eff.get("set_aptitudes"), dict):
        for k, v in eff["set_aptitudes"].items():
            state["aptitudes"][k.lower()] = int(v)
        state["aptitude_template"] = entry.title
        notes_out.append(f"Aptitude Template: {entry.title}")

    if isinstance(eff.get("aptitudes"), dict):
        for k, v in eff["aptitudes"].items():
            kl = k.lower()
            state["aptitudes"][kl] = max(1, int(state["aptitudes"].get(kl, 15)) + int(v))
            notes_out.append(f"{kl.upper()} {int(v):+d}")

    # 4. Skills & Know skills
    if isinstance(eff.get("skills"), dict):
        for sname, pts in eff["skills"].items():
            sn = _normalize_skill_name(sname)
            if sn.startswith("Know:"):
                kname = sn[5:].strip()
                _apply_delta_with_debt(state["know_skills"], state["know_debt"], kname, int(pts))
                notes_out.append(f"Know: {kname} {int(pts):+d}")
            else:
                _apply_delta_with_debt(state["skills"], state["skill_debt"], sn, int(pts))
                notes_out.append(f"{sn} {int(pts):+d}")

    if isinstance(eff.get("know_skills"), dict):
        for kname, pts in eff["know_skills"].items():
            kn = kname.strip()
            if entry.table.slug == "post-fall-event" and "Interests 10" in kn:
                continue  # handled by faction sub_roll
            _apply_delta_with_debt(state["know_skills"], state["know_debt"], kn, int(pts))
            notes_out.append(f"Know: {kn} {int(pts):+d}")

    if isinstance(eff.get("specializations"), list):
        for sp in eff["specializations"]:
            if isinstance(sp, dict) and sp.get("skill") and sp.get("specialization"):
                state["specializations"].append(sp)
                notes_out.append(f"Spec: {sp['skill']} ({sp['specialization']})")

    # 5. Rep
    if isinstance(eff.get("rep"), dict):
        for rname, pts in eff["rep"].items():
            rn = rname.lower().strip()
            _apply_delta_with_debt(state["rep"], state["rep_debt"], rn, int(pts))
            notes_out.append(f"{rn} {int(pts):+d}")

    # 6. Traits (including Resources fallback)
    if isinstance(eff.get("traits"), list):
        for tr in eff["traits"]:
            if not isinstance(tr, dict) or not tr.get("name"):
                continue
            tname = tr["name"]
            if tr.get("delta"):
                removed = _add_trait(state["traits"], tname, delta=int(tr["delta"]))
                if removed:
                    notes_out.append(f"-1 level {tname}")
                else:
                    fb = tr.get("fallback") or {}
                    fkind = fb.get("kind")
                    if fkind == "trait":
                        _add_trait(state["traits"], fb["name"], level=fb.get("level", 1))
                        notes_out.append(f"Lacked {tname} -> gained {fb['name']}")
                    elif fkind == "rep":
                        _apply_delta_with_debt(state["rep"], state["rep_debt"], fb["rep"], int(fb["amount"]))
                        notes_out.append(f"Lacked {tname} -> {fb['rep']} {fb['amount']:+d}")
                    elif fkind == "rep_choice":
                        state["pending_choices"].append({
                            "id": f"fallback_rep_{len(state['pending_choices'])+1}",
                            "kind": "rep_delta",
                            "amount": int(fb["amount"]),
                            "options": fb["options"],
                            "prompt": f"No {tname}: choose rep for {fb['amount']:+d}",
                        })
                    else:
                        state["notes"].append(f"Lacked {tname}: {fb.get('text', entry.summary)}")
                        notes_out.append(f"Fallback note: {fb.get('text', tname)}")
            else:
                lvl = int(tr.get("level") or 2)
                _add_trait(state["traits"], tname, level=lvl)
                notes_out.append(f"Trait: {tname} (Lvl {lvl})")

    # 7. Languages
    if isinstance(eff.get("languages"), list):
        for lang in eff["languages"]:
            if lang and lang not in state["languages"]:
                state["languages"].append(lang)
                notes_out.append(f"Language: {lang}")

    # 8. Motivations
    if isinstance(eff.get("motivations"), list):
        for mot in eff["motivations"]:
            if mot and mot not in state["motivations_pool"]:
                state["motivations_pool"].append(mot)

    # 9. Morphs
    if eff.get("morph"):
        mcat = eff.get("morph_category") or (
            "synthmorph" if any(k in eff["morph"].lower() for k in SYNTHMORPH_KEYWORDS) else state["morph"].get("category", "")
        )
        state["morph"] = {"name": eff["morph"], "category": mcat, "module": ""}
        notes_out.append(f"Morph: {eff['morph']}")
    if eff.get("morph_module"):
        state["morph"]["module"] = eff["morph_module"]
        notes_out.append(f"Flexbot Module: {eff['morph_module']}")
    if isinstance(eff.get("morph_d10"), list):
        # Resolve 1d10 starting morph sub-roll immediately (or queue? Resolving cleanly with sub-roll record lets Flex reroll work cleanly!)
        r_m = _roll_d10(rng)
        chosen_m = eff["morph_d10"][0]["morph"]
        for row in eff["morph_d10"]:
            if row["roll_min"] <= r_m <= row["roll_max"]:
                chosen_m = row["morph"]
                break
        mcat = "synthmorph" if any(k in chosen_m.lower() for k in SYNTHMORPH_KEYWORDS) else "biomorph"
        state["morph"] = {"name": chosen_m, "category": mcat, "module": ""}
        notes_out.append(f"Morph (1d10={_fmt_d10(r_m)}): {chosen_m}")

    # 10. Sleights & Sub-strains
    if eff.get("kind") == "strain" and eff.get("value"):
        state["strain"] = eff["value"]
        notes_out.append(f"Watts-MacLeod Strain: {eff['value']}")
    if isinstance(eff.get("sleights"), list):
        stype = "Psi-Gamma" if "gamma" in entry.table.slug else "Psi-Chi"
        for sl in eff["sleights"]:
            state["sleights"].append({"name": sl, "type": stype})
            notes_out.append(f"Sleight ({stype}): {sl}")

    # 11. Gear & Notes
    if isinstance(eff.get("gear"), list):
        for g in eff["gear"]:
            state["gear"].append(g)
            notes_out.append(f"Gear: {g.get('name', g)}")
    if isinstance(eff.get("notes"), list):
        for n in eff["notes"]:
            state["notes"].append(n)

    # 12. Flags
    flags = eff.get("flags") or {}
    if flags.get("background_group"):
        state["background_group"] = flags["background_group"]
        if entry.table.category == LifepathTable.CAT_SUBTABLE:
            state["background_sub"] = entry.title
    if flags.get("career_group"):
        state["career_group"] = flags["career_group"]
        if entry.table.category == LifepathTable.CAT_SUBTABLE:
            state["career_sub"] = entry.title
    if flags.get("faction"):
        state["faction"] = flags["faction"]
    if flags.get("age_rule"):
        state["flags"]["age_rule"] = flags["age_rule"]
    if flags.get("force_interest"):
        state["flags"]["force_interest"] = flags["force_interest"]
        notes_out.append(f"Forced Step 10 Interest: {flags['force_interest']}")
    if flags.get("starting_stress"):
        state["starting_stress"] = int(state.get("starting_stress", 0)) + int(flags["starting_stress"])
        notes_out.append(f"Starting Stress +{flags['starting_stress']}")
    if flags.get("extra_prefall_rolls"):
        state["flags"]["extra_prefall_rolls"] = int(state["flags"].get("extra_prefall_rolls", 0)) + int(flags["extra_prefall_rolls"])
        notes_out.append("Extra Step 7 Pre-Fall Event roll")
    for sk in flags.get("skip_steps") or []:
        if sk not in state["flags"]["skip_steps"]:
            state["flags"]["skip_steps"].append(sk)
            notes_out.append(f"Skip Step {sk}")
    if is_age_step and flags.get("age_decade"):
        dec = int(flags["age_decade"])
        state["age_decade"] = dec
        if dec >= 100:
            exact = 100 + rng.randint(0, 30)
            state["age_label"] = f"{exact} (100+)"
        else:
            digit = rng.randint(0, 9)
            exact = dec + digit
            state["age_decade"] = dec
            state["age_label"] = f"{exact} ({dec}s)"
        state["age_years"] = exact
        notes_out.append(f"Age: {state['age_label']}")

    # 13. Queue sub-rolls & interactive choices
    for sr in eff.get("sub_rolls") or []:
        kind = sr.get("kind")
        if kind == "aptitude_1d6_minus":
            ak = _apply_aptitude_1d6(rng)
            state["aptitudes"][ak] = max(1, state["aptitudes"][ak] - 5)
            notes_out.append(f"{ak.upper()} -5 (1d6)")
        elif kind == "aptitude_1d10_plus":
            ak = _apply_aptitude_1d10(rng)
            state["aptitudes"][ak] = state["aptitudes"][ak] + 5
            notes_out.append(f"{ak.upper()} +5 (1d10)")
        elif kind == "aptitude_1d6_plus_minus":
            ak_plus = _apply_aptitude_1d6(rng)
            ak_minus = _apply_aptitude_1d6(rng)
            state["aptitudes"][ak_plus] = state["aptitudes"][ak_plus] + 5
            state["aptitudes"][ak_minus] = max(1, state["aptitudes"][ak_minus] - 5)
            notes_out.append(f"{ak_plus.upper()} +5 / {ak_minus.upper()} -5 (1d6)")
        else:
            cnt = int(sr.get("count") or 1)
            for _ in range(cnt):
                state["pending_sub_rolls"].append(copy.deepcopy(sr))

    for ch in eff.get("choices") or []:
        ch_copy = copy.deepcopy(ch)
        ch_copy.setdefault("step", step_num)
        # Skip optional 60+ exchange prompt if player wants to keep existing skills or auto-mark optional
        state["pending_choices"].append(ch_copy)

    # 14. Append history & last_roll
    state["last_roll"] = {
        "step": step_num,
        "table_slug": entry.table.slug,
        "table_name": entry.table.name,
        "roll": roll_label,
        "entry_code": entry.code,
        "entry_title": entry.title,
        "summary": entry.summary,
        "highlights": notes_out,
    }
    state["history"].append({
        "step": step_num,
        "table": entry.table.slug,
        "roll": roll_label,
        "title": entry.title,
        "detail": "; ".join(notes_out) if notes_out else entry.summary[:140],
    })
    return notes_out


def _advance_next_step_or_table(session: LifepathSession) -> None:
    """Advance active_table_slug / current_step automatically when sub-rolls & choices are clear."""
    state = session.state
    if state.get("pending_choices"):
        return
    if state.get("pending_sub_rolls"):
        nxt = state["pending_sub_rolls"][0]
        state["active_table_slug"] = nxt["table_slug"]
        return

    # Check if current entry points to a mandatory sub-table (e.g. Background 4.0 -> 4.x, Career 9.0 -> 9.x)
    cur_step = int(session.current_step)
    if cur_step == 7:
        state["flags"]["prefall_rolls_done"] = int(state["flags"].get("prefall_rolls_done", 0)) + 1
        needed = 1 + int(state["flags"].get("extra_prefall_rolls", 0))
        if state["flags"]["prefall_rolls_done"] < needed:
            state["active_table_slug"] = "pre-fall-event"
            return

    nxt_step = cur_step + 1
    skip_steps = set(state.get("flags", {}).get("skip_steps") or [])
    while nxt_step in skip_steps and nxt_step < 15:
        state["history"].append({
            "step": nxt_step,
            "table": DEFAULT_STEP_TABLE.get(nxt_step, ""),
            "roll": "Skipped",
            "title": STEP_TITLES.get(nxt_step, f"Step {nxt_step}"),
            "detail": f"Skipped per earlier Life Path rule ({state['flags'].get('age_rule') or 'Event'}).",
        })
        nxt_step += 1

    session.current_step = min(15, nxt_step)
    state["active_table_slug"] = DEFAULT_STEP_TABLE.get(session.current_step, "")


def perform_step_roll(
    session: LifepathSession,
    *,
    table_slug: str | None = None,
    chosen_entry_code: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Execute a roll or player choice on the active (or specified) LifepathTable."""
    ensure_lifepath_seeded()
    rng = random.Random(seed) if seed is not None else random.Random()
    state = session.state

    if state.get("pending_choices"):
        raise ValueError("Please resolve the pending choice before rolling the next table.")

    # Save snapshot for Flex Reroll BEFORE modifying anything
    state["step_snapshot"] = _take_snapshot(state, session.current_step)

    # Check pending sub-roll queue first unless overriding Step 13 campaign choice
    sub_roll_meta = None
    if state.get("pending_sub_rolls"):
        sub_roll_meta = state["pending_sub_rolls"].pop(0)
        eff_slug = sub_roll_meta["table_slug"]
    else:
        eff_slug = (table_slug or state.get("active_table_slug") or DEFAULT_STEP_TABLE.get(session.current_step, "")).strip()

    if not eff_slug:
        raise ValueError(f"No roll table is active at Step {session.current_step}.")

    # Special background Age exceptions at Step 6
    if eff_slug == "age" and session.current_step == 6:
        age_rule = (state.get("flags") or {}).get("age_rule", "")
        if age_rule == "infolife":
            state["age_decade"] = 20
            state["age_years"] = 20 + rng.randint(0, 9)
            state["age_label"] = f"{state['age_years']} (Infolife 20s)"
            if 7 not in state["flags"]["skip_steps"]:
                state["flags"]["skip_steps"].append(7)
            state["last_roll"] = {
                "step": 6,
                "table_slug": "age",
                "table_name": "Infolife Age Rule",
                "roll": "Fixed 20s",
                "entry_code": "infolife-20s",
                "entry_title": f"Infolife Age: {state['age_label']}",
                "summary": "Infolife characters start in their 20s and skip directly to Step 8: The Fall.",
                "highlights": [f"Age {state['age_label']}", "Skip Step 7"],
            }
            state["history"].append({
                "step": 6,
                "table": "age",
                "roll": "Infolife",
                "title": state["last_roll"]["entry_title"],
                "detail": "Infolife skips Step 7.",
            })
            _advance_next_step_or_table(session)
            session.save(update_fields=["current_step", "state", "updated_at"])
            return state["last_roll"]
        if age_rule == "lost":
            subj_d6 = rng.randint(1, 6)
            state["age_years"] = 9
            state["subjective_age_years"] = 20 + subj_d6
            state["age_label"] = f"9 chronological ({20 + subj_d6} subjective)"
            for sk in (7, 8):
                if sk not in state["flags"]["skip_steps"]:
                    state["flags"]["skip_steps"].append(sk)
            state["last_roll"] = {
                "step": 6,
                "table_slug": "age",
                "table_name": "Lost Age Rule",
                "roll": f"9 chron / 20+1d6({subj_d6})={20+subj_d6} subj",
                "entry_code": "lost-age",
                "entry_title": f"Lost Age: {state['age_label']}",
                "summary": "Lost characters are 9 chronologically (20+1d6 subjective) and skip Steps 7 & 8.",
                "highlights": [state["age_label"], "Skip Steps 7 & 8"],
            }
            state["history"].append({
                "step": 6,
                "table": "age",
                "roll": "Lost",
                "title": state["last_roll"]["entry_title"],
                "detail": "Lost skips Steps 7 & 8.",
            })
            _advance_next_step_or_table(session)
            session.save(update_fields=["current_step", "state", "updated_at"])
            return state["last_roll"]

    # Special Step 10 Forced Async rule
    if eff_slug == "interest" and session.current_step == 10 and (state.get("flags") or {}).get("force_interest") == "Async":
        async_entry = LifepathEntry.objects.filter(
            table__slug="interest-packages", title__iexact="Async", is_active=True
        ).first()
        if async_entry is not None:
            state["interest"] = "Async"
            notes = _apply_entry_effects(
                state,
                async_entry,
                roll_label="Forced by Step 8 (Watts-MacLeod)",
                step_num=10,
                rng=rng,
            )
            _advance_next_step_or_table(session)
            session.save(update_fields=["current_step", "state", "updated_at"])
            return {"entry_title": "Async (Forced)", "highlights": notes, **state["last_roll"]}

    table = LifepathTable.objects.filter(slug=eff_slug, is_active=True).first()
    if table is None:
        raise ValueError(f"Lifepath table '{eff_slug}' not found.")

    if chosen_entry_code:
        if not table.allow_choice and not sub_roll_meta:
            raise ValueError(f"Table '{table.name}' requires rolling (manual choice disabled).")
        entry = table.entries.filter(code=chosen_entry_code, is_active=True).first()
        if entry is None:
            raise ValueError(f"Entry '{chosen_entry_code}' not found in '{table.slug}'.")
        roll_label = "Chosen"
    else:
        modifier = int((sub_roll_meta or {}).get("modifier") or 0)
        ignore_cats = (sub_roll_meta or {}).get("ignore") or []
        entry, roll_label = roll_table_entry(table, rng, modifier=modifier, ignore_morph_categories=ignore_cats)
        # Uplift age cap <= 50
        if table.slug == "age" and (state.get("flags") or {}).get("age_rule") == "uplift":
            while int((entry.effects or {}).get("flags", {}).get("age_decade") or 20) > 50:
                entry, roll_label = roll_table_entry(table, rng)

    highlights = _apply_entry_effects(
        state,
        entry,
        roll_label=roll_label,
        step_num=session.current_step,
        rng=rng,
        is_age_step=(table.slug == "age"),
    )

    # Uplift exact age <= 50
    if table.slug == "age" and (state.get("flags") or {}).get("age_rule") == "uplift":
        if state.get("age_decade") == 50:
            state["age_years"] = 50
            state["age_label"] = "50 (Uplift max)"

    # Handle chaining to sub-table when entry has next_table_slug and isn't already resolved via target_entry_code
    if entry.next_table_slug and not (entry.effects or {}).get("target_entry_code"):
        if table.slug in ("background-path", "career-path", "morph-type", "sleight-type", "trait-type"):
            if table.slug in ("morph-type", "sleight-type", "trait-type"):
                state["pending_sub_rolls"].insert(0, {"table_slug": entry.next_table_slug, "reason": entry.title})
            else:
                state["active_table_slug"] = entry.next_table_slug
                session.save(update_fields=["current_step", "state", "updated_at"])
                return {**state["last_roll"], "highlights": highlights}

    _advance_next_step_or_table(session)
    session.save(update_fields=["current_step", "state", "updated_at"])
    return {**state["last_roll"], "highlights": highlights}


def skip_optional_step(session: LifepathSession, *, reason: str = "Skipped") -> LifepathSession:
    """Skip Step 13 or Step 14 cleanly."""
    if session.current_step not in (13, 14):
        raise ValueError(f"Step {session.current_step} cannot be skipped directly.")
    state = session.state
    if state.get("pending_choices") or state.get("pending_sub_rolls"):
        raise ValueError("Resolve pending sub-rolls or choices before skipping.")
    state["step_snapshot"] = None
    state["history"].append({
        "step": session.current_step,
        "table": DEFAULT_STEP_TABLE.get(session.current_step, ""),
        "roll": "Skipped",
        "title": f"Skipped Step {session.current_step}",
        "detail": reason,
    })
    session.current_step += 1
    state["active_table_slug"] = DEFAULT_STEP_TABLE.get(session.current_step, "")
    session.save(update_fields=["current_step", "state", "updated_at"])
    return session


def use_flex_reroll(session: LifepathSession, *, seed: int | None = None) -> dict[str, Any]:
    """Spend 1 Flex reroll charge to revert the last roll/stage and roll again!"""
    state = session.state
    rerolls_left = int(state.get("flex_rerolls_remaining", 0))
    if rerolls_left <= 0:
        raise ValueError("No Ego Flex rerolls remaining.")
    snapshot = state.get("step_snapshot")
    last_roll = state.get("last_roll")
    if not snapshot or not last_roll:
        raise ValueError("Nothing eligible to reroll right now.")

    prev_table = last_roll.get("table_slug")
    prev_step = int(snapshot.get("__snapshot_step", session.current_step))
    prev_title = last_roll.get("entry_title", "previous roll")

    restored = copy.deepcopy(snapshot)
    restored.pop("__snapshot_step", None)
    # Deduct 1 Flex reroll charge (and deduct flex_total only in hardcore mode)
    restored["flex_rerolls_remaining"] = max(0, rerolls_left - 1)
    restored["flex_spent_count"] = int(state.get("flex_spent_count", 0)) + 1
    if session.hardcore_flex:
        restored["flex_total"] = max(0, int(restored.get("flex_total", 1)) - 1)
    restored["history"].append({
        "step": prev_step,
        "table": prev_table,
        "roll": "FLEX REROLL",
        "title": f"Spent Flex to reroll '{prev_title}'",
        "detail": f"Remaining rerolls: {restored['flex_rerolls_remaining']}",
    })
    session.current_step = prev_step
    session.state = restored
    session.save(update_fields=["current_step", "state", "updated_at"])

    return perform_step_roll(session, table_slug=prev_table, seed=seed)


def get_choice_options_for_pending(choice: dict[str, Any]) -> list[dict[str, str]]:
    """Build selectable choice options (label + value) for Discord/web UI."""
    kind = choice.get("kind")
    if kind == "skill_option":
        return [{"label": f"{o['skill']} (+{o['points']})", "value": o["skill"]} for o in (choice.get("options") or [])]
    if kind == "trait_option":
        return [{"label": f"{o['name']} (Lvl {o.get('level', 2)})", "value": o["name"]} for o in (choice.get("options") or [])]
    if kind == "gear_option":
        return [{"label": o, "value": o} for o in (choice.get("options") or [])]
    if kind == "rep_delta":
        amt = int(choice.get("amount") or 0)
        return [{"label": f"{r} ({amt:+d})", "value": r} for r in (choice.get("options") or REP_NETWORKS)]
    if kind == "aptitude_delta":
        amt = int(choice.get("amount") or 5)
        return [{"label": f"{k.upper()} ({amt:+d})", "value": k} for k in APT_KEYS]
    if kind == "language":
        tbl = LifepathTable.objects.filter(slug="native-tongue").first()
        if tbl:
            return [{"label": e.title, "value": e.title} for e in tbl.entries.filter(is_active=True) if e.title != "Other"]
    if kind == "disorder":
        tbl = LifepathTable.objects.filter(slug="disorders").first()
        if tbl:
            return [{"label": e.title, "value": e.title} for e in tbl.entries.filter(is_active=True)]
    if kind == "sleight":
        scope = choice.get("scope", "any_psi")
        opts: list[dict[str, str]] = []
        if scope in ("psi-chi", "any_psi"):
            tbl = LifepathTable.objects.filter(slug="psi-chi-sleights").first()
            if tbl:
                opts.extend([{"label": f"[Chi] {e.title}", "value": f"Psi-Chi::{e.title}"} for e in tbl.entries.filter(is_active=True)])
        if scope in ("psi-gamma", "any_psi"):
            tbl = LifepathTable.objects.filter(slug="psi-gamma-sleights").first()
            if tbl:
                opts.extend([{"label": f"[Gamma] {e.title}", "value": f"Psi-Gamma::{e.title}"} for e in tbl.entries.filter(is_active=True)])
        return opts
    if kind == "skill_bonus":
        scope = choice.get("scope", "any")
        if scope == "hardware":
            tbl = LifepathTable.objects.filter(slug="skill-hardware").first()
            if tbl:
                return [{"label": f"Hardware: {e.title}", "value": f"Hardware: {e.title}"} for e in tbl.entries.filter(is_active=True)]
        if scope == "pilot":
            tbl = LifepathTable.objects.filter(slug="skill-pilot").first()
            if tbl:
                return [{"label": f"Pilot: {e.title}", "value": f"Pilot: {e.title}"} for e in tbl.entries.filter(is_active=True)]
        if scope == "exotic":
            tbl = LifepathTable.objects.filter(slug="skill-exotic").first()
            if tbl:
                return [{"label": f"Exotic Skill: {e.title}", "value": f"Exotic Skill: {e.title}"} for e in tbl.entries.filter(is_active=True)]
        if scope.startswith("know_category:"):
            cat_str = scope.split(":", 1)[1].lower()
            slugs = []
            if "art" in cat_str:
                slugs.append("skill-know-art")
            if "interest" in cat_str:
                slugs.append("skill-know-interest")
            if "academic" in cat_str:
                slugs.append("skill-know-academic")
            if "professional" in cat_str:
                slugs.append("skill-know-profession")
            out: list[dict[str, str]] = []
            for s in slugs:
                tbl = LifepathTable.objects.filter(slug=s).first()
                if tbl:
                    out.extend([{"label": f"Know: {e.title}", "value": f"Know: {e.title}"} for e in tbl.entries.filter(is_active=True)])
            return out
        # Generic active / any
        tbl = LifepathTable.objects.filter(slug="skill-active").first()
        if tbl:
            return [{"label": e.title, "value": e.title} for e in tbl.entries.filter(is_active=True) if "[" not in e.title]
    if kind == "rep_network_note":
        return [{"label": r, "value": r} for r in REP_NETWORKS]
    return []


def resolve_pending_choice(
    session: LifepathSession,
    *,
    selected_value: str | None = None,
    auto_roll: bool = False,
    seed: int | None = None,
) -> dict[str, Any]:
    """Resolve the next item in session.state['pending_choices'] by player selection or random roll."""
    rng = random.Random(seed) if seed is not None else random.Random()
    state = session.state
    choices = state.get("pending_choices") or []
    if not choices:
        raise ValueError("No pending choices to resolve.")

    choice = choices.pop(0)
    kind = choice.get("kind")
    detail = ""

    if auto_roll:
        opts = get_choice_options_for_pending(choice)
        if opts:
            selected_value = rng.choice(opts)["value"]

    val = (selected_value or "").strip()

    if kind == "free_text":
        target = choice.get("target")
        if target == "native_language":
            lang = val or "Custom Language"
            if lang not in state["languages"]:
                state["languages"].append(lang)
            detail = f"Native language: {lang}"
        else:
            state["notes"].append(f"{choice.get('prompt', 'Custom')}: {val or 'Unspecified'}")
            detail = f"{val}"
    elif kind == "fixed_specialization":
        state["specializations"].append({"skill": choice["skill"], "specialization": choice["spec"]})
        detail = f"Spec: {choice['skill']} ({choice['spec']})"
    elif kind == "specialization":
        skills_list = list((state.get("skills") or {}).keys()) + [f"Know: {k}" for k in (state.get("know_skills") or {}).keys()]
        skill_target = val or (skills_list[0] if skills_list else "Chosen Skill")
        state["specializations"].append({"skill": skill_target, "specialization": "Chosen Specialization"})
        detail = f"Specialization in {skill_target}"
    elif kind == "skill_option":
        chosen = next((o for o in (choice.get("options") or []) if o["skill"].lower() == val.lower()), None)
        if chosen is None:
            chosen = choice["options"][0]
        sk = _normalize_skill_name(chosen["skill"])
        pts = int(chosen["points"])
        if sk.startswith("Know:"):
            kn = sk[5:].strip()
            _apply_delta_with_debt(state["know_skills"], state["know_debt"], kn, pts)
        else:
            _apply_delta_with_debt(state["skills"], state["skill_debt"], sk, pts)
        detail = f"{sk} {pts:+d}"
    elif kind == "trait_option":
        chosen = next((o for o in (choice.get("options") or []) if o["name"].lower() == val.lower()), None)
        if chosen is None:
            chosen = choice["options"][0]
        _add_trait(state["traits"], chosen["name"], level=int(chosen.get("level", 2)))
        detail = f"Trait: {chosen['name']} (Lvl {chosen.get('level', 2)})"
    elif kind == "gear_option":
        picked = val or (choice.get("options") or ["Item"])[0]
        if not picked.lower().startswith("decline"):
            state["gear"].append({"name": picked, "complexity": "Event", "page": "CO"})
        detail = picked
    elif kind == "rep_delta":
        rkey = val.lower() if val.lower() in REP_NETWORKS else (choice.get("options") or list(REP_NETWORKS))[0]
        amt = int(choice.get("amount") or 0)
        _apply_delta_with_debt(state["rep"], state["rep_debt"], rkey, amt)
        detail = f"{rkey} {amt:+d}"
    elif kind == "rep_network_note":
        rkey = val or rng.choice(REP_NETWORKS)
        state["notes"].append(f"Contact Rep Network: {rkey}")
        detail = f"Contact Rep: {rkey}"
    elif kind == "aptitude_delta":
        ak = val.lower() if val.lower() in APT_KEYS else "cog"
        amt = int(choice.get("amount") or 5)
        state["aptitudes"][ak] = max(1, int(state["aptitudes"].get(ak, 15)) + amt)
        detail = f"{ak.upper()} {amt:+d}"
    elif kind == "language":
        lang = val or "English"
        if lang not in state["languages"]:
            state["languages"].append(lang)
        detail = f"Language: {lang}"
        cnt = int(choice.get("count") or 1)
        if cnt > 1:
            rem = copy.deepcopy(choice)
            rem["count"] = cnt - 1
            rem["prompt"] = f"Choose or roll {cnt - 1} more extra language(s)"
            state["pending_choices"].insert(0, rem)
    elif kind == "disorder":
        dname = val or "Anxiety"
        _add_trait(state["traits"], f"Mental Disorder ({dname})", level=1)
        detail = f"Mental Disorder ({dname})"
    elif kind == "sleight":
        if "::" in val:
            stype, sname = val.split("::", 1)
        else:
            stype = "Psi-Gamma" if choice.get("scope") == "psi-gamma" else "Psi-Chi"
            sname = val or "Charisma"
        state["sleights"].append({"name": sname, "type": stype})
        detail = f"Sleight ({stype}): {sname}"
        cnt = int(choice.get("count") or 1)
        if cnt > 1:
            rem = copy.deepcopy(choice)
            rem["count"] = cnt - 1
            rem["prompt"] = f"Choose or roll {cnt - 1} more sleight(s)"
            state["pending_choices"].insert(0, rem)
    elif kind == "skill_bonus":
        amt = int(choice.get("amount") or 10)
        target_sk = _normalize_skill_name(val or "Perceive")
        if target_sk.startswith("Know:"):
            kn = target_sk[5:].strip()
            _apply_delta_with_debt(state["know_skills"], state["know_debt"], kn, amt)
        elif choice.get("scope") == "know":
            _apply_delta_with_debt(state["know_skills"], state["know_debt"], target_sk, amt)
        else:
            _apply_delta_with_debt(state["skills"], state["skill_debt"], target_sk, amt)
        detail = f"{target_sk} {amt:+d}"
        cnt = int(choice.get("count") or 1)
        if cnt > 1:
            rem = copy.deepcopy(choice)
            rem["count"] = cnt - 1
            rem["prompt"] = f"Choose {cnt - 1} more skill(s) for {amt:+d}"
            state["pending_choices"].insert(0, rem)
    elif kind in ("replace_skill", "exchange_60_for_skill"):
        if val and val.lower() not in ("skip", "keep"):
            # Format supported: "OldSkill -> NewSkill" or just target
            if "->" in val:
                old_s, new_s = [p.strip() for p in val.split("->", 1)]
                if old_s in state["skills"]:
                    pts = state["skills"].pop(old_s)
                    if choice.get("to_scope") == "know":
                        _apply_delta_with_debt(state["know_skills"], state["know_debt"], new_s.replace("Know:", "").strip(), pts)
                    else:
                        _apply_delta_with_debt(state["skills"], state["skill_debt"], new_s, pts)
                    detail = f"Replaced {old_s} ({pts}) -> {new_s}"
                else:
                    detail = f"Recorded swap request: {val}"
                    state["notes"].append(detail)
            else:
                state["notes"].append(f"{choice.get('prompt')}: {val}")
                detail = val
        else:
            detail = "Kept existing skills"

    state["history"].append({
        "step": choice.get("step", session.current_step),
        "table": "choice",
        "roll": "Chosen" if not auto_roll else "Rolled",
        "title": choice.get("prompt", "Choice"),
        "detail": detail,
    })

    _advance_next_step_or_table(session)
    session.save(update_fields=["current_step", "state", "updated_at"])
    return {"choice": choice, "detail": detail}


def compute_final_sheet(state: dict[str, Any]) -> dict[str, Any]:
    """Compile Step 15 Final Stats, linked-aptitude totals, 80-cap warnings, and Derived Stats."""
    apts = {k: int((state.get("aptitudes") or {}).get(k, 15)) for k in APT_KEYS}
    raw_skills = dict(state.get("skills") or {})
    raw_know = dict(state.get("know_skills") or {})

    # Always include base Fray (REF*2) and Perceive (INT*2)
    final_active: dict[str, dict[str, Any]] = {}
    all_active_names = sorted(set(raw_skills.keys()) | {"Fray", "Perceive"})
    skill_overflows: list[dict[str, Any]] = []
    for sname in all_active_names:
        base_pts = int(raw_skills.get(sname, 0))
        apt_key, mult = SKILL_LINKED_APTITUDE.get(sname, ("cog", 1))
        apt_bonus = apts[apt_key] * mult
        total = base_pts + apt_bonus
        capped = min(80, total)
        excess = max(0, total - 80)
        if excess > 0:
            skill_overflows.append({"skill": sname, "total": total, "excess": excess, "is_know": False})
        final_active[sname] = {
            "raw": base_pts,
            "aptitude": apt_key.upper(),
            "apt_bonus": apt_bonus,
            "total": capped,
            "uncapped_total": total,
        }

    final_know: dict[str, dict[str, Any]] = {}
    for kname, pts in sorted(raw_know.items()):
        apt_bonus = apts["cog"]
        total = int(pts) + apt_bonus
        capped = min(80, total)
        excess = max(0, total - 80)
        if excess > 0:
            skill_overflows.append({"skill": f"Know: {kname}", "total": total, "excess": excess, "is_know": True})
        final_know[kname] = {
            "raw": int(pts),
            "aptitude": "COG",
            "apt_bonus": apt_bonus,
            "total": capped,
            "uncapped_total": total,
        }

    final_rep: dict[str, int] = {}
    rep_overflows: list[dict[str, Any]] = []
    for rkey, val in sorted((state.get("rep") or {}).items()):
        v = int(val)
        if v > 80:
            rep_overflows.append({"rep": rkey, "total": v, "excess": v - 80})
        final_rep[rkey] = min(80, v)

    # Derived stats per EP2 Step 15
    init_val = round((apts["ref"] + apts["int"]) / 5)
    luc = apts["wil"] * 2
    tt = luc // 5
    ir = luc * 2
    psi_trait = next((t for t in (state.get("traits") or []) if t.get("name", "").lower() == "psi"), None)
    infection_rating = int(psi_trait.get("level", 0)) * 10 if psi_trait else 0
    apt_checks = {k: apts[k] * 3 for k in APT_KEYS}

    return {
        "character_name": state.get("character_name") or "Unnamed Lifepath Ego",
        "flex": int(state.get("flex_total", 1)),
        "flex_rerolls_remaining": int(state.get("flex_rerolls_remaining", 0)),
        "aptitudes": apts,
        "aptitude_checks": apt_checks,
        "derived": {
            "initiative": init_val,
            "lucidity": luc,
            "trauma_threshold": tt,
            "insanity_rating": ir,
            "infection_rating": infection_rating,
            "starting_stress": int(state.get("starting_stress", 0)),
        },
        "active_skills": final_active,
        "know_skills": final_know,
        "specializations": list(state.get("specializations") or []),
        "reputations": final_rep,
        "skill_overflows": skill_overflows,
        "rep_overflows": rep_overflows,
        "skill_debt": dict(state.get("skill_debt") or {}),
        "know_debt": dict(state.get("know_debt") or {}),
        "rep_debt": dict(state.get("rep_debt") or {}),
        "traits": list(state.get("traits") or []),
        "sleights": list(state.get("sleights") or []),
        "strain": state.get("strain") or "",
        "languages": list(state.get("languages") or []),
        "motivations": list(state.get("motivations") or state.get("motivations_pool", [])[:3]),
        "motivations_pool": list(state.get("motivations_pool") or []),
        "morph": dict(state.get("morph") or {}),
        "gear": list(state.get("gear") or []),
        "gear_pack_campaign": state.get("gear_pack_campaign") or "",
        "gear_pack_profession": state.get("gear_pack_profession") or "",
        "age_label": state.get("age_label") or "",
        "background": f"{state.get('background_group', '')} — {state.get('background_sub', '')}".strip(" —"),
        "career": f"{state.get('career_group', '')} — {state.get('career_sub', '')}".strip(" —"),
        "interest": state.get("interest") or "",
        "faction": state.get("faction") or "",
        "notes": list(state.get("notes") or []),
    }


def apply_step15_gear_packs(
    session: LifepathSession,
    *,
    campaign_pack_title: str | None = None,
    profession_pack_title: str | None = None,
    selected_motivations: list[str] | None = None,
) -> dict[str, Any]:
    """Select Campaign & Profession Gear Packs and up to 3 Motivations at Step 15."""
    state = session.state
    is_synth = (state.get("morph") or {}).get("category", "").lower() == "synthmorph"

    def _apply_pack(slug: str, title: str, state_key: str) -> None:
        entry = LifepathEntry.objects.filter(table__slug=slug, title__iexact=title.strip(), is_active=True).first()
        if entry is None:
            raise ValueError(f"Gear pack '{title}' not found in '{slug}'.")
        # Remove previously chosen items from this pack kind
        state["gear"] = [g for g in (state.get("gear") or []) if g.get("pack_source") != state_key]
        eff = entry.effects or {}
        items = copy.deepcopy(eff.get("gear") or [])
        if is_synth and eff.get("synthmorph_alt_gear"):
            alt_items = copy.deepcopy(eff["synthmorph_alt_gear"])
            # Keep non-starred items and append synthmorph alternatives
            items = [it for it in items if not str(it.get("name", "")).endswith("*")] + alt_items
        for it in items:
            it["pack_source"] = state_key
            state["gear"].append(it)
        state[state_key] = entry.title

    if campaign_pack_title:
        _apply_pack("gear-pack-campaign", campaign_pack_title, "gear_pack_campaign")
    if profession_pack_title:
        _apply_pack("gear-pack-profession", profession_pack_title, "gear_pack_profession")
    if selected_motivations is not None:
        state["motivations"] = [m.strip() for m in selected_motivations if m.strip()][:3]

    session.save(update_fields=["state", "updated_at"])
    return compute_final_sheet(state)


def reallocate_step15_overflow(
    session: LifepathSession,
    *,
    source_name: str,
    target_name: str,
    amount: int | None = None,
) -> dict[str, Any]:
    """Move excess points above 80 from an overflowed skill/rep to another skill/rep."""
    state = session.state
    sheet = compute_final_sheet(state)
    # Rep overflow check
    rep_ov = next((o for o in sheet["rep_overflows"] if o["rep"].lower() == source_name.lower()), None)
    if rep_ov:
        pts = min(rep_ov["excess"], int(amount or rep_ov["excess"]))
        tgt = target_name.lower().strip()
        if tgt not in REP_NETWORKS:
            raise ValueError(f"Unknown rep network '{target_name}'.")
        state["rep"][rep_ov["rep"]] = int(state["rep"].get(rep_ov["rep"], 0)) - pts
        state["rep"][tgt] = int(state["rep"].get(tgt, 0)) + pts
        session.save(update_fields=["state", "updated_at"])
        return compute_final_sheet(state)

    sk_ov = next((o for o in sheet["skill_overflows"] if o["skill"].lower() == source_name.lower()), None)
    if not sk_ov:
        raise ValueError(f"'{source_name}' has no overflow points above 80.")
    pts = min(sk_ov["excess"], int(amount or sk_ov["excess"]))
    if sk_ov["is_know"]:
        src_k = sk_ov["skill"].replace("Know:", "").strip()
        tgt_k = target_name.replace("Know:", "").strip()
        state["know_skills"][src_k] = int(state["know_skills"].get(src_k, 0)) - pts
        state["know_skills"][tgt_k] = int(state["know_skills"].get(tgt_k, 0)) + pts
    else:
        src_s = sk_ov["skill"]
        state["skills"][src_s] = int(state["skills"].get(src_s, 0)) - pts
        if target_name.startswith("Know:"):
            tgt_k = target_name.replace("Know:", "").strip()
            state["know_skills"][tgt_k] = int(state["know_skills"].get(tgt_k, 0)) + pts
        else:
            state["skills"][target_name] = int(state["skills"].get(target_name, 0)) + pts

    session.save(update_fields=["state", "updated_at"])
    return compute_final_sheet(state)


def finalize_and_export_session(
    session: LifepathSession,
    *,
    user=None,
    character_name: str | None = None,
    create_dossier: bool = False,
) -> tuple[LifepathSession, GeneratedCharacter | None]:
    """Mark session completed and export/save to GeneratedCharacter(source_system='life_path') when user exists."""
    state = session.state
    if character_name and character_name.strip():
        clean_name = character_name.strip()[:160]
        state["character_name"] = clean_name
        session.character_name = clean_name
    if not state.get("motivations"):
        state["motivations"] = list((state.get("motivations_pool") or [])[:3])

    sheet = compute_final_sheet(state)
    effective_user = user if (user is not None and getattr(user, "is_authenticated", False)) else session.user

    gen_char = session.generated_character
    if effective_user is not None:
        # Build MeshNet-compatible raw_data + full lifePath payload
        raw_data: dict[str, Any] = {
            "pointBuy": {
                "name": f"i_{sheet['character_name']}",
                "concept": f"i_{sheet['career'] or sheet['background']}",
                "egoType": f"i_{state.get('background_group') or 'Transhuman'}",
                "description": f"h_Generated via EP2e Life Path ({sheet['background']} · {sheet['career']} · {sheet['faction']})",
                "aptitudes": dict(sheet["aptitudes"]),
                "flexPoints": sheet["flex"],
                "skills": {k: v["raw"] for k, v in sheet["active_skills"].items() if v["raw"] > 0},
                "knowSkills": {k: v["raw"] for k, v in sheet["know_skills"].items()},
                "reputations": {
                    f"rep_{k}": {"points": v, "isTracked": True, "design": {"uid": f"rep:ep-crb:{k}"}}
                    for k, v in sheet["reputations"].items()
                },
                "languages": {f"lang_{i}": {"customName": lang} for i, lang in enumerate(sheet["languages"])},
                "motivations": {
                    f"mot_{i}": {
                        "cause": f"i_{mot.lstrip('+-–− ').strip()}",
                        "supportCause": not mot.strip().startswith(("-", "–", "−")),
                    }
                    for i, mot in enumerate(sheet["motivations"])
                },
                "morphs": (
                    {"morph_1": {"customName": sheet["morph"].get("name")}}
                    if sheet["morph"].get("name")
                    else {}
                ),
                "egoTraits": {
                    f"tr_{i}": {"customName": f"{t['name']} (Lvl {t['level']})"}
                    for i, t in enumerate(sheet["traits"])
                },
                "sleights": {
                    f"sl_{i}": {"customName": f"{s['name']} ({s['type']})"}
                    for i, s in enumerate(sheet["sleights"])
                },
                "skillPacks": {
                    k: {"customName": v}
                    for k, v in (
                        ("background", state.get("background_sub")),
                        ("career", state.get("career_sub")),
                        ("interest", state.get("interest")),
                        ("faction", state.get("faction")),
                    )
                    if v
                },
            },
            "lifePath": {
                "session_id": session.pk,
                "sheet": sheet,
                "history": state.get("history") or [],
            },
        }
        summary = {
            "character_name": sheet["character_name"],
            "concept": f"{sheet['background']} · {sheet['career']}".strip(" ·"),
            "ego_type": state.get("background_group") or "Transhuman",
            "aptitudes": sheet["aptitudes"],
            "flex": sheet["flex"],
            "skill_packs": {
                k: v
                for k, v in (
                    ("background", state.get("background_sub")),
                    ("career", state.get("career_sub")),
                    ("interest", state.get("interest")),
                    ("faction", state.get("faction")),
                )
                if v
            },
            "morphs": [sheet["morph"]["name"]] if sheet["morph"].get("name") else [],
            "traits": [f"{t['name']} (Lvl {t['level']})" for t in sheet["traits"]],
            "sleights": [f"{s['name']} ({s['type']})" for s in sheet["sleights"]],
            "reputations": sheet["reputations"],
            "languages": sheet["languages"],
            "motivations": sheet["motivations"],
            "skill_count": len(sheet["active_skills"]) + len(sheet["know_skills"]),
            "derived": sheet["derived"],
        }
        dossier = session.dossier
        if create_dossier and dossier is None:
            dossier = CharacterDossier.objects.create(
                user=effective_user,
                discord_owner_id=session.discord_user_id,
                character_name=sheet["character_name"],
            )
            session.dossier = dossier

        with transaction.atomic():
            if gen_char is None:
                gen_char = GeneratedCharacter.objects.create(
                    user=effective_user,
                    dossier=dossier,
                    character_name=sheet["character_name"],
                    source_system=GeneratedCharacter.SOURCE_LIFE_PATH,
                    raw_data=raw_data,
                    summary=summary,
                    status=GeneratedCharacter.STATUS_COMPLETED,
                    completed_at=timezone.now(),
                )
            else:
                gen_char.character_name = sheet["character_name"]
                gen_char.dossier = dossier
                gen_char.source_system = GeneratedCharacter.SOURCE_LIFE_PATH
                gen_char.raw_data = raw_data
                gen_char.summary = summary
                gen_char.status = GeneratedCharacter.STATUS_COMPLETED
                gen_char.completed_at = timezone.now()
                gen_char.save()
            session.user = effective_user
            session.generated_character = gen_char

    session.status = LifepathSession.STATUS_COMPLETED
    session.current_step = 15
    session.save()
    return session, gen_char


def render_lifepath_summary_markdown(session: LifepathSession) -> str:
    """Render a clean portable Markdown summary for a LifepathSession."""
    sheet = compute_final_sheet(session.state)
    lines = [
        f"# {sheet['character_name']} — EP2e Life Path",
        "",
        f"- **Background:** {sheet['background'] or '—'}",
        f"- **Age:** {sheet['age_label'] or '—'}",
        f"- **Career:** {sheet['career'] or '—'}",
        f"- **Interest:** {sheet['interest'] or '—'}",
        f"- **Faction:** {sheet['faction'] or '—'}",
        f"- **Morph:** {sheet['morph'].get('name') or '—'}",
        f"- **Flex:** {sheet['flex']} (Rerolls unused: {sheet['flex_rerolls_remaining']})",
        "",
        "## Aptitudes & Derived Stats",
        "| COG | INT | REF | SAV | SOM | WIL | INIT | LUC | TT | IR |",
        "|---|---|---|---|---|---|---|---|---|---|",
        "| " + " | ".join(str(sheet["aptitudes"][k]) for k in APT_KEYS) + f" | {sheet['derived']['initiative']} | {sheet['derived']['lucidity']} | {sheet['derived']['trauma_threshold']} | {sheet['derived']['insanity_rating']} |",
        "",
        "## Active Skills",
        *[f"- **{k}:** {v['total']} (base {v['raw']} + {v['aptitude']} {v['apt_bonus']})" for k, v in sheet["active_skills"].items()],
        "",
        "## Know Skills",
        *[f"- **Know: {k}:** {v['total']} (base {v['raw']} + COG {v['apt_bonus']})" for k, v in sheet["know_skills"].items()],
        "",
        "## Reputations",
        *[f"- **{k}:** {v}" for k, v in sheet["reputations"].items()],
        "",
        "## Traits & Sleights",
        *[f"- Trait: {t['name']} (Level {t['level']})" for t in sheet["traits"]],
        *[f"- Sleight: {s['name']} ({s['type']})" for s in sheet["sleights"]],
        "",
        "## Motivations & Languages",
        f"- **Languages:** {', '.join(sheet['languages']) or '—'}",
        f"- **Motivations:** {', '.join(sheet['motivations']) or '—'}",
        "",
        "## Starting Gear",
        f"- **Campaign Pack:** {sheet['gear_pack_campaign'] or '—'}",
        f"- **Profession Pack:** {sheet['gear_pack_profession'] or '—'}",
        *[f"- {g.get('name', g)}" for g in sheet["gear"]],
    ]
    return "\n".join(lines) + "\n"
