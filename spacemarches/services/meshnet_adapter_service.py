"""Transform Django DesignPack & Ep2Entry records into MeshNet DesignPackPartial payloads."""

from __future__ import annotations

import re
from typing import Any

from django.utils.html import escape
from django.utils.text import slugify

from spacemarches.models import DesignPack, Ep2Entry
from spacemarches.services.design_pack_service import visible_design_packs_qs

try:
    import nh3  # type: ignore
except ImportError:  # pragma: no cover
    nh3 = None

VALID_COMPLEXITIES = {"trivial", "minor", "moderate", "major", "rare"}
VALID_SIZES = {"verySmall", "small", "medium", "large", "veryLarge"}
VALID_PHYSICAL_WARES = {"bioware", "cyberware", "hardware", "nanoware"}
VALID_DRUG_CATEGORIES = {
    "cognitive",
    "combat",
    "health",
    "nano",
    "narcoalgorithm",
    "petal",
    "psi",
    "recreational",
    "social",
}
VALID_KINETIC_CLASSES = {
    "holdoutPistol",
    "mediumPistol",
    "heavyPistol",
    "machinePistol",
    "submachineGun",
    "assaultRifle",
    "battleRifle",
    "machineGun",
    "sniperRifle",
}

_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_-]+")
_DICE_TOKEN_RE = re.compile(r"^[0-9]+(?:d[0-9]+)?(?:\s*[+\-*/]\s*[0-9]+(?:d[0-9]+)?)*$", re.IGNORECASE)


def _int(value: Any, default: int = 0, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def _clean_text(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _tagged_text(value: Any, fallback: str = "") -> str:
    text = _clean_text(value, fallback=fallback)
    if text.startswith(("i_", "m_")):
        return text
    return f"i_{text}"


def _sanitize_html(raw_html: str) -> str:
    content = (raw_html or "").strip()
    if not content:
        return ""
    if "<" not in content and ">" not in content:
        paragraphs = [f"<p>{escape(line.strip())}</p>" for line in content.splitlines() if line.strip()]
        return "".join(paragraphs)
    if nh3 is not None:
        return nh3.clean(content)
    return f"<p>{escape(re.sub(r'<[^>]+>', ' ', content).strip())}</p>"


def _tagged_html(raw_html: str) -> str:
    text = (raw_html or "").strip()
    if text.startswith(("h_", "m_")):
        return text
    return f"h_{_sanitize_html(text)}"


def _normalize_complexity(value: Any) -> str:
    val = str(value or "").strip().lower()
    if val in VALID_COMPLEXITIES:
        return val
    return "moderate"


def _normalize_size(value: Any, default: str = "medium") -> str:
    raw = str(value or "").strip()
    if raw in VALID_SIZES:
        return raw
    lowered = raw.lower().replace("_", "").replace("-", "").replace(" ", "")
    mapping = {
        "verysmall": "verySmall",
        "small": "small",
        "medium": "medium",
        "large": "large",
        "verylarge": "veryLarge",
    }
    return mapping.get(lowered, default)


def _normalize_dice(value: Any, default: str = "1d6") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    compact = re.sub(r"\s+", " ", raw).strip()
    if _DICE_TOKEN_RE.match(compact):
        return compact
    # Fall back gracefully for descriptive formulas like "1d10 + SOM/10"
    m = re.search(r"([0-9]+d[0-9]+(?:\s*[+\-]\s*[0-9]+)?)", compact, re.IGNORECASE)
    if m:
        return m.group(1)
    return default


def _build_gear_cost(system: dict[str, Any]) -> dict[str, Any]:
    return {
        "complexity": _normalize_complexity(system.get("complexity")),
        "isRestricted": bool(system.get("restricted")),
    }


def _build_ware_types(system: dict[str, Any]) -> list[str]:
    wt = str(system.get("wareType") or "").strip().lower()
    return [wt] if wt in VALID_PHYSICAL_WARES else []


def _build_gear_traits(system: dict[str, Any]) -> list[str]:
    traits: list[str] = []
    if system.get("concealable"):
        traits.append("concealable")
    if system.get("fragile"):
        traits.append("fragile")
    if system.get("singleUse"):
        traits.append("singleUse")
    if system.get("twoHanded"):
        traits.append("twoHanded")
    return traits


def _build_ranged_traits(system: dict[str, Any]) -> list[str]:
    traits: list[str] = []
    if system.get("fixed"):
        traits.append("fixed")
    if system.get("long"):
        traits.append("long")
    if system.get("noPointBlank"):
        traits.append("noPointBlank")
    if system.get("noClose"):
        traits.append("noClose")
    return traits


def _extract_attack_damage(attack: Any, *, armor_default: str = "kinetic", damage_default: str = "1d6") -> dict[str, Any]:
    att = attack if isinstance(attack, dict) else {}
    armor_used: list[str] = []
    armor_used_raw = att.get("armorUsed")
    if isinstance(armor_used_raw, str) and armor_used_raw in ("kinetic", "energy", "mental", "mesh"):
        armor_used = [armor_used_raw]
    elif isinstance(armor_used_raw, list):
        armor_used = [a for a in armor_used_raw if a in ("kinetic", "energy", "mental", "mesh")]
    if not armor_used:
        armor_used = [armor_default]

    damage_traits: list[str] = []
    if att.get("armorPiercing"):
        damage_traits.append("armorPiercing")
    if att.get("armorReducing"):
        damage_traits.append("armorReducing")

    attack_traits: list[str] = []
    raw_at = att.get("attackTraits")
    if isinstance(raw_at, list):
        for t in raw_at:
            ts = str(t).strip()
            if ts in ("blinding", "entangling", "knockdown", "pain", "shock", "stun") and ts not in attack_traits:
                attack_traits.append(ts)

    return {
        "type": "physical",
        "value": _normalize_dice(att.get("damageFormula"), default=damage_default),
        "attackTraits": attack_traits,
        "armorInteraction": {
            "armorUsed": armor_used,
            "damageTraits": damage_traits,
        },
    }


def _extract_firing_modes(attack: Any) -> list[str]:
    att = attack if isinstance(attack, dict) else {}
    raw = att.get("firingModes")
    valid = {"singleShot", "semiAuto", "burstFire", "fullAuto"}
    out: list[str] = []
    if isinstance(raw, dict):
        for k, enabled in raw.items():
            if enabled and k in valid and k not in out:
                out.append(k)
    elif isinstance(raw, list):
        for k in raw:
            if k in valid and k not in out:
                out.append(k)
    return out or ["semiAuto"]


def _build_morph_pools(system: dict[str, Any]) -> dict[str, int]:
    raw_pools = system.get("pools") if isinstance(system.get("pools"), dict) else {}
    return {
        "insight": _int(raw_pools.get("insight"), 0, minimum=0),
        "moxie": _int(raw_pools.get("moxie"), 0, minimum=0),
        "vigor": _int(raw_pools.get("vigor"), 0, minimum=0),
        "flex": _int(raw_pools.get("flex"), 0, minimum=0),
    }


def _build_inherent_armor(raw_armor: Any) -> dict[str, Any] | None:
    if not isinstance(raw_armor, dict):
        return None
    kinetic = _int(raw_armor.get("kinetic"), 0, minimum=0)
    energy = _int(raw_armor.get("energy"), 0, minimum=0)
    if kinetic <= 0 and energy <= 0:
        return None
    return {
        "kinetic": kinetic,
        "energy": energy,
        "isAccessory": bool(raw_armor.get("layerable") or raw_armor.get("isAccessory")),
    }


def _build_references(entry: Ep2Entry, pack_name: str) -> list[dict[str, Any]]:
    ref = (entry.reference or "").strip()
    if not ref:
        return []
    return [
        {
            "source": _tagged_text(pack_name, "Compendium"),
            "pages": [ref],
        }
    ]


def _make_design_key(entry: Ep2Entry, used_keys: set[str]) -> str:
    raw = _SAFE_KEY_RE.sub("-", (entry.entry_id or slugify(entry.name) or "entry").strip()).strip("-")
    if not raw:
        raw = f"entry-{entry.pk or 1}"
    base = raw[:48]
    candidate = base
    counter = 2
    while candidate in used_keys:
        suffix = f"-{counter}"
        candidate = f"{base[:48 - len(suffix)]}{suffix}"
        counter += 1
    used_keys.add(candidate)
    return candidate


def _convert_entry(entry: Ep2Entry, *, pack_name: str) -> tuple[str, dict[str, Any]] | None:
    """Convert one Ep2Entry into (meshnet_design_type, partial_design_dict)."""
    system = entry.system if isinstance(entry.system, dict) else {}
    raw_desc = entry.description or system.get("description") or ""
    common: dict[str, Any] = {
        "name": _tagged_text(entry.name, "Unnamed Entry"),
        "description": _tagged_html(str(raw_desc)),
        "references": _build_references(entry, pack_name),
    }
    cat = entry.category
    etype = (entry.entry_type or "").strip()

    # --- Morphs ---
    if cat == Ep2Entry.CATEGORY_MORPH and etype == "biological":
        acq = system.get("acquisition") if isinstance(system.get("acquisition"), dict) else {}
        phys = system.get("physicalHealth") if isinstance(system.get("physicalHealth"), dict) else {}
        cost_pts = _int(acq.get("cost"), 0, minimum=0)
        design: dict[str, Any] = {
            **common,
            "type": "biologicalBody",
            "category": _tagged_text(system.get("subtype") or "Biomorph", "Biomorph"),
            "cost": {"asMorph": {"points": cost_pts, "availability": []}},
            "durability": _int(phys.get("baseDurability"), 30, minimum=1),
            "pools": _build_morph_pools(system),
            "limbs": {
                "nonPrehensile": 0,
                "prehensile": _int(system.get("prehensileLimbs"), 2, minimum=0),
                "reachModifier": _int(system.get("reach"), 0, minimum=-60, maximum=60),
            },
            "size": _normalize_size(system.get("size"), "medium"),
        }
        armor = _build_inherent_armor(system.get("inherentArmor"))
        if armor:
            design["inherentArmor"] = armor
        return ("biologicalBody", design)

    if etype == "synthetic" and cat in (Ep2Entry.CATEGORY_MORPH, Ep2Entry.CATEGORY_GEAR):
        acq = system.get("acquisition") if isinstance(system.get("acquisition"), dict) else {}
        phys = system.get("physicalHealth") if isinstance(system.get("physicalHealth"), dict) else {}
        durability = _int(phys.get("baseDurability"), 25, minimum=1)
        pools = _build_morph_pools(system)
        if system.get("isSwarm"):
            cost_pts = _int(acq.get("cost"), 0, minimum=0)
            return (
                "swarm",
                {
                    **common,
                    "type": "swarm",
                    "category": _tagged_text(system.get("subtype") or "Swarm", "Swarm"),
                    "cost": {"asMorph": {"points": cost_pts, "availability": []}},
                    "durability": durability,
                    "isBiological": False,
                    "miteSize": "nano",
                    "pools": pools,
                },
            )
        shell_type = str(system.get("shellType") or "").strip().lower()
        subtype_label = _clean_text(system.get("subtype"), "Synthmorph" if shell_type == "synthmorph" else shell_type.title() or "Synthmorph")
        cost_obj: dict[str, Any] = {}
        if cat == Ep2Entry.CATEGORY_MORPH or shell_type == "synthmorph":
            cost_obj["asMorph"] = {"points": _int(acq.get("cost"), 0, minimum=0), "availability": []}
        if cat == Ep2Entry.CATEGORY_GEAR or shell_type in ("bot", "vehicle"):
            cost_obj["asGear"] = {
                "complexity": _normalize_complexity(acq.get("complexity") or system.get("complexity")),
                "isRestricted": bool(acq.get("restricted") or system.get("restricted")),
            }
        if not cost_obj:
            cost_obj["asMorph"] = {"points": _int(acq.get("cost"), 0, minimum=0), "availability": []}
        design = {
            **common,
            "type": "syntheticShell",
            "category": _tagged_text(subtype_label, "Synthmorph"),
            "cost": cost_obj,
            "durability": durability,
            "frame": "medium" if shell_type == "synthmorph" else "none",
            "pools": pools,
            "limbs": {
                "nonPrehensile": 0,
                "prehensile": _int(system.get("prehensileLimbs"), 2, minimum=0),
                "reachModifier": _int(system.get("reach"), 0, minimum=-60, maximum=60),
            },
            "sizes": [_normalize_size(system.get("size"), "medium")],
        }
        armor = _build_inherent_armor(system.get("inherentArmor"))
        if armor:
            design["inherentArmor"] = armor
        passengers = _int(system.get("passengers"), 0, minimum=0)
        is_exo = subtype_label.lower() in ("exoskeleton", "hardsuit")
        if passengers > 0 or is_exo:
            design["vehicle"] = {
                "isExoskeleton": is_exo,
                "passengers": max(1, passengers) if is_exo else passengers,
            }
        return ("syntheticShell", design)

    if cat == Ep2Entry.CATEGORY_MORPH and etype == "infomorph":
        acq = system.get("acquisition") if isinstance(system.get("acquisition"), dict) else {}
        mesh_h = system.get("meshHealth") if isinstance(system.get("meshHealth"), dict) else {}
        return (
            "digitalForm",
            {
                **common,
                "type": "digitalForm",
                "category": _tagged_text("Infomorph", "Infomorph"),
                "cost": {"asMorph": {"points": _int(acq.get("cost"), 0, minimum=0), "availability": []}},
                "durability": _int(mesh_h.get("baseDurability"), 20, minimum=1),
                "pools": _build_morph_pools(system),
            },
        )

    # --- Armor & Physical Tech / Augmentations ---
    if etype == "armor":
        av = system.get("armorValues") if isinstance(system.get("armorValues"), dict) else {}
        return (
            "armorMod",
            {
                **common,
                "type": "armorMod",
                "armor": {
                    "kinetic": _int(av.get("kinetic"), 0, minimum=0),
                    "energy": _int(av.get("energy"), 0, minimum=0),
                },
                "cost": _build_gear_cost(system),
            },
        )

    if etype == "physicalTech":
        cat_label = _clean_text(system.get("category"), "Gear")
        ware_types = _build_ware_types(system)
        if system.get("fabricator") or "fabricator" in cat_label.lower():
            return (
                "fabricator",
                {
                    **common,
                    "type": "fabricator",
                    "category": _tagged_text(cat_label, "Nanofabricators"),
                    "cost": _build_gear_cost(system),
                    "defaultSize": _normalize_size(system.get("size"), "small") if system.get("size") else None,
                    "fabricatorType": "general",
                },
            )
        if ware_types or "augment" in cat_label.lower():
            return (
                "augmentation",
                {
                    **common,
                    "type": "augmentation",
                    "category": _tagged_text(cat_label, "Augmentation"),
                    "cost": _build_gear_cost(system),
                    "size": _normalize_size(system.get("size"), "small") if system.get("size") else None,
                    "wareTypes": ware_types or ["cyberware"],
                },
            )
        return (
            "tech",
            {
                **common,
                "type": "tech",
                "category": _tagged_text(cat_label, "Everyday Tech"),
                "cost": _build_gear_cost(system),
                "size": _normalize_size(system.get("size"), "small") if system.get("size") else None,
            },
        )

    # --- Weapons & Ammo ---
    if etype == "beamWeapon":
        p_att = system.get("primaryAttack") if isinstance(system.get("primaryAttack"), dict) else {}
        attacks = [
            {
                "label": _tagged_text(p_att.get("label") or "Primary"),
                "notes": _tagged_text(p_att.get("notes") or ""),
                "range": _int(system.get("range") or p_att.get("range"), 50, minimum=1),
                "firingModes": _extract_firing_modes(p_att),
                "damage": _extract_attack_damage(p_att, armor_default="energy", damage_default="1d10"),
            }
        ]
        if system.get("hasSecondaryAttack") and isinstance(system.get("secondaryAttack"), dict):
            s_att = system["secondaryAttack"]
            attacks.append(
                {
                    "label": _tagged_text(s_att.get("label") or "Secondary"),
                    "notes": _tagged_text(s_att.get("notes") or ""),
                    "range": _int(s_att.get("range") or system.get("range"), 50, minimum=1),
                    "firingModes": _extract_firing_modes(s_att),
                    "damage": _extract_attack_damage(s_att, armor_default="energy", damage_default="1d10"),
                }
            )
        return (
            "beamWeapon",
            {
                **common,
                "type": "beamWeapon",
                "attacks": attacks,
                "batteryCapacity": _int(
                    (system.get("battery") or {}).get("max") if isinstance(system.get("battery"), dict) else 10,
                    10,
                    minimum=1,
                ),
                "cost": _build_gear_cost(system),
                "gearTraits": _build_gear_traits(system),
                "rangedTraits": _build_ranged_traits(system),
                "wareTypes": _build_ware_types(system),
                "_skillHint": "Guns",
            },
        )

    if etype in ("firearm", "railgun"):
        p_att = system.get("primaryAttack") if isinstance(system.get("primaryAttack"), dict) else {}
        ammo_info = system.get("ammo") if isinstance(system.get("ammo"), dict) else {}
        ammo_class = str(ammo_info.get("ammoClass") or "").strip()
        if ammo_class not in VALID_KINETIC_CLASSES:
            ammo_class = "mediumPistol"
        shape = {
            "ammoCapacity": _int(ammo_info.get("max"), 12, minimum=1),
            "damage": _extract_attack_damage(p_att, armor_default="kinetic", damage_default="2d10"),
            "description": _tagged_html(""),
            "firingModes": _extract_firing_modes(p_att),
            "gearTraits": _build_gear_traits(system),
            "label": _tagged_text(system.get("shapeName") or "Standard"),
            "range": _int(system.get("range"), 50, minimum=1),
            "rangedTraits": _build_ranged_traits(system),
            "weaponClass": ammo_class,
        }
        out: dict[str, Any] = {
            **common,
            "type": etype,
            "cost": _build_gear_cost(system),
            "shapes": [shape],
            "wareTypes": _build_ware_types(system),
            "_skillHint": "Guns",
        }
        if etype == "railgun":
            bat = system.get("battery") if isinstance(system.get("battery"), dict) else {}
            out["batteryCapacity"] = _int(bat.get("max"), 200, minimum=1)
        return (etype, out)

    if etype == "meleeWeapon":
        p_att = system.get("primaryAttack") if isinstance(system.get("primaryAttack"), dict) else {}
        attacks = [
            {
                "addsToUnarmedDamage": bool(system.get("augmentUnarmed")),
                "damage": _extract_attack_damage(p_att, armor_default="kinetic", damage_default="1d6"),
                "label": _tagged_text(p_att.get("label") or "Strike"),
                "notes": _tagged_text(p_att.get("notes") or ""),
            }
        ]
        if system.get("hasSecondaryAttack") and isinstance(system.get("secondaryAttack"), dict):
            s_att = system["secondaryAttack"]
            attacks.append(
                {
                    "addsToUnarmedDamage": bool(system.get("augmentUnarmed")),
                    "damage": _extract_attack_damage(s_att, armor_default="kinetic", damage_default="1d6"),
                    "label": _tagged_text(s_att.get("label") or "Secondary"),
                    "notes": _tagged_text(s_att.get("notes") or ""),
                }
            )
        return (
            "meleeWeapon",
            {
                **common,
                "type": "meleeWeapon",
                "acceptsPayload": bool(system.get("acceptsPayload")),
                "attacks": attacks,
                "coatingIsPermanent": False,
                "cost": _build_gear_cost(system),
                "gearTraits": _build_gear_traits(system),
                "isImprovised": bool(system.get("improvised")),
                "isTouchOnly": bool(system.get("touchOnly")),
                "reachBonus": _int(system.get("reachBonus"), 0, minimum=0),
                "wareTypes": _build_ware_types(system),
                "_skillHint": _clean_text(system.get("exoticSkill"), "Melee"),
            },
        )

    if etype == "seekerWeapon":
        p_ammo = system.get("primaryAmmo") if isinstance(system.get("primaryAmmo"), dict) else {}
        raw_size = str(p_ammo.get("size") or "micro").strip().lower()
        exp_size = raw_size if raw_size in ("micro", "mini", "standard") else "micro"
        fmode = "singleShot" if system.get("firingMode") == "singleShot" else "semiAuto"
        return (
            "seekerWeapon",
            {
                **common,
                "type": "seekerWeapon",
                "ammoModes": [
                    {
                        "capacity": _int(p_ammo.get("max"), 6, minimum=1),
                        "firingMode": fmode,
                        "range": _int(system.get("range"), 150, minimum=1),
                        "type": exp_size,
                    }
                ],
                "cost": _build_gear_cost(system),
                "gearTraits": _build_gear_traits(system),
                "rangedTraits": _build_ranged_traits(system),
                "wareTypes": _build_ware_types(system),
                "_skillHint": "Guns",
            },
        )

    if etype == "sprayWeapon":
        p_att = system.get("primaryAttack") if isinstance(system.get("primaryAttack"), dict) else {}
        ammo_info = system.get("ammo") if isinstance(system.get("ammo"), dict) else {}
        payload_use = str(system.get("payloadUse") or "").strip().lower()
        if payload_use == "substance":
            descriptor = {
                "type": "substance",
                "capacity": _int(ammo_info.get("max"), 10, minimum=1),
                "dosesPerShot": _int(system.get("dosesPerShot"), 1, minimum=1),
                "augmentAttack": False,
            }
        else:
            descriptor = {
                "type": "standard",
                "capacity": _int(ammo_info.get("max"), 10, minimum=1),
            }
        return (
            "sprayWeapon",
            {
                **common,
                "type": "sprayWeapon",
                "ammoDescriptor": descriptor,
                "attacks": [
                    {
                        "damage": _extract_attack_damage(p_att, armor_default="kinetic", damage_default="1d10"),
                        "firingModes": _extract_firing_modes(p_att),
                        "label": _tagged_text(p_att.get("label") or "Spray"),
                        "notes": _tagged_text(p_att.get("notes") or ""),
                    }
                ],
                "cost": _build_gear_cost(system),
                "gearTraits": _build_gear_traits(system),
                "range": _int(system.get("range"), 15, minimum=1),
                "rangedTraits": _build_ranged_traits(system),
                "wareTypes": _build_ware_types(system),
                "_skillHint": "Guns",
            },
        )

    if etype == "explosive":
        p_att = system.get("primaryAttack") if isinstance(system.get("primaryAttack"), dict) else {}
        raw_etype = str(system.get("explosiveType") or "generic").strip().lower()
        exp_type = raw_etype if raw_etype in ("grenade", "missile", "generic") else "generic"
        raw_esize = str(system.get("size") or "standard").strip().lower()
        exp_size = raw_esize if raw_esize in ("micro", "mini", "standard") else "standard"
        return (
            "explosive",
            {
                **common,
                "type": "explosive",
                "canCarryPayload": bool(system.get("useSubstance")),
                "category": _tagged_text(exp_type.title(), "Explosive"),
                "cost": _build_gear_cost(system),
                "forms": [
                    {
                        "type": exp_type,
                        "size": exp_size,
                        "units": _int(system.get("unitsPerComplexity") or system.get("quantity"), 5, minimum=1),
                        "attacks": [
                            {
                                "damage": _extract_attack_damage(p_att, armor_default="kinetic", damage_default="3d10"),
                                "label": _tagged_text(p_att.get("label") or "Detonate"),
                                "notes": _tagged_text(p_att.get("notes") or ""),
                            }
                        ],
                    }
                ],
            },
        )

    if etype == "firearmAmmo":
        ammo_class = str(system.get("ammoClass") or "").strip().lower()
        weapon_type = "railgun" if "rail" in ammo_class or "railgun" in entry.name.lower() else "firearm"
        return (
            "kineticAmmo",
            {
                **common,
                "type": "kineticAmmo",
                "canCarryPayload": bool(system.get("carryPayload")),
                "cost": _build_gear_cost(system),
                "forms": [{"attackTraits": [], "damageTraits": [], "label": _tagged_text("Standard"), "notes": _tagged_text(""), "rangedTraits": []}],
                "units": _int(system.get("roundsPerComplexity") or system.get("quantity"), 100, minimum=1),
                "weaponType": weapon_type,
            },
        )

    if etype == "physicalService":
        svc_type = "mesh" if system.get("serviceType") == "fakeEgoId" else "physical"
        return (
            "service",
            {
                **common,
                "type": "service",
                "category": _tagged_text("Fake Ego ID" if system.get("serviceType") == "fakeEgoId" else "Service"),
                "cost": _build_gear_cost(system),
                "serviceType": svc_type,
            },
        )

    if etype == "software":
        sw_raw = str(system.get("softwareType") or "").strip()
        cat_raw = _clean_text(system.get("category"), "Software")
        sw_map = {
            "app": "app",
            "appAsWare": "app",
            "meshware": "meshware",
            "meshService": "meshware",
            "scorcher": "scorcher",
            "skillsoft": "skillsoft",
            "tacnet": "tacnet",
        }
        sw_type = sw_map.get(sw_raw)
        if not sw_type:
            lower_cat = cat_raw.lower()
            if "tacnet" in lower_cat:
                sw_type = "tacnet"
            elif "scorcher" in lower_cat:
                sw_type = "scorcher"
            elif "meshware" in lower_cat or "augment" in lower_cat:
                sw_type = "meshware"
            else:
                sw_type = "app"
        return (
            "software",
            {
                **common,
                "type": "software",
                "category": _tagged_text(cat_raw, "Software"),
                "cost": _build_gear_cost(system),
                "softwareType": sw_type,
            },
        )

    # --- Substances ---
    if cat == Ep2Entry.CATEGORY_SUBSTANCE or etype == "substance":
        sub_type = str(system.get("substanceType") or "chemical").strip().lower()
        classification = str(system.get("classification") or "biochem").strip().lower()
        if classification not in ("biochem", "nano", "electronic"):
            classification = "biochem"
        units = _int(system.get("quantityPerCost") or system.get("quantity"), 5, minimum=1)
        if sub_type == "drug":
            dcat = str(system.get("category") or "recreational").strip().lower()
            if dcat == "nanodrug":
                dcat = "nano"
            if dcat not in VALID_DRUG_CATEGORIES:
                dcat = "recreational"
            return (
                "drug",
                {
                    **common,
                    "type": "drug",
                    "category": dcat,
                    "classification": classification,
                    "cost": _build_gear_cost(system),
                },
            )
        if sub_type == "toxin":
            return (
                "toxin",
                {
                    **common,
                    "type": "toxin",
                    "classification": classification,
                    "cost": _build_gear_cost(system),
                    "units": units,
                },
            )
        return (
            "chemical",
            {
                **common,
                "type": "chemical",
                "cost": _build_gear_cost(system),
                "units": units,
            },
        )

    # --- Traits ---
    if cat == Ep2Entry.CATEGORY_TRAIT or etype == "trait":
        t_type = "negative" if str(system.get("traitType") or "").strip().lower() == "negative" else "positive"
        raw_sub = str(system.get("subtype") or "").strip().lower()
        if raw_sub == "ego":
            t_subtype = "ego"
        elif raw_sub == "morph":
            t_subtype = "morph"
        else:
            t_subtype = "ego/morph"
        levels_out: list[dict[str, Any]] = []
        raw_levels = system.get("levels")
        if isinstance(raw_levels, list) and raw_levels:
            for lvl in raw_levels[:4]:
                if isinstance(lvl, dict):
                    pts = _int(lvl.get("cost") or lvl.get("pointValue") or lvl.get("points"), 1, minimum=1)
                    levels_out.append({"pointValue": pts, "isGamemasterOnly": bool(entry.is_storyteller_only)})
        if not levels_out:
            levels_out = [{"pointValue": _int(system.get("cost"), 1, minimum=1), "isGamemasterOnly": bool(entry.is_storyteller_only)}]
        return (
            "trait",
            {
                **common,
                "type": "trait",
                "traitType": t_type,
                "traitSubtype": t_subtype,
                "levels": levels_out,
            },
        )

    # --- Psi Sleights ---
    if cat == Ep2Entry.CATEGORY_SLEIGHT or etype == "sleight":
        s_type = str(system.get("sleightType") or "chi").strip().lower()
        raw_action = str(system.get("action") or "complex").strip().lower()
        action_type = raw_action if raw_action in ("quick", "complex", "task") else "complex"
        raw_dur = str(system.get("duration") or "instant").strip().lower()
        if raw_dur == "sustained":
            duration: dict[str, Any] = {"type": "sustained"}
        elif raw_dur in ("actionturns", "actionturn"):
            duration = {"type": "wilBased", "divisor": 5, "unit": "actionTurn"}
        elif raw_dur == "minutes":
            duration = {"type": "wilBased", "divisor": 5, "unit": "minutes"}
        elif raw_dur == "hours":
            duration = {"type": "wilBased", "divisor": 5, "unit": "hours"}
        else:
            duration = {"type": "instant"}

        if s_type == "epsilon":
            return (
                "epsilonSleight",
                {
                    **common,
                    "type": "epsilonSleight",
                    "actionType": action_type,
                    "duration": duration,
                },
            )
        if s_type == "gamma":
            return (
                "gammaSleight",
                {
                    **common,
                    "type": "gammaSleight",
                    "actionType": action_type,
                    "duration": duration,
                    "infectionModifier": _int(system.get("infectionMod"), 2, minimum=0, maximum=100),
                },
            )
        return (
            "chiSleight",
            {
                **common,
                "type": "chiSleight",
            },
        )

    # --- Sub-strains ---
    if cat == Ep2Entry.CATEGORY_SPECIAL and etype == "psi":
        return (
            "exovirusSubstrain",
            {
                **common,
                "type": "exovirusSubstrain",
            },
        )

    # --- Generic custom / misc fallback ---
    if entry.is_custom:
        return (
            "tech",
            {
                **common,
                "type": "tech",
                "category": _tagged_text(cat.title() if cat else "Custom", "Custom"),
                "cost": _build_gear_cost(system),
            },
        )

    return None


def export_meshnet_pack_payload(pack: DesignPack, *, include_storyteller: bool = True) -> dict[str, Any]:
    """Serialize a DesignPack and its Ep2Entry records into a MeshNet-compatible DesignPackPartial."""
    designs: dict[str, dict[str, dict[str, Any]]] = {}
    used_keys_by_type: dict[str, set[str]] = {}

    entries_qs = pack.entries.all().order_by("category", "entry_type", "name", "id")
    if not include_storyteller:
        entries_qs = entries_qs.filter(is_storyteller_only=False)

    converted_count = 0
    for entry in entries_qs:
        converted = _convert_entry(entry, pack_name=pack.name)
        if converted is None:
            continue
        design_type, design_data = converted
        bucket = designs.setdefault(design_type, {})
        used_keys = used_keys_by_type.setdefault(design_type, set())
        key = _make_design_key(entry, used_keys)
        bucket[key] = design_data
        converted_count += 1

    metadata = pack.metadata if isinstance(pack.metadata, dict) else {}
    dep_ids = metadata.get("dependency_ids")
    if not isinstance(dep_ids, list):
        dep_ids = [] if pack.slug == DesignPack.TIER_CRB else [DesignPack.TIER_CRB]
    else:
        dep_ids = [str(x) for x in dep_ids if isinstance(x, str) and x.strip()]

    refs: list[dict[str, Any]] = []
    if pack.source_url:
        refs.append({"source": _tagged_text(pack.name), "pages": [], "url": pack.source_url})

    return {
        "id": pack.slug,
        "slug": pack.slug,
        "tier": pack.tier,
        "isOfficial": bool(pack.is_official),
        "isStorytellerOnly": bool(pack.is_storyteller_only),
        "convertedCount": converted_count,
        "pack": {
            "name": _tagged_text(pack.name),
            "description": _tagged_html(pack.description or ""),
            "references": refs,
            "dependencyIds": dep_ids,
            "isGamemasterOnly": bool(pack.is_storyteller_only or pack.tier == DesignPack.TIER_CRB_STORYTELLER),
            "designs": designs,
        },
    }


def get_meshnet_packs_payload(user, *, include_storyteller: bool = True) -> list[dict[str, Any]]:
    """Return all visible DesignPacks formatted for MeshNet hydration."""
    packs = visible_design_packs_qs(user, include_storyteller=include_storyteller).order_by("-is_official", "tier", "name")
    return [export_meshnet_pack_payload(pack, include_storyteller=include_storyteller) for pack in packs]
