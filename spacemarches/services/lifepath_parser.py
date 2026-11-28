"""Parse docs/ep2e-lifepath-character-creation.md into adjustable LifepathTable / LifepathEntry fixtures."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_RANGE_RE = re.compile(r"^(\d+)\s*[–-]\s*(\d+)\s*(.*)$")
_SINGLE_RE = re.compile(r"^(\d+)\s+(.*)$")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")

KNOWN_REPS = ("@-rep", "c-rep", "f-rep", "g-rep", "i-rep", "r-rep", "x-rep")
KNOWN_APTS = ("COG", "INT", "REF", "SAV", "SOM", "WIL")

TRAIT_NO_DEFAULT_LEVEL = {"Psi", "Resources"}


def _slugify_simple(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return cleaned or "entry"


def _strip_md(text: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", text)
    text = _BOLD_RE.sub(r"\1", text)
    text = _CODE_SPAN_RE.sub(r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_die_token(val: str, die_type: str) -> tuple[int | None, int | None]:
    raw = val.strip().replace("—", "-").replace("–", "-")
    if not raw or raw == "-":
        return None, None
    # Strip trailing + like "9+"
    raw_clean = raw.rstrip("+").strip()
    if "-" in raw_clean:
        lo_s, hi_s = [p.strip() for p in raw_clean.split("-", 1)]
        lo = int(lo_s)
        hi = int(hi_s)
    else:
        lo = int(raw_clean)
        hi = 10 if raw.endswith("+") else lo
    if die_type in ("d10", "d10_pair"):
        if lo == 0:
            lo = 10
        if hi == 0:
            hi = 10
    return lo, hi


def _split_md_table(lines: list[str]) -> list[tuple[list[str], list[list[str]]]]:
    """Extract all markdown tables inside a slice of lines as (headers, rows)."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*[-:]+", lines[i + 1].strip()):
            headers = [c.strip() for c in line.strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            tables.append((headers, rows))
        else:
            i += 1
    return tables


def _extract_sections(md_text: str) -> dict[str, list[str]]:
    """Split markdown by heading line text into sections preserving order."""
    sections: dict[str, list[str]] = {}
    current_key = "_preamble"
    sections[current_key] = []
    for line in md_text.splitlines():
        if line.startswith("#"):
            current_key = line.strip()
            if current_key not in sections:
                sections[current_key] = []
        else:
            sections[current_key].append(line)
    return sections


def _parse_morph_cell(cell: str) -> dict[str, Any]:
    clean = _strip_md(cell)
    if not clean:
        return {}
    if "Roll on Uplift Biomorphs" in clean:
        return {"sub_rolls": [{"table_slug": "morph-uplift-biomorphs", "reason": "Starting Uplift Morph"}]}
    if "Roll on" in clean and "Morph" in clean:
        return {"sub_rolls": [{"table_slug": "morph-type", "reason": "Starting Morph"}]}
    # Check if 1d10 weighted list like "1–4 Splicer, 5–8 Bouncer, 9–0 Exalt"
    parts = [p.strip() for p in clean.split(",") if p.strip()]
    morph_table: list[dict[str, Any]] = []
    for part in parts:
        m = re.match(r"^(\d+(?:[–-]\d+)?)\s+(.+)$", part)
        if m:
            lo, hi = _parse_die_token(m.group(1), "d10")
            morph_table.append({"roll_min": lo, "roll_max": hi, "morph": m.group(2).strip()})
    if morph_table:
        return {"morph_d10": morph_table}
    return {"morph": clean}


def _parse_package_modifiers(text: str, *, default_step_hint: str = "") -> dict[str, Any]:
    """Parse comma-separated package grants (e.g. Rep, Traits, Languages, Aptitudes, Skills)."""
    effects: dict[str, Any] = {}
    raw = _strip_md(text)
    if not raw or raw == "—":
        return effects

    # Split top-level commas (respecting parentheses)
    tokens: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            tok = "".join(buf).strip()
            if tok:
                tokens.append(tok)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        tokens.append(tail)

    skills: dict[str, int] = {}
    know_skills: dict[str, int] = {}
    rep: dict[str, int] = {}
    aptitudes: dict[str, int] = {}
    traits: list[dict[str, Any]] = []
    choices: list[dict[str, Any]] = []
    sub_rolls: list[dict[str, Any]] = []
    notes: list[str] = []

    for tok in tokens:
        # Flex e.g. "Ego Flex 1"
        m_flex = re.match(r"^Ego Flex\s+([+-]?\d+)$", tok, re.I)
        if m_flex:
            effects["flex"] = effects.get("flex", 0) + int(m_flex.group(1))
            continue

        # Aptitude e.g. "COG +5" or "+5 WIL"
        m_apt = re.match(r"^(COG|INT|REF|SAV|SOM|WIL)\s*([+-]\d+)$", tok)
        if m_apt:
            apt = m_apt.group(1).lower()
            aptitudes[apt] = aptitudes.get(apt, 0) + int(m_apt.group(2))
            continue

        # Sleights e.g. "4 psi sleights (random or choose)"
        m_sleight = re.match(r"^(\d+)\s+psi\s+sleights?", tok, re.I)
        if m_sleight:
            cnt = int(m_sleight.group(1))
            effects["sleight_count"] = effects.get("sleight_count", 0) + cnt
            choices.append({
                "id": f"sleights_{len(choices)+1}",
                "kind": "sleight",
                "count": cnt,
                "scope": "any_psi",
                "allow_roll": True,
                "prompt": f"Choose or roll {cnt} psi sleight(s)",
            })
            continue

        # Languages e.g. "2 languages of your choice"
        m_lang = re.match(r"^(\d+)\s+languages?(?:\s+of your choice)?$", tok, re.I)
        if m_lang:
            cnt = int(m_lang.group(1))
            choices.append({
                "id": f"languages_{len(choices)+1}",
                "kind": "language",
                "count": cnt,
                "allow_roll": True,
                "prompt": f"Choose or roll {cnt} extra language(s)",
            })
            continue

        # Traits e.g. "Resources (Level 2) trait" or "Mental Disorder [Choose One] trait"
        if tok.lower().endswith(" trait") or " trait (" in tok.lower():
            t_clean = re.sub(r"\s+trait.*$", "", tok, flags=re.I).strip()
            level = None
            m_lvl = re.search(r"\(([^)]*Level\s*(\d+)[^)]*)\)", t_clean, re.I)
            if m_lvl:
                level = int(m_lvl.group(2))
                inner = re.sub(r",?\s*Level\s*\d+", "", m_lvl.group(1), flags=re.I).strip(" ,")
                base_name = re.sub(r"\s*\([^)]*\)", "", t_clean).strip()
                t_name = f"{base_name} ({inner})" if inner else base_name
            else:
                t_name = t_clean
            if "[Choose One]" in t_name and "Mental Disorder" in t_name:
                choices.append({
                    "id": f"disorder_{len(choices)+1}",
                    "kind": "disorder",
                    "count": 1,
                    "allow_roll": True,
                    "prompt": "Choose or roll 1 Mental Disorder trait",
                })
            else:
                traits.append({"name": t_name, "level": level or (1 if t_name in TRAIT_NO_DEFAULT_LEVEL else 2)})
            continue

        # Reputation e.g. "c-rep 20" or "@-rep 10"
        m_rep = re.match(r"^([@cfgirx]-rep)\s+(\d+)$", tok, re.I)
        if m_rep:
            rkey = m_rep.group(1).lower()
            rep[rkey] = rep.get(rkey, 0) + int(m_rep.group(2))
            continue

        # Know skill with 'or': e.g. "Know: Asteroid Mining 40 or Know: Gas Mining 40"
        if " or " in tok:
            m_or = re.match(r"^(.+?)\s+(\d+)\s+or\s+(.+?)\s+(\d+)$", tok)
            if m_or:
                opt_a = m_or.group(1).strip()
                val_a = int(m_or.group(2))
                opt_b = m_or.group(3).strip()
                val_b = int(m_or.group(4))
                choices.append({
                    "id": f"pick_skill_{len(choices)+1}",
                    "kind": "skill_option",
                    "options": [
                        {"skill": opt_a, "points": val_a, "is_know": opt_a.startswith("Know:")},
                        {"skill": opt_b, "points": val_b, "is_know": opt_b.startswith("Know:")},
                    ],
                    "prompt": f"Choose {opt_a} {val_a} or {opt_b} {val_b}",
                })
                continue

        # Standard Know skill: "Know: Asteroid Mining 60"
        m_know = re.match(r"^Know:\s*(.+?)\s+(\d+)$", tok)
        if m_know:
            kname = m_know.group(1).strip()
            know_skills[kname] = know_skills.get(kname, 0) + int(m_know.group(2))
            continue

        # Survival (Navigate) 30 (40) or Skill (Spec) X (Y)
        m_spec_sk = re.match(r"^([A-Za-z][A-Za-z\s:/&-]+?)\s*\(([^)]+)\)\s*(\d+)\s*\((\d+)\)$", tok)
        if m_spec_sk:
            sname = m_spec_sk.group(1).strip()
            spec_name = m_spec_sk.group(2).strip()
            base_v = int(m_spec_sk.group(3))
            skills[sname] = skills.get(sname, 0) + base_v
            effects.setdefault("specializations", []).append({"skill": sname, "specialization": spec_name})
            continue

        # Language note like "Indian Language", "Mandarin language", "English language"
        m_lang_named = re.match(r"^([A-Za-z]+)\s+language$", tok, re.I)
        if m_lang_named:
            lang_name = m_lang_named.group(1).strip()
            effects.setdefault("languages", []).append(lang_name)
            continue

        # Standard Active skill: "Hardware: Robotics 50" or "Guns 30" or "Exotic Skill: Animal Handling 40"
        m_skill = re.match(r"^([A-Za-z][A-Za-z\s:/&-]+?)\s+(\d+)$", tok)
        if m_skill:
            sname = m_skill.group(1).strip()
            # Normalize accidental "Pilot: Spacecraft" -> "Pilot: Space" only if needed, keep clean
            skills[sname] = skills.get(sname, 0) + int(m_skill.group(2))
            continue

        notes.append(tok)

    if skills:
        effects["skills"] = skills
    if know_skills:
        effects["know_skills"] = know_skills
    if rep:
        effects["rep"] = rep
    if aptitudes:
        effects["aptitudes"] = aptitudes
    if traits:
        effects["traits"] = traits
    if choices:
        effects["choices"] = choices
    if sub_rolls:
        effects["sub_rolls"] = sub_rolls
    if notes:
        effects["notes"] = notes
    return effects


def _parse_event_effects(result_text: str) -> dict[str, Any]:
    """Parse natural-language event result text into structured mechanical effects."""
    clean = _strip_md(result_text)
    effects: dict[str, Any] = {}
    skills: dict[str, int] = {}
    know_skills: dict[str, int] = {}
    rep: dict[str, int] = {}
    aptitudes: dict[str, int] = {}
    traits: list[dict[str, Any]] = []
    choices: list[dict[str, Any]] = []
    sub_rolls: list[dict[str, Any]] = []
    motivations: list[str] = []
    gear: list[dict[str, Any]] = []
    flags: dict[str, Any] = {}

    # 1. Step skips & forced interest & extra rolls
    if "skip Step 7" in clean or "Skip Step 7" in clean:
        flags.setdefault("skip_steps", []).append(7)
    if "skip Step 12" in clean or "Skip Step 12" in clean:
        flags.setdefault("skip_steps", []).append(12)
    if "must take the Async path in Step 10" in clean:
        flags["force_interest"] = "Async"
    if "Roll an additional time on the 7.0 Pre-Fall Event table" in clean:
        flags["extra_prefall_rolls"] = 1
    if "Start play with 10 points of stress" in clean:
        flags["starting_stress"] = 10

    # 2. Flex changes
    m_gain_flex = re.search(r"(?:Gain|\+)\s*([12])\s*ego Flex", clean, re.I)
    if m_gain_flex:
        effects["flex"] = effects.get("flex", 0) + int(m_gain_flex.group(1))
    m_lose_flex = re.search(r"Lose\s*([12])\s*ego Flex", clean, re.I)
    if m_lose_flex:
        effects["flex"] = effects.get("flex", 0) - int(m_lose_flex.group(1))

    # 3. Aptitude changes
    for m in re.finditer(r"Increase\s+(?:your\s+)?(COG|INT|REF|SAV|SOM|WIL)\s+by\s+(\d+)", clean):
        k = m.group(1).lower()
        aptitudes[k] = aptitudes.get(k, 0) + int(m.group(2))
    for m in re.finditer(r"Reduce\s+(?:your\s+)?(COG|INT|REF|SAV|SOM|WIL)\s+by\s+(\d+)", clean):
        k = m.group(1).lower()
        aptitudes[k] = aptitudes.get(k, 0) - int(m.group(2))
    if "Increase one aptitude by 5 and reduce another by 5" in clean:
        sub_rolls.append({"table_slug": "_apt_swap_5", "kind": "aptitude_1d6_plus_minus", "reason": "Reinvent (+5 one / -5 another)"})
    elif "Reduce one aptitude by 5" in clean:
        sub_rolls.append({"table_slug": "_apt_1d6_minus_5", "kind": "aptitude_1d6_minus", "reason": "Aptitude -5 (1d6)"})
    elif "Increase one aptitude by 5" in clean and "Roll 1d10" in clean:
        sub_rolls.append({"table_slug": "_apt_1d10_plus_5", "kind": "aptitude_1d10_plus", "reason": "Aptitude +5 (1d10)"})
    elif "Increase one aptitude of your choice by 5" in clean or "increase any one aptitude by 5" in clean.lower():
        choices.append({"id": "pick_apt_plus_5", "kind": "aptitude_delta", "amount": 5, "prompt": "Choose 1 aptitude to increase by +5"})

    # 4. Follow-up table rolls
    if "Roll on the Story Event" in clean or "roll on the Story Event" in clean:
        sub_rolls.append({"table_slug": "story-event", "reason": "Story Event"})
    if "Roll on the Crime Event" in clean or "Roll once on the Crime Event" in clean:
        sub_rolls.append({"table_slug": "crime-event", "reason": "Crime Event"})
    if "Roll on the Firewall Event" in clean:
        sub_rolls.append({"table_slug": "firewall-event", "reason": "Firewall Event"})
    if "Roll on the Gatecrashing Event" in clean:
        sub_rolls.append({"table_slug": "gatecrashing-event", "reason": "Gatecrashing Event"})
    if "Random Morph" in clean:
        ignore: list[str] = []
        if "ignore pods and uplifts" in clean.lower() or "re-roll pods and uplifts" in clean.lower():
            ignore = ["pod", "uplift"]
        elif "ignore pods" in clean.lower():
            ignore = ["pod"]
        sub_rolls.append({"table_slug": "morph-type", "ignore": ignore, "reason": "Random Morph replacement"})
    if "Table 11.0 Faction" in clean or "Faction table" in clean:
        sub_rolls.append({"table_slug": "ref-faction", "reason": "Random Faction (story hook)"})
    if "Rep Networks" in clean:
        choices.append({"id": "pick_rep_network", "kind": "rep_network_note", "allow_roll": True, "prompt": "Choose or roll Rep Network for Contact"})

    # 5. Sleights / Psi / Sub-strains
    if "Watts-MacLeod" in clean and "Async" not in clean and "Psi" not in clean:
        sub_rolls.append({"table_slug": "watts-macleod-strains", "reason": "Watts-MacLeod Sub-Strain"})
    if "Roll on the Sleights tables" in clean:
        sub_rolls.append({"table_slug": "sleight-type", "reason": "Random Sleight (Psi-Opener)"})
    if "Roll for your new faction on Table 11.0" in clean:
        sub_rolls.append({"table_slug": "faction", "reason": "New Faction Allegiance (+10 Know: Interests)"})
    m_psi_lvl = re.search(r"Gain the Psi \(Level (\d+)\) trait", clean)
    if m_psi_lvl:
        traits.append({"name": "Psi", "level": int(m_psi_lvl.group(1))})
    m_chi = re.search(r"(\d+)\s+psi-chi sleights?", clean, re.I)
    if m_chi:
        cnt = int(m_chi.group(1))
        choices.append({"id": "pick_chi_sleight", "kind": "sleight", "count": cnt, "scope": "psi-chi", "allow_roll": True, "prompt": f"Choose or roll {cnt} Psi-Chi sleight(s)"})
    m_gam = re.search(r"(\d+)\s+psi-gamma sleights?", clean, re.I)
    if m_gam:
        cnt = int(m_gam.group(1))
        choices.append({"id": "pick_gamma_sleight", "kind": "sleight", "count": cnt, "scope": "psi-gamma", "allow_roll": True, "prompt": f"Choose or roll {cnt} Psi-Gamma sleight(s)"})
    if "Gain one extra sleight" in clean or "Gain 1 extra sleight" in clean:
        choices.append({"id": "pick_extra_sleight", "kind": "sleight", "count": 1, "scope": "any_psi", "allow_roll": True, "prompt": "Choose or roll 1 extra sleight"})

    # 6. Traits (including Resources loss conditional!)
    if "Gain either the Edited Memories" in clean:
        choices.append({
            "id": "pick_trait_ed_rb",
            "kind": "trait_option",
            "options": [
                {"name": "Edited Memories", "level": 2},
                {"name": "Restricted Behavior", "level": 2},
            ],
            "prompt": "Choose Edited Memories or Restricted Behavior (Level 2)",
        })
    elif re.search(r"(?:Lose|Reduce(?: your)?) (?:1|one) levels? of (?:the )?Resources|Reduce your Resources trait by (?:1|one) level", clean, re.I):
        alt: dict[str, Any] = {"kind": "note", "text": clean}
        if "gain the Debt trait" in clean:
            alt = {"kind": "trait", "name": "Debt", "level": 1}
        elif "−10 c-rep" in clean or "lose 10 c-rep" in clean:
            alt = {"kind": "rep", "rep": "c-rep", "amount": -10}
        elif "lose 10 x-rep" in clean:
            alt = {"kind": "rep", "rep": "x-rep", "amount": -10}
        elif "10 c-rep or g-rep" in clean:
            alt = {"kind": "rep_choice", "options": ["c-rep", "g-rep"], "amount": -10}
        elif "one rep score of your choice" in clean:
            alt = {"kind": "rep_choice", "options": list(KNOWN_REPS), "amount": -10}
        traits.append({"name": "Resources", "delta": -1, "fallback": alt})
    else:
        for m in re.finditer(r"Gain(?: the)?\s+([A-Z][A-Za-zÀ-ÿ0-9\s/'\-–:]+?(?:\s*\([^)]+\))?)\s+trait", clean):
            raw_t = m.group(1).strip()
            if raw_t.startswith("Psi (Level"):
                continue
            level = None
            m_lvl = re.search(r"\(([^)]*Level\s*(\d+)[^)]*)\)", raw_t, re.I)
            if m_lvl:
                level = int(m_lvl.group(2))
                inner = re.sub(r",?\s*Level\s*\d+", "", m_lvl.group(1), flags=re.I).strip(" ,")
                base = re.sub(r"\s*\([^)]*\)", "", raw_t).strip()
                tname = f"{base} ({inner})" if inner else base
            else:
                tname = raw_t
            if tname == "Resource":
                tname = "Resources"
            traits.append({"name": tname, "level": level or (1 if tname in TRAIT_NO_DEFAULT_LEVEL else 2)})
        if "random Negative Morph trait" in clean.lower():
            sub_rolls.append({"table_slug": "negative-morph-traits", "reason": "Negative Morph Trait"})
        if "random Positive Ego trait" in clean.lower():
            sub_rolls.append({"table_slug": "positive-ego-traits", "reason": "Positive Ego Trait"})

    # 7. Languages
    if any(p in clean for p in ("Learn an additional language", "Gain a language", "Gain 1 language", "Gain an extra language")):
        choices.append({"id": "pick_language", "kind": "language", "count": 1, "allow_roll": True, "prompt": "Choose or roll 1 additional language"})

    # 8. Rep changes (explicit & choice)
    # Check specific "or" choices first e.g. "−10 to either c-rep or r-rep" or "−10 @-rep, g-rep, or c-rep" or "lose 10 c-rep or @-rep"
    m_rep_or = re.search(r"([+−-])(\d+)\s+(?:to\s+(?:either\s+)?)?([@cfgirx]-rep(?:\s*,\s*[@cfgirx]-rep)*(?:\s*,?\s*or\s*[@cfgirx]-rep))", clean, re.I)
    if m_rep_or:
        sign = -1 if m_rep_or.group(1) in ("-", "−") else 1
        amt = sign * int(m_rep_or.group(2))
        opts = re.findall(r"[@cfgirx]-rep", m_rep_or.group(3).lower())
        choices.append({
            "id": f"rep_choice_{len(choices)+1}",
            "kind": "rep_delta",
            "amount": amt,
            "options": opts,
            "prompt": f"Choose rep network for {amt:+d}",
        })
    elif re.search(r"lose\s+(\d+)\s+([@cfgirx]-rep)\s+or\s+([@cfgirx]-rep)", clean, re.I):
        m_lr = re.search(r"lose\s+(\d+)\s+([@cfgirx]-rep)\s+or\s+([@cfgirx]-rep)", clean, re.I)
        amt = -int(m_lr.group(1))
        choices.append({
            "id": f"rep_choice_{len(choices)+1}",
            "kind": "rep_delta",
            "amount": amt,
            "options": [m_lr.group(2).lower(), m_lr.group(3).lower()],
            "prompt": f"Choose rep network for {amt:+d}",
        })
    else:
        for m in re.finditer(r"([+−-])(\d+)\s+([@cfgirx]-rep)\b", clean, re.I):
            sign = -1 if m.group(1) in ("-", "−") else 1
            rkey = m.group(3).lower()
            rep[rkey] = rep.get(rkey, 0) + sign * int(m.group(2))

    # Fixed "+10 g-rep, but lose 10 c-rep or @-rep" already gives +10 g-rep? Handle when both appear:
    if re.search(r"\+10 g-rep, but lose 10 c-rep or @-rep", clean):
        rep["g-rep"] = rep.get("g-rep", 0) + 10
    if "−10 r-rep or c-rep" in clean and not any(c.get("kind") == "rep_delta" for c in choices):
        choices.append({"id": "rep_choice_rc", "kind": "rep_delta", "amount": -10, "options": ["r-rep", "c-rep"], "prompt": "Choose -10 r-rep or c-rep"})
    if "rep score most appropriate to your faction" in clean:
        choices.append({"id": f"rep_fac_{len(choices)+1}", "kind": "rep_delta", "amount": -10 if ("−10" in clean or "-10" in clean) else 10, "options": list(KNOWN_REPS), "prompt": "Choose faction-appropriate rep score"})
    elif "rep score you don't have" in clean:
        choices.append({"id": f"rep_new_{len(choices)+1}", "kind": "rep_delta", "amount": 10, "options": list(KNOWN_REPS), "prompt": "Choose +10 to a rep score you don't have"})
    m_any_rep = re.search(r"([+−-])(\d+)\s+to\s+(?:a|one)\s+rep score of your choice", clean, re.I)
    if m_any_rep:
        sign = -1 if m_any_rep.group(1) in ("-", "−") else 1
        amt = sign * int(m_any_rep.group(2))
        choices.append({"id": f"rep_any_{len(choices)+1}", "kind": "rep_delta", "amount": amt, "options": list(KNOWN_REPS), "prompt": f"Choose any rep network for {amt:+d}"})

    # 9. Skills & Know skills
    # Special choice sentences first
    if "Exotic Skill" in clean and "of your choice at 30" in clean:
        choices.append({"id": "pick_exotic_30", "kind": "skill_bonus", "amount": 30, "scope": "exotic", "allow_roll": True, "prompt": "Choose or roll 1 Exotic Skill at 30"})
    elif "free specialization" in clean.lower() or "one specialization" in clean.lower():
        choices.append({"id": "free_spec", "kind": "specialization", "prompt": "Choose 1 free specialization in a skill you possess"})
    elif "Gain the Interface (Pandora Gates) specialization" in clean:
        choices.append({"id": "spec_interface_pg", "kind": "fixed_specialization", "skill": "Interface", "spec": "Pandora Gates"})
    elif "Gain the Program (Pandora Gates) specialization" in clean:
        choices.append({"id": "spec_program_pg", "kind": "fixed_specialization", "skill": "Program", "spec": "Pandora Gates"})
    elif "Intimidation specialization" in clean:
        choices.append({"id": "spec_provoke_intim", "kind": "fixed_specialization", "skill": "Provoke", "spec": "Intimidation"})
        if "Increase Provoke by 5" in clean:
            skills["Provoke"] = skills.get("Provoke", 0) + 5
    elif "Exotic Skill in a field of your choice" in clean:
        choices.append({"id": "pick_exotic_20", "kind": "skill_bonus", "amount": 20, "scope": "exotic", "allow_roll": True, "prompt": "Choose or roll +20 Exotic Skill"})
    elif "Exotic Skill: [Bow, Garrote, or Throwing Knives]" in clean:
        choices.append({"id": "pick_exotic_assassin", "kind": "skill_option", "options": [{"skill": "Exotic Skill: Bow", "points": 10}, {"skill": "Exotic Skill: Monowire Garrote", "points": 10}, {"skill": "Exotic Skill: Throwing Knives", "points": 10}], "prompt": "Choose +10 Bow, Garrote, or Throwing Knives"})
    elif "+10 to either Guns or Melee skill" in clean:
        choices.append({"id": "pick_guns_melee", "kind": "skill_option", "options": [{"skill": "Guns", "points": 10}, {"skill": "Melee", "points": 10}], "prompt": "Choose +10 Guns or Melee"})
    elif "+10 to either Pilot: Space, Free Fall, or Hardware: Demolitions" in clean:
        choices.append({"id": "pick_pirate_skill", "kind": "skill_option", "options": [{"skill": "Pilot: Space", "points": 10}, {"skill": "Free Fall", "points": 10}, {"skill": "Hardware: Demolitions", "points": 10}], "prompt": "Choose +10 Pilot: Space, Free Fall, or Hardware: Demolitions"})
    elif "Replace any one active skill with another active skill" in clean:
        choices.append({"id": "replace_active", "kind": "replace_skill", "from_scope": "active", "to_scope": "active", "prompt": "Replace 1 Active skill with another Active skill at the same rating"})
    elif "Replace one active skill with Melee (or Guns" in clean:
        choices.append({"id": "replace_melee_guns", "kind": "replace_skill", "from_scope": "active", "to_options": ["Melee", "Guns"], "prompt": "Replace 1 Active skill with Melee (or Guns if you already have Melee)"})
    elif "Replace one Active skill with a Know skill" in clean:
        choices.append({"id": "replace_active_know", "kind": "replace_skill", "from_scope": "active", "to_scope": "know", "prompt": "Replace 1 Active skill with a Know skill at the same rating"})
    elif "replace one Know skill field with one relevant to the fandom" in clean:
        choices.append({"id": "replace_know_fandom", "kind": "replace_skill", "from_scope": "know", "to_scope": "know", "prompt": "Replace 1 Know skill field with a fandom Know field"})

    # Generic skill choices like "+10 to two skills of your choice", "−10 to one skill of your choice"
    for m in re.finditer(r"([+−-])(\d+)\s+to\s+(one|two)\s+(?:separate\s+)?(active\s+|Know\s+)?skills?\s+of your choice", clean, re.I):
        sign = -1 if m.group(1) in ("-", "−") else 1
        amt = sign * int(m.group(2))
        cnt = 2 if m.group(3).lower() == "two" else 1
        raw_sc = (m.group(4) or "").strip().lower()
        scope = "active" if raw_sc == "active" else ("know" if raw_sc == "know" else "any")
        choices.append({"id": f"pick_skill_{len(choices)+1}", "kind": "skill_bonus", "amount": amt, "count": cnt, "scope": scope, "prompt": f"Choose {cnt} skill(s) for {amt:+d}"})

    # Category-scoped Know/Hardware/Pilot choices
    m_know_cat = re.search(r"([+−-])(\d+)\s+to\s+(?:a|one)\s+Know skill with (?:an?|the)\s+(.+?)\s+field of your choice", clean, re.I)
    if m_know_cat:
        sign = -1 if m_know_cat.group(1) in ("-", "−") else 1
        amt = sign * int(m_know_cat.group(2))
        fld = m_know_cat.group(3)
        choices.append({"id": f"pick_know_field_{len(choices)+1}", "kind": "skill_bonus", "amount": amt, "count": 1, "scope": f"know_category:{fld}", "allow_roll": True, "prompt": f"Choose or roll a Know skill ({fld}) for {amt:+d}"})
    elif "+10 to a Hardware skill of your choice" in clean:
        choices.append({"id": "pick_hw", "kind": "skill_bonus", "amount": 10, "count": 1, "scope": "hardware", "allow_roll": True, "prompt": "Choose or roll +10 Hardware skill"})
    elif "+10 Pilot skill in a field of your choice" in clean:
        choices.append({"id": "pick_pilot", "kind": "skill_bonus", "amount": 10, "count": 1, "scope": "pilot", "allow_roll": True, "prompt": "Choose or roll +10 Pilot skill"})
    elif "+10 Hardware: Electronics or Hardware: Robotics" in clean:
        choices.append({"id": "pick_hw_or", "kind": "skill_option", "options": [{"skill": "Hardware: Electronics", "points": 10}, {"skill": "Hardware: Robotics", "points": 10}], "prompt": "Choose +10 Hardware: Electronics or Hardware: Robotics"})
    else:
        # Specific Know skills: "+10 Know: TITANs", "+20 Know: Xeno-archeology"
        for m in re.finditer(r"([+−-])(\d+)\s+Know:\s*([A-Za-zÀ-ÿ0-9\s/\-&'()]+?)(?=\s*(?:\.|,|but|and|$))", clean):
            sign = -1 if m.group(1) in ("-", "−") else 1
            kname = m.group(3).strip().rstrip(".")
            know_skills[kname] = know_skills.get(kname, 0) + sign * int(m.group(2))
        # Specific Active skills: "+10 Guns", "+10 Medicine: Biotech", "+10 to Persuade skill"
        for m in re.finditer(r"([+−-])(\d+)\s+(?:to\s+)?(Athletics|Deceive|Fray|Free Fall|Guns|Infiltrate|Infosec|Interface|Kinesics|Melee|Perceive|Persuade|Program|Provoke|Psi|Research|Survival|Hardware:\s*[A-Za-z]+|Medicine:\s*[A-Za-z]+|Pilot:\s*[A-Za-z]+|Exotic Skill:\s*[A-Za-z\s]+?)(?=\s*(?:skill|\.|,|but|and|$))", clean):
            sign = -1 if m.group(1) in ("-", "−") else 1
            sname = m.group(3).strip()
            if sname.startswith("Pilot: Nautical"):
                sname = "Pilot: Nautical"
            skills[sname] = skills.get(sname, 0) + sign * int(m.group(2))

    # 10. Motivations
    for m in re.finditer(r"gain the motivation\s+([+−–-][A-Za-zÀ-ÿ0-9\s/\-]+?)(?=\s*(?:\.|,|$))", clean, re.I):
        mot = m.group(1).strip().replace("–", "-").replace("−", "-")
        motivations.append(mot)

    # 11. Notable gear/items
    if "fake ego id" in clean.lower():
        gear.append({"name": "Fake Ego ID", "complexity": "Maj/R/3", "page": "315"})
    if "blue box" in clean.lower():
        gear.append({"name": "Blue Box", "complexity": "Min/1", "page": "340"})
    if "kaos AI" in clean:
        gear.append({"name": "Kaos AI", "complexity": "Min/1", "page": "326"})
    if "hazardous recovery bond" in clean.lower():
        gear.append({"name": "Hazardous Recovery Bond", "complexity": "Min/1", "page": "315"})
    if "emergency farcaster" in clean.lower():
        gear.append({"name": "Emergency Farcaster", "complexity": "Mod/2", "page": "320"})
    if "green petal flowers" in clean.lower():
        gear.append({"name": "Inquisitive Green Petal Flowers (5 doses)", "complexity": "Min/1", "page": "333"})
    if "servitor, saucer, or gnat bot" in clean.lower():
        choices.append({"id": "pick_bot", "kind": "gear_option", "options": ["Servitor Bot", "Saucer Bot", "Gnat Bot"], "prompt": "Choose free bot: Servitor, Saucer, or Gnat"})
    if "smart dog, smart monkey, or smart rat" in clean.lower():
        choices.append({"id": "pick_smart_pet", "kind": "gear_option", "options": ["Smart Dog", "Smart Monkey", "Smart Rat"], "prompt": "Choose free smart animal: Dog, Monkey, or Rat"})
    if "hypermesh link" in clean.lower():
        choices.append({"id": "pick_hypermesh", "kind": "gear_option", "options": ["Gain Hypermesh Link", "Decline Hypermesh Link"], "prompt": "Accept Neo-Synergist Hypermesh Link?"})
    if "backdoor" in clean.lower() and "hypercorp" in clean.lower():
        gear.append({"name": "Hypercorp Mesh Backdoor", "complexity": "Special", "page": "263"})
    if "digital exsurgent virus" in clean.lower():
        gear.append({"name": "Suspicious Infected Electronics", "complexity": "Special", "page": "382"})
    if "double the Availability of one morph" in clean:
        effects.setdefault("notes", []).append("Double Availability of one morph on Titan")
    if "exchange one" in clean.lower() and "60+" in clean:
        target_sk = "Melee" if "for Melee skill" in clean else ("Guns" if "with Guns skill" in clean else "")
        if target_sk:
            choices.append({
                "id": f"swap_60_{target_sk.lower()}",
                "kind": "exchange_60_for_skill",
                "target_skill": target_sk,
                "prompt": f"Optional/if lacking {target_sk} 60+: exchange one 60+ active skill for {target_sk} at the same rating",
            })
    if "extra ware of Major complexity" in clean:
        choices.append({"id": "pick_major_ware", "kind": "free_text", "target": "extra_gear", "prompt": "Choose 1 extra ware of Major complexity installed in your morph"})

    if skills:
        effects["skills"] = skills
    if know_skills:
        effects["know_skills"] = know_skills
    if rep:
        effects["rep"] = rep
    if aptitudes:
        effects["aptitudes"] = aptitudes
    if traits:
        effects["traits"] = traits
    if choices:
        effects["choices"] = choices
    if sub_rolls:
        effects["sub_rolls"] = sub_rolls
    if motivations:
        effects["motivations"] = motivations
    if gear:
        effects["gear"] = gear
    if flags:
        effects["flags"] = flags
    return effects


def parse_lifepath_markdown(md_path: Path) -> list[dict[str, Any]]:
    """Parse docs/ep2e-lifepath-character-creation.md into a list of table payloads."""
    text = md_path.read_text(encoding="utf-8")
    sections = _extract_sections(text)
    tables_out: list[dict[str, Any]] = []
    sort_idx = 0

    def add_table(
        *,
        slug: str,
        step_number: int,
        code: str,
        name: str,
        category: str,
        die_type: str,
        description: str = "",
        allow_choice: bool = True,
        rules_meta: dict[str, Any] | None = None,
        entries: list[dict[str, Any]] | None = None,
    ) -> None:
        nonlocal sort_idx
        sort_idx += 10
        tables_out.append({
            "slug": slug,
            "step_number": step_number,
            "code": code,
            "name": name,
            "category": category,
            "die_type": die_type,
            "description": description,
            "allow_choice": allow_choice,
            "rules_meta": rules_meta or {},
            "sort_order": sort_idx,
            "entries": entries or [],
        })

    # --- Step 1: Flex (fixed starting rule) ---
    add_table(
        slug="starting-flex",
        step_number=1,
        code="1.0",
        name="Step 1: Starting Ego Flex",
        category="package",
        die_type="fixed",
        description="Every character begins with 1 point of ego Flex. Flex may also be spent once per point during character creation to reroll a stage or event table.",
        allow_choice=False,
        entries=[{
            "code": "step1-flex",
            "roll_min": None,
            "roll_max": None,
            "title": "Starting Ego Flex (+1)",
            "summary": "Every character begins with 1 point of ego Flex.",
            "effects": {"flex": 1},
            "sort_order": 10,
        }],
    )

    # --- Step 2: Aptitude Template ---
    apt_lines = sections.get("### Table 2.0: Random Aptitude Template (`1d10`)", [])
    apt_tables = _split_md_table(apt_lines)
    apt_entries = []
    if apt_tables:
        _, rows = apt_tables[0]
        for idx, row in enumerate(rows, 1):
            d10_lo, d10_hi = _parse_die_token(row[0], "d10")
            sub_lo, sub_hi = _parse_die_token(row[1], "d10")
            tname = _strip_md(row[2])
            desc = _strip_md(row[3])
            apts = {k.lower(): int(row[4 + i]) for i, k in enumerate(KNOWN_APTS)}
            apt_entries.append({
                "code": f"apt-{d10_lo}-{sub_lo or 0}-{_slugify_simple(tname)}",
                "roll_min": d10_lo,
                "roll_max": d10_hi,
                "sub_roll_min": sub_lo,
                "sub_roll_max": sub_hi,
                "title": tname,
                "summary": desc,
                "effects": {"set_aptitudes": apts},
                "sort_order": idx * 10,
            })
    add_table(
        slug="aptitude-template",
        step_number=2,
        code="2.0",
        name="Table 2.0: Aptitude Template",
        category="package",
        die_type="d10",
        description="Choose or roll 1d10 (with 1d10 sub-roll on 8-0) for your starting aptitude array.",
        allow_choice=True,
        entries=apt_entries,
    )

    # --- Step 3: Native Tongue ---
    lang_lines = sections.get("### Table 3.0: Random Language (`1d100`)", [])
    lang_tables = _split_md_table(lang_lines)
    lang_entries = []
    if lang_tables:
        _, rows = lang_tables[0]
        idx = 0
        for row in rows:
            for pair_idx in range(0, len(row), 2):
                r_raw = row[pair_idx].strip()
                l_raw = row[pair_idx + 1].strip() if pair_idx + 1 < len(row) else ""
                if not r_raw or not l_raw:
                    continue
                idx += 1
                lo, hi = _parse_die_token(r_raw, "d100")
                lname = _strip_md(l_raw)
                eff: dict[str, Any] = {"languages": [lname]}
                if lname.lower() == "other":
                    eff = {
                        "choices": [{
                            "id": "custom_native_language",
                            "kind": "free_text",
                            "target": "native_language",
                            "prompt": "Enter your custom native language",
                        }]
                    }
                lang_entries.append({
                    "code": f"lang-{lo:02d}-{_slugify_simple(lname)}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": lname,
                    "summary": f"Native language: {lname}",
                    "effects": eff,
                    "sort_order": idx * 10,
                })
        lang_entries.sort(key=lambda e: e["roll_min"])
    add_table(
        slug="native-tongue",
        step_number=3,
        code="3.0",
        name="Table 3.0: Native Tongue",
        category="package",
        die_type="d100",
        description="Determine your character's native language.",
        allow_choice=True,
        entries=lang_entries,
    )

    # --- Step 4: Background Path 4.0 ---
    bg_lines = sections.get("### Table 4.0: Random Background Path (`1d10`)", [])
    bg_tables = _split_md_table(bg_lines)
    bg_entries = []
    bg_slug_map = {
        "Colonist": "background-colonist",
        "Enclaver": "background-enclaver",
        "Freelancer": "background-freelancer",
        "Hyperelite": "background-hyperelite",
        "Indenture": "background-indenture",
        "Infolife": "background-infolife",
        "Isolate": "background-isolate",
        "Lost": "background-lost",
        "Underclass": "background-underclass",
        "Uplift": "background-uplift",
    }
    if bg_tables:
        _, rows = bg_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d10")
            bname = _strip_md(row[1])
            desc = _strip_md(row[2])
            flags: dict[str, Any] = {"background_group": bname}
            if bname in ("Infolife", "Lost", "Uplift"):
                flags["age_rule"] = bname.lower()
            bg_entries.append({
                "code": f"bg-{_slugify_simple(bname)}",
                "roll_min": lo,
                "roll_max": hi,
                "title": bname,
                "summary": desc,
                "next_table_slug": bg_slug_map.get(bname, f"background-{_slugify_simple(bname)}"),
                "effects": {"flags": flags},
                "sort_order": idx * 10,
            })
    add_table(
        slug="background-path",
        step_number=4,
        code="4.0",
        name="Table 4.0: Background Path",
        category="package",
        die_type="d10",
        description="Choose a background or roll 1d10, then resolve its sub-table (4.1-4.10).",
        allow_choice=True,
        entries=bg_entries,
    )

    # --- Step 4.1 - 4.10 Sub-backgrounds ---
    sub_bg_headers = [
        ("4.1", "### 4.1 Colonist", "background-colonist", "Colonist"),
        ("4.2", "### 4.2 Enclaver", "background-enclaver", "Enclaver"),
        ("4.3", "### 4.3 Freelancer", "background-freelancer", "Freelancer"),
        ("4.4", "### 4.4 Hyperelite", "background-hyperelite", "Hyperelite"),
        ("4.5", "### 4.5 Indenture", "background-indenture", "Indenture"),
        ("4.6", "### 4.6 Infolife", "background-infolife", "Infolife"),
        ("4.7", "### 4.7 Isolate", "background-isolate", "Isolate"),
        ("4.8", "### 4.8 Lost", "background-lost", "Lost"),
        ("4.9", "### 4.9 Underclass", "background-underclass", "Underclass"),
        ("4.10", "### 4.10 Uplift", "background-uplift", "Uplift"),
    ]
    for code, heading, slug, bg_group in sub_bg_headers:
        slines = sections.get(heading, [])
        stables = _split_md_table(slines)
        entries = []
        if stables:
            _, rows = stables[0]
            for idx, row in enumerate(rows, 1):
                lo, hi = _parse_die_token(row[0], "d100")
                sub_name = _strip_md(row[1])
                bio = _strip_md(row[2])
                eff = _parse_package_modifiers(row[3])
                mots = [_strip_md(m).replace("–", "-").replace("−", "-") for m in row[4].split(",") if _strip_md(m)]
                if mots:
                    eff["motivations"] = mots
                morph_info = _parse_morph_cell(row[5])
                eff.update({k: v for k, v in morph_info.items() if k != "sub_rolls"})
                if "sub_rolls" in morph_info:
                    eff.setdefault("sub_rolls", []).extend(morph_info["sub_rolls"])
                eff.setdefault("flags", {})["background_group"] = bg_group
                entries.append({
                    "code": f"{code}-{_slugify_simple(sub_name)}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": sub_name,
                    "summary": bio,
                    "effects": eff,
                    "raw_source": {"modifiers": _strip_md(row[3]), "motivations": _strip_md(row[4]), "morph": _strip_md(row[5])},
                    "sort_order": idx * 10,
                })
        add_table(
            slug=slug,
            step_number=4,
            code=code,
            name=f"Table {code}: {bg_group} Sub-Background",
            category="subtable",
            die_type="d100",
            description=f"Sub-background packages and starting morph rolls for {bg_group}.",
            allow_choice=True,
            rules_meta={"parent_table": "background-path", "background_group": bg_group},
            entries=entries,
        )

    # --- Step 5: Youth Event ---
    youth_lines = sections.get("### 5.0 Youth Event (`1d100`)", [])
    youth_tables = _split_md_table(youth_lines)
    youth_entries = []
    if youth_tables:
        _, rows = youth_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d100")
            res = _strip_md(row[1])
            youth_entries.append({
                "code": f"5.0-{lo:02d}",
                "roll_min": lo,
                "roll_max": hi,
                "title": res[:120] + ("..." if len(res) > 120 else ""),
                "summary": res,
                "effects": _parse_event_effects(row[1]),
                "sort_order": idx * 10,
            })
    add_table(
        slug="youth-event",
        step_number=5,
        code="5.0",
        name="Table 5.0: Youth Event",
        category="event",
        die_type="d100",
        description="Major event shaping your character's youth.",
        allow_choice=False,
        entries=youth_entries,
    )

    # --- Step 6: Age & 6.1 Advanced Age ---
    age_lines = sections.get("### 6.0 Age (`1d100`)", [])
    age_tables = _split_md_table(age_lines)
    age_entries = []
    if age_tables:
        _, rows = age_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d100")
            res = _strip_md(row[1])
            eff: dict[str, Any] = {"flags": {}}
            if "20s" in res:
                eff["flags"]["age_decade"] = 20
                eff["flags"]["skip_steps"] = [7]
            elif "30s" in res:
                eff["flags"]["age_decade"] = 30
            elif "40s" in res:
                eff["flags"]["age_decade"] = 40
            elif "50s" in res:
                eff["flags"]["age_decade"] = 50
            elif "60s" in res:
                eff["flags"]["age_decade"] = 60
                eff["sub_rolls"] = [{"table_slug": "advanced-age", "modifier": 3, "count": 1, "reason": "Advanced Age (60s, +3)"}]
            elif "70s" in res:
                eff["flags"]["age_decade"] = 70
                eff["sub_rolls"] = [{"table_slug": "advanced-age", "modifier": 2, "count": 1, "reason": "Advanced Age (70s, +2)"}]
            elif "80s" in res:
                eff["flags"]["age_decade"] = 80
                eff["sub_rolls"] = [{"table_slug": "advanced-age", "modifier": 1, "count": 1, "reason": "Advanced Age (80s, +1)"}]
            elif "90s" in res:
                eff["flags"]["age_decade"] = 90
                eff["sub_rolls"] = [{"table_slug": "advanced-age", "modifier": 0, "count": 1, "reason": "Advanced Age (90s)"}]
            elif "Over 100" in res:
                eff["flags"]["age_decade"] = 100
                eff["sub_rolls"] = [{"table_slug": "advanced-age", "modifier": 0, "count": 2, "reason": "Advanced Age (100+, roll twice)"}]
            age_entries.append({
                "code": f"6.0-{lo:02d}",
                "roll_min": lo,
                "roll_max": hi,
                "title": res.split(".")[0],
                "summary": res,
                "effects": eff,
                "sort_order": idx * 10,
            })
    add_table(
        slug="age",
        step_number=6,
        code="6.0",
        name="Table 6.0: Starting Age",
        category="event",
        die_type="d100",
        description="Determine starting age decade + 1d10 exact year (subject to Infolife, Lost, and Uplift rules).",
        allow_choice=False,
        entries=age_entries,
    )

    adv_lines = sections.get("### 6.1 Advanced Age (`1d10`)", [])
    adv_tables = _split_md_table(adv_lines)
    adv_entries = []
    if adv_tables:
        _, rows = adv_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d10")
            res = _strip_md(row[1])
            adv_entries.append({
                "code": f"6.1-{lo}",
                "roll_min": lo,
                "roll_max": hi,
                "title": res[:120],
                "summary": res,
                "effects": _parse_event_effects(row[1]),
                "sort_order": idx * 10,
            })
    add_table(
        slug="advanced-age",
        step_number=6,
        code="6.1",
        name="Table 6.1: Advanced Age",
        category="subtable",
        die_type="d10",
        description="Modifiers for characters aged 60 or older.",
        allow_choice=False,
        entries=adv_entries,
    )

    # --- Step 7, 8, 12, 13 (3 tables), 14 Events ---
    event_specs = [
        ("pre-fall-event", 7, "7.0", "Table 7.0: Pre-Fall Event", "### 7.0 Pre-Fall Event (`1d100`)", "Major life event before the Fall."),
        ("fall-event", 8, "8.0", "Table 8.0: Fall Event", "### 8.0 Fall Event (`1d100`)", "How you survived (or died and backed up during) the Fall."),
        ("post-fall-event", 12, "12.0", "Table 12.0: Post-Fall Event", "### 12.0 Post-Fall Event (`1d100`)", "Major event in the decade AF."),
        ("firewall-event", 13, "13.1", "Firewall Event", "### Firewall Event", "Campaign Event table for Firewall agents."),
        ("gatecrashing-event", 13, "13.2", "Gatecrashing Event", "### Gatecrashing Event", "Campaign Event table for Gatecrashers."),
        ("crime-event", 13, "13.3", "Crime Event", "### Crime Event", "Campaign Event table for Criminals / Underworld characters."),
        ("story-event", 14, "14.0", "Table 14.0: Story Event (Optional)", "### 14.0 Story Event (`1d100`)", "Optional narrative hook event (also triggered by 00-19 Pre-Fall, 00-09 Fall, 00 Post-Fall)."),
    ]
    for slug, step_no, code, name, heading, desc in event_specs:
        elines = sections.get(heading, [])
        etables = _split_md_table(elines)
        entries = []
        if etables:
            _, rows = etables[0]
            for idx, row in enumerate(rows, 1):
                lo, hi = _parse_die_token(row[0], "d100")
                res = _strip_md(row[1])
                entries.append({
                    "code": f"{code}-{lo:02d}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": res[:120] + ("..." if len(res) > 120 else ""),
                    "summary": res,
                    "effects": _parse_event_effects(row[1]),
                    "sort_order": idx * 10,
                })
        add_table(
            slug=slug,
            step_number=step_no,
            code=code,
            name=name,
            category="event",
            die_type="d100",
            description=desc,
            allow_choice=False,
            entries=entries,
        )

    # --- Step 9: Career Path (9.0 + 9.1..9.14) ---
    career_slug_map = {
        "Academic": "career-academic",
        "Covert Operative": "career-covert-op",
        "Enforcer": "career-enforcer",
        "Explorer": "career-explorer",
        "Face": "career-face",
        "Genehacker": "career-genehacker",
        "Hacker": "career-hacker",
        "Investigator": "career-investigator",
        "Medic": "career-medic",
        "Mindhacker": "career-mindhacker",
        "Scavenger": "career-scavenger",
        "Scientist": "career-scientist",
        "Soldier": "career-soldier",
        "Techie": "career-techie",
    }
    cp_lines = sections.get("### 9.0 Random Career Path (`1d10 #1` + `1d10 #2`)", [])
    cp_tables = _split_md_table(cp_lines)
    cp_entries = []
    if cp_tables:
        _, rows = cp_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d10_pair")
            slo, shi = _parse_die_token(row[1], "d10_pair")
            cname = _strip_md(row[2])
            desc = _strip_md(row[3])
            is_reroll = "re-roll" in cname.lower()
            cp_entries.append({
                "code": f"9.0-{lo}-{slo}-{_slugify_simple(cname)}",
                "roll_min": lo,
                "roll_max": hi,
                "sub_roll_min": slo,
                "sub_roll_max": shi,
                "title": cname,
                "summary": desc,
                "next_table_slug": "" if is_reroll else career_slug_map.get(cname, f"career-{_slugify_simple(cname)}"),
                "effects": {"flags": {"reroll_sub": True}} if is_reroll else {"flags": {"career_group": cname}},
                "sort_order": idx * 10,
            })
    add_table(
        slug="career-path",
        step_number=9,
        code="9.0",
        name="Table 9.0: Career Path",
        category="package",
        die_type="d10_pair",
        description="Choose a career path or roll 1d10 #1 + 1d10 #2 (re-rolling #2 on 8-0), then resolve its 3 sub-careers.",
        allow_choice=True,
        entries=cp_entries,
    )

    career_subs = [
        ("9.1", "### 9.1 Academic", "career-academic", "Academic"),
        ("9.2", "### 9.2 Covert Op", "career-covert-op", "Covert Operative"),
        ("9.3", "### 9.3 Enforcer", "career-enforcer", "Enforcer"),
        ("9.4", "### 9.4 Explorer", "career-explorer", "Explorer"),
        ("9.5", "### 9.5 Face", "career-face", "Face"),
        ("9.6", "### 9.6 Genehacker", "career-genehacker", "Genehacker"),
        ("9.7", "### 9.7 Hacker", "career-hacker", "Hacker"),
        ("9.8", "### 9.8 Investigator", "career-investigator", "Investigator"),
        ("9.9", "### 9.9 Medic", "career-medic", "Medic"),
        ("9.10", "### 9.10 Mindhacker", "career-mindhacker", "Mindhacker"),
        ("9.11", "### 9.11 Scavenger", "career-scavenger", "Scavenger"),
        ("9.12", "### 9.12 Scientist", "career-scientist", "Scientist"),
        ("9.13", "### 9.13 Soldier", "career-soldier", "Soldier"),
        ("9.14", "### 9.14 Techie", "career-techie", "Techie"),
    ]
    for code, heading, slug, cgroup in career_subs:
        clines = sections.get(heading, [])
        ctables = _split_md_table(clines)
        entries = []
        if ctables:
            _, rows = ctables[0]
            for idx, row in enumerate(rows, 1):
                lo, hi = _parse_die_token(row[0], "d100")
                cname = _strip_md(row[1])
                desc = _strip_md(row[2])
                mot = _strip_md(row[3]).replace("–", "-").replace("−", "-")
                combined_mods = f"{_strip_md(row[4])}, {_strip_md(row[5])}".strip(", ")
                eff = _parse_package_modifiers(combined_mods)
                if mot:
                    eff["motivations"] = [mot]
                eff.setdefault("flags", {})["career_group"] = cgroup
                entries.append({
                    "code": f"{code}-{_slugify_simple(cname)}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": cname,
                    "summary": desc,
                    "effects": eff,
                    "raw_source": {"apt_rep": _strip_md(row[4]), "skills": _strip_md(row[5]), "motivation": mot},
                    "sort_order": idx * 10,
                })
        add_table(
            slug=slug,
            step_number=9,
            code=code,
            name=f"Table {code}: {cgroup} Career",
            category="subtable",
            die_type="d100",
            description=f"Sub-career packages for {cgroup}.",
            allow_choice=True,
            rules_meta={"parent_table": "career-path", "career_group": cgroup},
            entries=entries,
        )

    # --- Step 10: Interests (10.0 + Interest Packages) ---
    int_pkg_lines = sections.get("### Interest Packages", [])
    int_pkg_tables = _split_md_table(int_pkg_lines)
    int_pkg_entries = []
    if int_pkg_tables:
        _, rows = int_pkg_tables[0]
        for idx, row in enumerate(rows, 1):
            iname = _strip_md(row[0])
            mot = _strip_md(row[1]).replace("–", "-").replace("−", "-")
            combined = f"{_strip_md(row[2])}, {_strip_md(row[3])}".strip(", ")
            eff = _parse_package_modifiers(combined)
            if mot:
                eff["motivations"] = [mot]
            int_pkg_entries.append({
                "code": f"10.1-{_slugify_simple(iname)}",
                "roll_min": idx,
                "roll_max": idx,
                "title": iname,
                "summary": f"Interest Package: {iname}",
                "effects": eff,
                "raw_source": {"rep_traits": _strip_md(row[2]), "skills": _strip_md(row[3]), "motivation": mot},
                "sort_order": idx * 10,
            })
    add_table(
        slug="interest-packages",
        step_number=10,
        code="10.1",
        name="Interest Packages",
        category="subtable",
        die_type="choice",
        description="Mechanical packages for all 16 Step 10 Interests.",
        allow_choice=True,
        entries=int_pkg_entries,
    )

    int_lines = sections.get("### 10.0 Random Interest (`1d10 #1` + `1d10 #2`)", [])
    int_tables = _split_md_table(int_lines)
    int_entries = []
    if int_tables:
        _, rows = int_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d10_pair")
            slo, shi = _parse_die_token(row[1], "d10_pair")
            iname = _strip_md(row[2])
            desc = _strip_md(row[3])
            is_reroll = "re-roll" in iname.lower()
            pkg_code = "" if is_reroll else f"10.1-{_slugify_simple(iname)}"
            int_entries.append({
                "code": f"10.0-{lo}-{slo}-{_slugify_simple(iname)}",
                "roll_min": lo,
                "roll_max": hi,
                "sub_roll_min": slo,
                "sub_roll_max": shi,
                "title": iname,
                "summary": desc,
                "next_table_slug": "" if is_reroll else "interest-packages",
                "effects": {"flags": {"reroll_sub": True}} if is_reroll else {"target_entry_code": pkg_code},
                "sort_order": idx * 10,
            })
    add_table(
        slug="interest",
        step_number=10,
        code="10.0",
        name="Table 10.0: Interests",
        category="package",
        die_type="d10_pair",
        description="Choose an interest or roll 1d10 #1 + 1d10 #2 (re-rolling #2 on 9-0).",
        allow_choice=True,
        entries=int_entries,
    )

    # --- Step 11: Faction ---
    fac_lines = sections.get("### 11.0 Faction (`1d100`)", [])
    fac_tables = _split_md_table(fac_lines)
    fac_entries = []
    if fac_tables:
        _, rows = fac_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d100")
            fname = _strip_md(row[1])
            know_str = _strip_md(row[2])
            mots = [_strip_md(m).replace("–", "-").replace("−", "-") for m in row[3].split(",") if _strip_md(m)]
            eff = _parse_package_modifiers(f"Know: {know_str}, {_strip_md(row[4])}")
            if mots:
                eff["motivations"] = mots
            eff.setdefault("flags", {})["faction"] = fname
            fac_entries.append({
                "code": f"11.0-{_slugify_simple(fname)}",
                "roll_min": lo,
                "roll_max": hi,
                "title": fname,
                "summary": f"Faction: {fname} ({know_str})",
                "effects": eff,
                "sort_order": idx * 10,
            })
    add_table(
        slug="faction",
        step_number=11,
        code="11.0",
        name="Table 11.0: Faction",
        category="package",
        die_type="d100",
        description="Choose or roll your starting faction allegiance.",
        allow_choice=True,
        entries=fac_entries,
    )

    # --- Step 15: Gear Packs (Campaign & Profession) ---
    def _parse_gear_pack_section(heading_list: list[tuple[str, str]], slug: str, code: str, title: str, desc: str) -> None:
        entries = []
        for idx, (sec_heading, pack_title) in enumerate(heading_list, 1):
            glines = sections.get(sec_heading, [])
            gtables = _split_md_table(glines)
            items = []
            synthmorph_alts = []
            if gtables:
                _, rows = gtables[0]
                for r in rows:
                    items.append({
                        "name": _strip_md(r[0]),
                        "complexity": _strip_md(r[1]),
                        "page": _strip_md(r[2]),
                        "notes": _strip_md(r[3]),
                    })
                if len(gtables) > 1:
                    for r in gtables[1][1]:
                        synthmorph_alts.append({
                            "name": _strip_md(r[0]),
                            "complexity": _strip_md(r[1]),
                            "page": _strip_md(r[2]),
                            "notes": _strip_md(r[3]),
                        })
            # Also capture inline "*Synthmorph Alternative..." notes
            alt_notes = [_strip_md(l) for l in glines if "Synthmorph Alternative" in l]
            if not synthmorph_alts and alt_notes:
                for an in alt_notes:
                    m_alt = re.search(r":\*?\s*([A-Z][^(]+)\(([^,]+),\s*p\.\s*(\d+)\)\s*[—-]\s*(.+)$", an)
                    if m_alt:
                        synthmorph_alts.append({
                            "name": m_alt.group(1).strip(),
                            "complexity": m_alt.group(2).strip(),
                            "page": m_alt.group(3).strip(),
                            "notes": m_alt.group(4).strip(),
                        })
            entries.append({
                "code": f"{code}-{_slugify_simple(pack_title)}",
                "roll_min": idx,
                "roll_max": idx,
                "title": pack_title,
                "summary": f"{len(items)} starting gear items" + (f" ({alt_notes[0]})" if alt_notes else ""),
                "effects": {
                    "gear": items,
                    "synthmorph_alt_gear": synthmorph_alts,
                    "synthmorph_alt_notes": alt_notes,
                },
                "sort_order": idx * 10,
            })
        add_table(
            slug=slug,
            step_number=15,
            code=code,
            name=title,
            category="gear_pack",
            die_type="choice",
            description=desc,
            allow_choice=True,
            entries=entries,
        )

    _parse_gear_pack_section(
        [
            ("#### Firewall Agent / Criminal", "Firewall Agent / Criminal"),
            ("#### Gatecrashing", "Gatecrashing"),
            ("#### Infomorph", "Infomorph"),
        ],
        slug="gear-pack-campaign",
        code="15.1",
        title="Gear Packs: Campaign",
        desc="Choose 1 Campaign Gear Pack at Step 15.",
    )
    _parse_gear_pack_section(
        [
            ("#### Academic", "Academic"),
            ("#### Covert Operative", "Covert Operative"),
            ("#### Enforcer", "Enforcer"),
            ("#### Explorer", "Explorer"),
            ("#### Face / Dealer", "Face / Dealer"),
            ("#### Genehacker", "Genehacker"),
            ("#### Hacker", "Hacker"),
            ("#### Investigator", "Investigator"),
            ("#### Medic", "Medic"),
            ("#### Mindhacker", "Mindhacker"),
            ("#### Scavenger", "Scavenger"),
            ("#### Scientist", "Scientist"),
            ("#### Soldier", "Soldier"),
            ("#### Techie", "Techie"),
        ],
        slug="gear-pack-profession",
        code="15.2",
        title="Gear Packs: Profession",
        desc="Take 1 Profession Gear Pack matching your Step 9 career.",
    )

    # --- Reference Roll Tables ---
    # Random Motivations (multi-col 1d100)
    mot_lines = sections.get("#### Table: Random Motivations (`1d100`)", [])
    mot_tables = _split_md_table(mot_lines)
    mot_entries = []
    if mot_tables:
        _, rows = mot_tables[0]
        idx = 0
        for row in rows:
            for pair_idx in range(0, len(row), 2):
                r_raw = row[pair_idx].strip()
                m_raw = row[pair_idx + 1].strip() if pair_idx + 1 < len(row) else ""
                if not r_raw or not m_raw:
                    continue
                idx += 1
                lo, hi = _parse_die_token(r_raw, "d100")
                mname = _strip_md(m_raw)
                mot_entries.append({
                    "code": f"mot-{lo:02d}-{_slugify_simple(mname)}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": mname,
                    "summary": f"Motivation: +{mname}",
                    "effects": {"motivations": [f"+{mname}"]},
                    "sort_order": idx * 10,
                })
        mot_entries.sort(key=lambda e: e["roll_min"])
    add_table(
        slug="random-motivations",
        step_number=0,
        code="REF-MOT",
        name="Random Motivations (1d100)",
        category="reference",
        die_type="d100",
        description="Random starting or replacement motivations.",
        allow_choice=True,
        entries=mot_entries,
    )

    # Morph Type (d100) -> points to morph sub-tables
    mtype_lines = sections.get("#### Morph Type (`1d100`)", [])
    mtype_tables = _split_md_table(mtype_lines)
    morph_type_map = {
        "Biomorph": "morph-biomorphs",
        "Pod": "morph-pod-biomorphs",
        "Uplift": "morph-uplift-biomorphs",
        "Synthmorph": "morph-synthmorphs",
        "Infomorph/Core": "morph-infomorphs",
        "Axle": "morph-axles",
    }
    mtype_entries = []
    if mtype_tables:
        _, rows = mtype_tables[0]
        for idx, row in enumerate(rows, 1):
            lo, hi = _parse_die_token(row[0], "d100")
            mtype = _strip_md(row[1])
            mtype_entries.append({
                "code": f"mtype-{_slugify_simple(mtype)}",
                "roll_min": lo,
                "roll_max": hi,
                "title": mtype,
                "summary": f"Roll on {mtype} table.",
                "next_table_slug": morph_type_map.get(mtype, ""),
                "effects": {"morph_category": mtype.lower()},
                "sort_order": idx * 10,
            })
    add_table(
        slug="morph-type",
        step_number=0,
        code="REF-MTYPE",
        name="Morph Type (1d100)",
        category="reference",
        die_type="d100",
        description="Determines which Random Morph sub-table to roll on.",
        allow_choice=True,
        entries=mtype_entries,
    )

    morph_sub_specs = [
        ("morph-biomorphs", "#### Biomorphs (`1d100`)", "Biomorphs (1d100)", "biomorph"),
        ("morph-pod-biomorphs", "#### Pod Biomorphs (`1d100`)", "Pod Biomorphs (1d100)", "pod"),
        ("morph-uplift-biomorphs", "#### Uplift Biomorphs (`1d100`)", "Uplift Biomorphs (1d100)", "uplift"),
        ("morph-synthmorphs", "#### Synthmorphs (`1d100`)", "Synthmorphs (1d100)", "synthmorph"),
        ("morph-infomorphs", "#### Info/Core Morphs (`1d100`)", "Info/Core Morphs (1d100)", "infomorph"),
        ("morph-flexbot-modules", "#### Flexbot Modules (`1d100`)", "Flexbot Modules (1d100)", "synthmorph"),
        ("morph-axles", "#### Axles (`1d100`)", "Axles (1d100)", "axle"),
    ]
    for slug, heading, title, mcat in morph_sub_specs:
        mlines = sections.get(heading, [])
        mtables = _split_md_table(mlines)
        mentries = []
        if mtables:
            _, rows = mtables[0]
            for idx, row in enumerate(rows, 1):
                lo, hi = _parse_die_token(row[0], "d100")
                mname = _strip_md(row[1])
                mp_cost = _strip_md(row[2])
                page = _strip_md(row[3])
                eff: dict[str, Any] = {"morph": mname, "morph_category": mcat, "mp_cost": mp_cost, "page": page}
                if "Flexbot Modules" in mname:
                    mname_clean = "Flexbot"
                    eff["morph"] = "Flexbot"
                    eff["sub_rolls"] = [{"table_slug": "morph-flexbot-modules", "reason": "Flexbot Module"}]
                elif slug == "morph-flexbot-modules":
                    eff["morph_module"] = mname
                    eff.pop("morph", None)
                mentries.append({
                    "code": f"{slug}-{lo:02d}-{_slugify_simple(mname)}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": mname,
                    "summary": f"MP Cost: {mp_cost} · p. {page}",
                    "effects": eff,
                    "sort_order": idx * 10,
                })
        add_table(
            slug=slug,
            step_number=0,
            code=slug.upper(),
            name=title,
            category="reference",
            die_type="d100",
            description=f"Random {title} reference table.",
            allow_choice=True,
            entries=mentries,
        )

    # Sleights, Sub-Strains, Disorders, Traits, Factions, Rep Networks, Random Skills
    simple_ref_specs = [
        ("sleight-type", "#### Type of Sleight (`1d10`)", "Type of Sleight (1d10)", "d10", "sleight_type"),
        ("watts-macleod-strains", "#### Watts-MacLeod Sub-Strains (`1d100`)", "Watts-MacLeod Sub-Strains (1d100)", "d100", "strain"),
        ("psi-chi-sleights", "#### Psi-Chi Sleights (`1d100`)", "Psi-Chi Sleights (1d100)", "d100", "sleight"),
        ("psi-gamma-sleights", "#### Psi-Gamma Sleights (`1d100`)", "Psi-Gamma Sleights (1d100)", "d100", "sleight"),
        ("disorders", "#### Disorders (`1d100`)", "Disorders (1d100)", "d100", "disorder"),
        ("trait-type", "#### Traits (`1d10`)", "Traits Type (1d10)", "d10", "trait_type"),
        ("positive-morph-traits", "#### Positive Morph Traits (`1d100`)", "Positive Morph Traits (1d100)", "d100", "trait"),
        ("negative-morph-traits", "#### Negative Morph Traits (`1d100`)", "Negative Morph Traits (1d100)", "d100", "trait"),
        ("positive-ego-traits", "#### Positive Ego Traits (`1d100`)", "Positive Ego Traits (1d100)", "d100", "trait"),
        ("negative-ego-traits", "#### Negative Ego Traits (`1d100`)", "Negative Ego Traits (1d100)", "d100", "trait"),
        ("ref-faction", "#### Faction (`1d100`)", "Reference Faction (1d100)", "d100", "faction"),
        ("rep-networks", "#### Rep Networks (`1d100`)", "Rep Networks (1d100)", "d100", "rep_network"),
        ("skill-active", "#### Active Skills (`1d100`)", "Active Skills (1d100)", "d100", "skill"),
        ("skill-exotic", "#### Exotic Skill Fields (`1d100`)", "Exotic Skill Fields (1d100)", "d100", "exotic_field"),
        ("skill-hardware", "#### Hardware Fields (`1d100`)", "Hardware Fields (1d100)", "d100", "hardware_field"),
        ("skill-medicine", "#### Medicine Fields (`1d100`)", "Medicine Fields (1d100)", "d100", "medicine_field"),
        ("skill-pilot", "#### Pilot Fields (`1d100`)", "Pilot Fields (1d100)", "d100", "pilot_field"),
        ("skill-know-art", "#### Know [Art] Fields (`1d100`)", "Know [Art] Fields (1d100)", "d100", "know_art"),
        ("skill-know-academic", "#### Know [Academic] Fields (`1d100`)", "Know [Academic] Fields (1d100)", "d100", "know_academic"),
        ("skill-know-interest", "#### Know [Interest] Fields (`1d100`)", "Know [Interest] Fields (1d100)", "d100", "know_interest"),
        ("skill-know-profession", "#### Know [Profession] Fields (`1d100`)", "Know [Profession] Fields (1d100)", "d100", "know_profession"),
    ]
    for slug, heading, title, dtype, kind in simple_ref_specs:
        rlines = sections.get(heading, [])
        rtables = _split_md_table(rlines)
        rentries = []
        if rtables:
            _, rows = rtables[0]
            for idx, row in enumerate(rows, 1):
                lo, hi = _parse_die_token(row[0], dtype)
                val = _strip_md(row[1])
                extra_cols = [_strip_md(c) for c in row[2:]]
                summary_txt = " · ".join(c for c in extra_cols if c) if extra_cols else val
                next_slug = ""
                eff: dict[str, Any] = {"kind": kind, "value": val}
                if kind == "sleight_type":
                    next_slug = "psi-chi-sleights" if "Psi-Chi" in val else "psi-gamma-sleights"
                elif kind == "trait_type":
                    if "Positive Ego" in val:
                        next_slug = "positive-ego-traits"
                    elif "Positive Morph" in val:
                        next_slug = "positive-morph-traits"
                    elif "Negative Ego" in val:
                        next_slug = "negative-ego-traits"
                    elif "Negative Morph" in val:
                        next_slug = "negative-morph-traits"
                elif kind == "disorder":
                    eff["traits"] = [{"name": f"Mental Disorder ({val})", "level": 1}]
                elif kind == "trait":
                    eff["traits"] = [{"name": val, "level": 1 if val in TRAIT_NO_DEFAULT_LEVEL else 2}]
                elif kind == "sleight":
                    eff["sleights"] = [val]
                rentries.append({
                    "code": f"{slug}-{idx:03d}-{_slugify_simple(val)[:32]}",
                    "roll_min": lo,
                    "roll_max": hi,
                    "title": val,
                    "summary": summary_txt,
                    "next_table_slug": next_slug,
                    "effects": eff,
                    "sort_order": idx * 10,
                })
        add_table(
            slug=slug,
            step_number=0,
            code=slug.upper(),
            name=title,
            category="reference",
            die_type=dtype,
            description=f"EP2e Reference table: {title}.",
            allow_choice=True,
            entries=rentries,
        )

    return tables_out


def build_fixture(
    md_path: Path | None = None,
    out_path: Path | None = None,
) -> list[dict[str, Any]]:
    base = Path(__file__).resolve().parent.parent.parent
    src = md_path or (base / "docs" / "ep2e-lifepath-character-creation.md")
    dst = out_path or (base / "spacemarches" / "fixtures" / "ep2e_lifepath_tables.json")
    tables = parse_lifepath_markdown(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(json.dumps(tables, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return tables
