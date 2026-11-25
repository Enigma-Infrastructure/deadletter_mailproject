"""Service helpers for Spacemarches DesignPacks (rulebook tiers + custom packs)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.utils.text import slugify

from spacemarches.models import DesignPack, Ep2Entry

STORYTELLER_PACK_SLUGS = {"creatures", "psi-epsilon-sleights"}
RESERVED_OFFICIAL_SLUGS = {"ep-crb", "ep-crb-storyteller", "ep-copt", "spacemarches"}
VALID_ENTRY_CATEGORIES = {choice[0] for choice in Ep2Entry.CATEGORY_CHOICES}

CANONICAL_PACK_DEFS: list[dict[str, Any]] = [
    {
        "slug": "ep-crb",
        "name": "EP2e CRB",
        "description": (
            "Player-facing morphs, gear, augmentations, traits, psi sleights, and substances "
            "from the Eclipse Phase 2nd Edition Core Rulebook."
        ),
        "tier": DesignPack.TIER_CRB,
        "is_storyteller_only": False,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "https://github.com/Bubz43/ep2e",
        "metadata": {"dependency_ids": []},
    },
    {
        "slug": "ep-crb-storyteller",
        "name": "EP2e CRB (Storyteller)",
        "description": (
            "Threats, creatures, epsilon sleights, and Storyteller-only material from the "
            "Eclipse Phase 2nd Edition Core Rulebook."
        ),
        "tier": DesignPack.TIER_CRB_STORYTELLER,
        "is_storyteller_only": True,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "https://github.com/Bubz43/ep2e",
        "metadata": {"dependency_ids": ["ep-crb"]},
    },
    {
        "slug": "ep-copt",
        "name": "EP2e Character Options",
        "description": (
            "Expanded morphs, traits, augmentations, and Life-Path options from Eclipse Phase "
            "2e Character Options (staged for Compendium import)."
        ),
        "tier": DesignPack.TIER_COPT,
        "is_storyteller_only": False,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "https://github.com/TheGam1ngWizard/ep2e-virtual",
        "metadata": {"dependency_ids": ["ep-crb"], "status": "queued_import"},
    },
    {
        "slug": "spacemarches",
        "name": "Spacemarches",
        "description": (
            "Official Spacemarches campaign pack for custom setting gear, morph variants, "
            "traits, and homebrew additions."
        ),
        "tier": DesignPack.TIER_SPACEMARCHES,
        "is_storyteller_only": False,
        "is_official": True,
        "is_public": True,
        "is_active": True,
        "source_url": "",
        "metadata": {"dependency_ids": ["ep-crb"]},
    },
]


def ensure_canonical_design_packs() -> dict[str, DesignPack]:
    """Ensure the four canonical DesignPacks exist without clobbering staff customizations."""
    packs: dict[str, DesignPack] = {}
    for spec in CANONICAL_PACK_DEFS:
        pack_obj, _ = DesignPack.objects.get_or_create(
            slug=spec["slug"],
            defaults=spec,
        )
        packs[spec["slug"]] = pack_obj
    return packs


def is_storyteller_entry_payload(pack_slug: str | None, system_data: Any = None) -> bool:
    """Return True if a seeded entry belongs in the Storyteller-only tier."""
    slug = (pack_slug or "").strip().lower()
    if slug in STORYTELLER_PACK_SLUGS:
        return True
    if isinstance(system_data, dict) and bool(system_data.get("isGamemasterOnly")):
        return True
    return False


def visible_design_packs_qs(user, *, include_storyteller: bool = True) -> QuerySet[DesignPack]:
    """Return active DesignPacks visible to the given user."""
    qs = DesignPack.objects.filter(is_active=True)
    if not include_storyteller:
        qs = qs.filter(is_storyteller_only=False)
    if user and getattr(user, "is_authenticated", False):
        if getattr(user, "is_staff", False):
            return qs
        return qs.filter(Q(is_public=True) | Q(owner=user))
    return qs.filter(is_public=True)


def visible_ep2_entries_qs(user, *, include_storyteller: bool = False) -> QuerySet[Ep2Entry]:
    """Return Ep2Entry rows visible to the user, gating private packs and Storyteller items."""
    qs = Ep2Entry.objects.select_related("design_pack")
    if user and getattr(user, "is_authenticated", False):
        if getattr(user, "is_staff", False):
            qs = qs.filter(Q(design_pack__isnull=True) | Q(design_pack__is_active=True))
        else:
            qs = qs.filter(
                Q(design_pack__isnull=True)
                | Q(design_pack__is_active=True, design_pack__is_public=True)
                | Q(design_pack__is_active=True, design_pack__owner=user)
            )
    else:
        qs = qs.filter(Q(design_pack__isnull=True) | Q(design_pack__is_active=True, design_pack__is_public=True))

    if not include_storyteller:
        qs = qs.filter(is_storyteller_only=False).exclude(design_pack__is_storyteller_only=True)
    return qs


def can_edit_design_pack(user, pack: DesignPack) -> bool:
    """Return True if user is permitted to create/modify entries inside this DesignPack."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if pack.slug == DesignPack.TIER_SPACEMARCHES:
        return bool(getattr(user, "is_staff", False))
    if pack.is_official:
        return False
    return pack.owner_id == user.id or bool(getattr(user, "is_staff", False))


def _unique_pack_slug(base_text: str) -> str:
    base = slugify(base_text)[:54] or "custom-pack"
    if base in RESERVED_OFFICIAL_SLUGS:
        base = f"custom-{base}"[:54]
    candidate = base
    while DesignPack.objects.filter(slug=candidate).exists():
        candidate = f"{base[:47]}-{uuid.uuid4().hex[:6]}"
    return candidate


def create_custom_design_pack(
    user,
    *,
    name: str,
    slug: str = "",
    description: str = "",
    is_storyteller_only: bool = False,
    is_public: bool = True,
) -> DesignPack:
    """Create a user-owned custom DesignPack."""
    clean_name = (name or "").strip()[:120]
    if not clean_name:
        raise ValueError("Pack name is required.")
    raw_slug = (slug or "").strip()
    if raw_slug:
        normalized = slugify(raw_slug)[:64]
        if not normalized or normalized in RESERVED_OFFICIAL_SLUGS:
            raise ValueError("Invalid or reserved pack slug.")
        if DesignPack.objects.filter(slug=normalized).exists():
            raise ValueError(f"A pack with slug '{normalized}' already exists.")
        final_slug = normalized
    else:
        final_slug = _unique_pack_slug(f"custom-{clean_name}")

    return DesignPack.objects.create(
        slug=final_slug,
        name=clean_name,
        description=(description or "").strip(),
        tier=DesignPack.TIER_CUSTOM,
        is_storyteller_only=bool(is_storyteller_only),
        is_official=False,
        is_public=bool(is_public),
        is_active=True,
        owner=user if (user and getattr(user, "is_authenticated", False)) else None,
        metadata={"dependency_ids": ["ep-crb"]},
    )


def create_or_update_custom_entry(user, design_pack: DesignPack, data: dict[str, Any]) -> tuple[Ep2Entry, bool]:
    """Create or update a custom Ep2Entry inside an editable DesignPack."""
    if not can_edit_design_pack(user, design_pack):
        raise PermissionError("You do not have permission to edit this design pack.")

    name = (data.get("name") or "").strip()[:255]
    if not name:
        raise ValueError("Entry name is required.")

    category = (data.get("category") or Ep2Entry.CATEGORY_GEAR).strip().lower()
    if category not in VALID_ENTRY_CATEGORIES:
        raise ValueError(f"Unsupported category '{category}'.")

    pack_group = slugify((data.get("pack") or "").strip())[:64] or design_pack.slug
    entry_type = (data.get("entry_type") or "").strip()[:64]
    reference = (data.get("reference") or "").strip()[:255]
    description = (data.get("description") or "").strip()
    is_storyteller_only = bool(data.get("is_storyteller_only")) or design_pack.is_storyteller_only

    raw_system = data.get("system")
    if isinstance(raw_system, str):
        raw_system = raw_system.strip()
        if raw_system:
            try:
                parsed = json.loads(raw_system)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid system JSON: {exc}") from exc
            if not isinstance(parsed, dict):
                raise ValueError("System JSON must be a JSON object.")
            system_payload = parsed
        else:
            system_payload = {}
    elif isinstance(raw_system, dict):
        system_payload = raw_system
    elif raw_system is None:
        system_payload = {}
    else:
        raise ValueError("System payload must be a JSON object.")

    requested_entry_id = (data.get("entry_id") or "").strip()[:64]
    source_name = "spacemarches" if design_pack.slug == DesignPack.TIER_SPACEMARCHES else "custom"

    if requested_entry_id:
        existing = Ep2Entry.objects.filter(entry_id=requested_entry_id).first()
        if existing:
            if existing.design_pack_id != design_pack.id:
                raise ValueError(f"Entry ID '{requested_entry_id}' already belongs to another pack.")
            existing.name = name
            existing.category = category
            existing.pack = pack_group
            existing.entry_type = entry_type
            existing.reference = reference
            existing.description = description
            existing.is_storyteller_only = is_storyteller_only
            existing.system = system_payload
            existing.save()
            return existing, False
        entry_id = requested_entry_id
    else:
        slug_part = slugify(name)[:24] or "entry"
        entry_id = f"{design_pack.slug[:20]}-{slug_part}-{uuid.uuid4().hex[:6]}"[:64]

    entry = Ep2Entry.objects.create(
        design_pack=design_pack,
        source=source_name,
        pack=pack_group,
        entry_id=entry_id,
        name=name,
        entry_type=entry_type,
        category=category,
        description=description,
        reference=reference,
        is_storyteller_only=is_storyteller_only,
        is_custom=True,
        created_by=user if (user and getattr(user, "is_authenticated", False)) else None,
        system=system_payload,
    )
    return entry, True


def serialize_design_pack(pack: DesignPack, *, entry_count: int | None = None) -> dict[str, Any]:
    """Serialize DesignPack metadata for API and directory views."""
    count_val = entry_count if entry_count is not None else getattr(pack, "entry_count", None)
    if count_val is None:
        count_val = pack.entries.count()
    return {
        "slug": pack.slug,
        "name": pack.name,
        "description": pack.description,
        "tier": pack.tier,
        "tier_label": pack.get_tier_display(),
        "is_storyteller_only": pack.is_storyteller_only,
        "is_official": pack.is_official,
        "is_public": pack.is_public,
        "owner": pack.owner.username if pack.owner_id else "",
        "source_url": pack.source_url,
        "metadata": pack.metadata or {},
        "entry_count": count_val,
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else "",
    }


def export_design_pack_payload(design_pack: DesignPack) -> dict[str, Any]:
    """Export a DesignPack and all of its Ep2Entry records in portable JSON format."""
    entries = list(design_pack.entries.order_by("category", "pack", "name"))
    return {
        "schema": "spacemarches-design-pack/v1",
        "pack": serialize_design_pack(design_pack, entry_count=len(entries)),
        "entries": [
            {
                "entry_id": entry.entry_id,
                "name": entry.name,
                "category": entry.category,
                "pack": entry.pack,
                "entry_type": entry.entry_type,
                "reference": entry.reference,
                "description": entry.description,
                "is_storyteller_only": entry.is_storyteller_only,
                "system": entry.system or {},
            }
            for entry in entries
        ],
    }


def import_design_pack_payload(
    user,
    raw_payload: str | dict[str, Any],
    *,
    target_pack: DesignPack | None = None,
) -> tuple[DesignPack, int, int]:
    """Import a spacemarches-design-pack/v1 JSON payload into a custom or target pack."""
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionError("Authentication is required to import design packs.")

    if isinstance(raw_payload, str):
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid pack JSON: {exc}") from exc
    elif isinstance(raw_payload, dict):
        payload = raw_payload
    else:
        raise ValueError("Pack payload must be a JSON object.")

    if not isinstance(payload, dict):
        raise ValueError("Pack payload must be a JSON object.")

    pack_meta = payload.get("pack") if isinstance(payload.get("pack"), dict) else {}
    entries_data = payload.get("entries")
    if not isinstance(entries_data, list):
        raise ValueError("Pack JSON must contain an 'entries' list.")
    if len(entries_data) > 500:
        raise ValueError("Import limit exceeded (maximum 500 entries per pack import).")

    if target_pack is not None:
        if not can_edit_design_pack(user, target_pack):
            raise PermissionError("You do not have permission to import into this design pack.")
        pack_obj = target_pack
    else:
        pack_name = (pack_meta.get("name") or "").strip()[:120]
        if not pack_name:
            raise ValueError("Pack JSON must include 'pack.name'.")
        desired_slug = (pack_meta.get("slug") or "").strip()
        if desired_slug and (
            desired_slug in RESERVED_OFFICIAL_SLUGS or DesignPack.objects.filter(slug=desired_slug).exists()
        ):
            desired_slug = ""
        pack_obj = create_custom_design_pack(
            user,
            name=pack_name,
            slug=desired_slug,
            description=(pack_meta.get("description") or "").strip(),
            is_storyteller_only=bool(pack_meta.get("is_storyteller_only")),
            is_public=bool(pack_meta.get("is_public", True)),
        )

    created = 0
    updated = 0
    for idx, item in enumerate(entries_data):
        if not isinstance(item, dict):
            raise ValueError(f"Entry #{idx + 1} must be a JSON object.")
        # Avoid colliding with official entry IDs from other packs during fresh imports
        item_copy = dict(item)
        raw_id = (item_copy.get("entry_id") or "").strip()
        if raw_id and Ep2Entry.objects.filter(entry_id=raw_id).exclude(design_pack=pack_obj).exists():
            item_copy["entry_id"] = ""
        _, was_created = create_or_update_custom_entry(user, pack_obj, item_copy)
        if was_created:
            created += 1
        else:
            updated += 1

    return pack_obj, created, updated


def get_design_packs_with_counts(user, *, include_storyteller: bool = True) -> list[dict[str, Any]]:
    """Return serialized DesignPacks visible to user with visible entry counts."""
    qs = visible_design_packs_qs(user, include_storyteller=include_storyteller)
    entry_filter = Q() if include_storyteller else Q(entries__is_storyteller_only=False)
    qs = qs.annotate(visible_entry_count=Count("entries", filter=entry_filter)).select_related("owner")
    return [
        serialize_design_pack(pack, entry_count=pack.visible_entry_count)
        for pack in qs
    ]
