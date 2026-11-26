import json
from pathlib import Path
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from .markdown_utils import render_markdown_inline_safe, render_markdown_safe
from .models import (
    ArchiveEntry,
    CharacterDossier,
    DesignPack,
    DiscordLink,
    EclipsePhaseCensus,
    Ep2Entry,
    ForumPost,
    ForumThread,
    GeneratedCharacter,
    ProtectionAccessLog,
)
from .census import (
    get_all_census_questions,
    get_census_attribution,
    get_census_chapter,
    get_census_chapters,
    get_census_meta,
    get_chapter_questions,
)
from .services.census_service import (
    compute_census_stats,
    create_census,
    export_census_html,
    export_census_json,
    export_census_markdown,
    normalize_census_record,
    save_census_answer,
)
from .questionnaire import (
    get_all_questions,
    get_attribution_notice,
    get_categories,
    get_children,
    get_core_questions,
    get_question,
    get_question_temporal_defaults,
)
from .selectors import get_user_spacemarches_summary
from .services.character_cross_sync import (
    CENSUS_TO_DOSSIER_MAP,
    DOSSIER_TO_CENSUS_MAP,
    backfill_linked_census_and_dossier,
    build_sheet_prompt_context,
    compute_pending_sheet_changes,
    get_census_question_sheet_hint,
    get_dossier_question_sheet_hint,
    get_primary_linked_character_for_census,
    get_primary_linked_character_for_dossier,
)
from .services.character_sync_service import (
    export_generated_character_html,
    export_generated_character_markdown,
    get_sheet_skill_pack_choices,
    link_character_to_dossier,
    save_generated_character,
    serialize_generated_character,
    update_sheet_profile_fields,
)
from .services.dossier_service import (
    ENTRY_KIND_CHARACTER_CREATION,
    ENTRY_KIND_CHOICES,
    ENTRY_KIND_POST_ACTION_REPORT,
    STARDATE_ERA_AUTO,
    STARDATE_ERA_CHOICES,
    STARDATE_ERA_POST_FALL,
    _normalize_existing_record,
    compute_dossier_stats,
    export_dossier_markdown,
    generate_discord_link_code,
    get_dossier_progression_summary,
    reassign_dossier_control,
    save_dossier_answer,
)
from .services.design_pack_service import (
    can_edit_design_pack,
    create_custom_design_pack,
    create_or_update_custom_entry,
    ensure_canonical_design_packs,
    export_design_pack_payload,
    get_design_packs_with_counts,
    import_design_pack_payload,
    serialize_design_pack,
    visible_design_packs_qs,
    visible_ep2_entries_qs,
)
from .services.ep2_service import (
    extract_ep2_highlights,
    format_ep2_system_json,
    format_pack_label,
    get_ep2_catalog_summary,
    get_ep2_source_url,
    order_ep2_queryset,
    sanitize_ep2_html,
    strip_ep2_text,
)
from .services.game_sync_service import load_agent_save, sync_agent_save
from .services.meshnet_adapter_service import get_meshnet_packs_payload
from .services.protection_service import (
    clear_secret,
    is_secret_unlockable,
    is_unlocked,
    log_protection_access,
    mark_unlocked,
    protection_state,
    set_secret,
    verify_secret,
)

User = get_user_model()


# --------------------------------------------------
# Public Portal, Archives & Forum Reading
# --------------------------------------------------


def portal(request):
    """Public landing portal for Spacemarches."""
    recent_archives = ArchiveEntry.objects.filter(is_public=True).order_by("-created_at")[:5]
    recent_threads = ForumThread.objects.filter(is_public=True).select_related("author")[:5]
    summary = get_user_spacemarches_summary(request.user)
    ep2_summary = get_ep2_catalog_summary()
    return render(
        request,
        "spacemarches/portal.html",
        {
            "recent_archives": recent_archives,
            "recent_threads": recent_threads,
            "summary": summary,
            "ep2_summary": ep2_summary,
        },
    )


def archive_list(request):
    """Public declassified lore/containment archives strictly filtered by is_public=True."""
    entries = ArchiveEntry.objects.filter(is_public=True).order_by("-created_at")
    return render(request, "spacemarches/archive_list.html", {"entries": entries})


def archive_detail(request, slug: str):
    """Detail view for a single declassified archive entry."""
    entry = get_object_or_404(ArchiveEntry, slug=slug, is_public=True)
    related_threads = entry.forum_threads.filter(is_public=True).select_related("author")
    return render(
        request,
        "spacemarches/archive_detail.html",
        {
            "entry": entry,
            "rendered_body": render_markdown_safe(entry.body),
            "related_threads": related_threads,
        },
    )


def forum_list(request):
    """Public read-only list of forum threads (with creation form available if logged in)."""
    threads = (
        ForumThread.objects.filter(is_public=True)
        .select_related("author", "related_archive")
        .order_by("-created_at")
    )
    public_archives = ArchiveEntry.objects.filter(is_public=True).order_by("title")
    return render(
        request,
        "spacemarches/forum_list.html",
        {
            "threads": threads,
            "public_archives": public_archives,
        },
    )


def forum_detail(request, slug: str):
    """Public read access for a forum thread and its public posts."""
    thread = get_object_or_404(ForumThread, slug=slug, is_public=True)
    posts = thread.posts.filter(is_public=True).select_related("author").order_by("created_at")
    rendered_posts = [
        {"post": post, "rendered_body": render_markdown_safe(post.body)}
        for post in posts
    ]
    return render(
        request,
        "spacemarches/forum_detail.html",
        {
            "thread": thread,
            "rendered_body": render_markdown_safe(thread.body),
            "rendered_posts": rendered_posts,
        },
    )


@login_required
@require_POST
def forum_new(request):
    """Authenticated endpoint to open a new forum thread."""
    title = (request.POST.get("title") or "").strip()
    body = (request.POST.get("body") or "").strip()
    archive_slug = (request.POST.get("related_archive") or "").strip()

    if not title or not body:
        messages.error(request, "Thread title and body are required.")
        return redirect("spacemarches:forum_list")

    related_archive = None
    if archive_slug:
        related_archive = ArchiveEntry.objects.filter(slug=archive_slug, is_public=True).first()

    thread = ForumThread.objects.create(
        title=title[:255],
        author=request.user,
        related_archive=related_archive,
        is_public=True,
        body=body,
    )
    return redirect("spacemarches:forum_detail", slug=thread.slug)


@login_required
@require_POST
def forum_reply(request, slug: str):
    """Authenticated endpoint to post a reply on an existing public thread."""
    thread = get_object_or_404(ForumThread, slug=slug, is_public=True)
    body = (request.POST.get("body") or "").strip()
    if not body:
        messages.error(request, "Reply text cannot be empty.")
        return redirect("spacemarches:forum_detail", slug=thread.slug)

    ForumPost.objects.create(
        thread=thread,
        author=request.user,
        is_public=True,
        body=body,
    )
    return redirect("spacemarches:forum_detail", slug=thread.slug)


# --------------------------------------------------
# Public Point-Buy v2 Generator, Terminal & Cloud Save Sync (mesh-net)
# --------------------------------------------------


def _resolve_meshnet_bundle() -> dict[str, Any]:
    """Locate compiled MeshNet entry JS and CSS files inside static/spacemarches/assets/."""
    assets_dir = Path(settings.BASE_DIR) / "spacemarches" / "static" / "spacemarches" / "assets"
    js_entry = ""
    css_entries: list[str] = []
    if assets_dir.is_dir():
        index_js = sorted(assets_dir.glob("index-*.js"))
        if index_js:
            js_entry = f"spacemarches/assets/{index_js[0].name}"
        elif (assets_dir / "index.js").is_file():
            js_entry = "spacemarches/assets/index.js"
        for css_file in sorted(assets_dir.glob("index-*.css")):
            css_entries.append(f"spacemarches/assets/{css_file.name}")
        if not css_entries and (assets_dir / "index.css").is_file():
            css_entries.append("spacemarches/assets/index.css")
    return {
        "ready": bool(js_entry),
        "js_entry": js_entry,
        "css_entries": css_entries,
    }


def _build_generator_boot_payload(request, *, route_url: str) -> dict[str, Any]:
    """Build client bootstrap payload for the MeshNet Point-Buy v2 generator."""
    is_auth = bool(request.user and request.user.is_authenticated)
    saved_characters: list[dict[str, Any]] = []
    dossiers: list[dict[str, Any]] = []
    if is_auth:
        chars = GeneratedCharacter.objects.filter(user=request.user).select_related("dossier").order_by("-updated_at")
        saved_characters = [serialize_generated_character(c, include_raw=False) for c in chars]
        user_dossiers = CharacterDossier.objects.filter(user=request.user).order_by("-updated_at")
        dossiers = [
            {
                "id": d.pk,
                "character_name": d.character_name,
                "slug": d.slug,
                "url": reverse("spacemarches:dossier_detail", kwargs={"slug": d.slug}),
            }
            for d in user_dossiers
        ]

    return {
        "authenticated": is_auth,
        "username": request.user.username if is_auth else "",
        "login_url": f"{reverse('login')}?next={route_url}",
        "register_url": f"{reverse('register')}?next={route_url}",
        "portal_url": reverse("spacemarches:portal"),
        "roster_url": reverse("spacemarches:character_roster"),
        "dossier_list_url": reverse("spacemarches:dossier_list"),
        "characters_api_url": reverse("spacemarches:api_characters"),
        "ep2_api_url": reverse("spacemarches:api_ep2_data"),
        "ep2_meta_api_url": reverse("spacemarches:api_ep2_meta"),
        "meshnet_packs_api_url": reverse("spacemarches:api_meshnet_packs"),
        "packs_url": reverse("spacemarches:design_pack_list"),
        "compendium_url": reverse("spacemarches:compendium_list"),
        "saved_characters": saved_characters,
        "dossiers": dossiers,
        "initial_load_id": (request.GET.get("load") or "").strip(),
        "initial_external_id": (request.GET.get("external_id") or "").strip(),
    }


def generator(request):
    """Public MeshNet / Point-Buy v2 character generator: anonymous users build & export; logged-in users sync & link Dossiers."""
    route_url = request.path or reverse("spacemarches:meshnet")
    bundle = _resolve_meshnet_bundle()
    boot = _build_generator_boot_payload(request, route_url=route_url)
    initial_save = (
        load_agent_save(request.user, slot_name=(request.GET.get("slot") or "auto").strip() or "auto")
        if request.user.is_authenticated
        else {"exists": False, "slot_name": "auto", "raw_state": {}, "clearance_summary": {}, "updated_at": None}
    )
    return render(
        request,
        "spacemarches/terminal.html",
        {
            "is_public_generator": True,
            "slot_name": initial_save["slot_name"],
            "initial_save": initial_save,
            "generator_boot": boot,
            "meshnet_bundle": bundle,
        },
    )


@login_required
def terminal(request):
    """Authenticated shell hosting the mesh-net bundle, cloud save bridge, and character sync."""
    slot_name = (request.GET.get("slot") or "auto").strip() or "auto"
    saved = load_agent_save(request.user, slot_name=slot_name)
    bundle = _resolve_meshnet_bundle()
    boot = _build_generator_boot_payload(request, route_url=reverse("spacemarches:terminal"))
    return render(
        request,
        "spacemarches/terminal.html",
        {
            "is_public_generator": False,
            "slot_name": saved["slot_name"],
            "initial_save": saved,
            "generator_boot": boot,
            "meshnet_bundle": bundle,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def api_sync(request):
    """JSON endpoint hydrating or saving mesh-net localStorage state for the logged-in user."""
    if request.method == "GET":
        slot_name = request.GET.get("slot", "auto")
        data = load_agent_save(request.user, slot_name=slot_name)
        return JsonResponse(data)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "JSON payload must be an object."}, status=400)

    slot_name = payload.get("slot_name", "auto")
    raw_state = payload.get("raw_state")
    clearance_summary = payload.get("clearance_summary", {})

    if raw_state is None:
        return JsonResponse({"error": "Missing raw_state field."}, status=400)

    try:
        slot, created = sync_agent_save(
            request.user,
            slot_name=slot_name,
            raw_state=raw_state,
            clearance_summary=clearance_summary,
        )
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    return JsonResponse(
        {
            "status": "ok",
            "created": created,
            "slot_name": slot.slot_name,
            "updated_at": slot.updated_at.isoformat(),
        }
    )


@login_required
def character_roster(request):
    """Authenticated Django roster of generated EP2E characters with Dossier matching and exports."""
    if request.method == "POST":
        uploaded = request.FILES.get("character_json")
        if uploaded is None:
            messages.error(request, "Select a Point-Buy JSON export file to import.")
            return redirect("spacemarches:character_roster")
        if uploaded.size > 2_000_000:
            messages.error(request, "Uploaded JSON file exceeds 2 MB limit.")
            return redirect("spacemarches:character_roster")
        try:
            raw_data = json.loads(uploaded.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            messages.error(request, "Uploaded file is not valid JSON.")
            return redirect("spacemarches:character_roster")
        if not isinstance(raw_data, dict):
            messages.error(request, "Character JSON root must be an object.")
            return redirect("spacemarches:character_roster")
        try:
            char, _ = save_generated_character(
                request.user,
                raw_data=raw_data,
                dossier_id=request.POST.get("dossier_id") or None,
            )
            messages.success(request, f"Saved {char.character_name} to your Spacemarches account.")
        except ValueError as err:
            messages.error(request, str(err))
        return redirect("spacemarches:character_roster")

    characters = list(
        GeneratedCharacter.objects.filter(user=request.user)
        .select_related("dossier")
        .prefetch_related("censuses", "dossier__censuses")
        .order_by("-updated_at")
    )
    dossiers = list(CharacterDossier.objects.filter(user=request.user).order_by("-updated_at"))
    skill_pack_choices = get_sheet_skill_pack_choices()
    character_rows = []
    for ch in characters:
        pending = compute_pending_sheet_changes(ch)
        sheet_ctx = build_sheet_prompt_context(ch)
        character_rows.append(
            {
                "sheet": ch,
                "pending": pending,
                "sheet_context": sheet_ctx,
            }
        )
    return render(
        request,
        "spacemarches/character_roster.html",
        {
            "characters": characters,
            "character_rows": character_rows,
            "dossiers": dossiers,
            "skill_pack_choices": skill_pack_choices,
            "voice_choices": CharacterDossier.NARRATIVE_VOICE_CHOICES,
        },
    )


@login_required
def character_export(request, pk: int):
    """Download a saved GeneratedCharacter as HTML, JSON, or Markdown."""
    qs = GeneratedCharacter.objects.select_related("dossier")
    if _is_admin(request.user):
        character = get_object_or_404(qs, pk=pk)
    else:
        character = get_object_or_404(qs, pk=pk, user=request.user)

    fmt = (request.GET.get("format") or "html").strip().lower()
    base_name = slugify(character.character_name) or f"character-{character.pk}"
    if fmt == "json":
        payload = json.dumps(character.raw_data, indent=2)
        resp = HttpResponse(payload, content_type="application/json; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{base_name}-point-buy.json"'
        return resp
    if fmt in {"md", "markdown"}:
        md_text = export_generated_character_markdown(character)
        resp = HttpResponse(md_text, content_type="text/markdown; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{base_name}-sheet.md"'
        return resp
    html_text = export_generated_character_html(character)
    resp = HttpResponse(html_text, content_type="text/html; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{base_name}-sheet.html"'
    return resp


@login_required
@require_POST
def character_link_dossier(request, pk: int):
    """Link, unlink, or create-and-link a CharacterDossier for a GeneratedCharacter."""
    character = get_object_or_404(GeneratedCharacter, pk=pk, user=request.user)
    create_new = request.POST.get("create_dossier") in {"1", "true", "yes"}
    dossier_id = request.POST.get("dossier_id")
    voice = (request.POST.get("narrative_voice") or CharacterDossier.VOICE_FIRST_PERSON).strip()
    next_url = (request.POST.get("next") or "").strip()

    try:
        dossier = link_character_to_dossier(
            request.user,
            character,
            dossier_id=dossier_id,
            create_dossier=create_new,
            narrative_voice=voice,
        )
        if dossier is None:
            messages.success(request, f"Unlinked dossier from {character.character_name}.")
        else:
            messages.success(request, f"Linked {character.character_name} to dossier {dossier.character_name}.")
    except ValueError as err:
        messages.error(request, str(err))

    if next_url.startswith("/spacemarches/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect("spacemarches:character_roster")


@login_required
@require_POST
def character_sync_profile(request, pk: int):
    """Update core Point-Buy profile / skillPack options directly from Census, Dossier, or Roster."""
    qs = GeneratedCharacter.objects.select_related("dossier")
    if _is_admin(request.user):
        character = get_object_or_404(qs, pk=pk)
    else:
        character = get_object_or_404(qs, pk=pk, user=request.user)

    wants_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in (request.content_type or "")
    )
    if "application/json" in (request.content_type or ""):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    else:
        payload = request.POST

    acknowledge_only = str(payload.get("action") or "").strip() == "acknowledge"
    skill_packs: dict[str, str] = {}
    for slot in ("background", "career", "interest", "faction"):
        key = f"skill_pack_{slot}"
        if key in payload:
            skill_packs[slot] = str(payload.get(key) or "")

    kwargs: dict[str, Any] = {
        "acknowledge_only": acknowledge_only,
        "sync_linked_names": str(payload.get("sync_linked_names", "1")).strip() not in {"0", "false", "no"},
        "source": str(payload.get("source") or "web").strip()[:32],
    }
    for param, kw in (
        ("character_name", "character_name"),
        ("full_name", "full_name"),
        ("concept", "concept"),
        ("ego_type", "ego_type"),
        ("gender", "gender"),
        ("muse_name", "muse_name"),
    ):
        if param in payload:
            kwargs[kw] = str(payload.get(param) or "")
    if skill_packs:
        kwargs["skill_packs"] = skill_packs

    try:
        updated_char, changed_fields = update_sheet_profile_fields(request.user, character, **kwargs)
    except ValueError as err:
        if wants_json:
            return JsonResponse({"error": str(err)}, status=400)
        messages.error(request, str(err))
        next_url = str(payload.get("next") or "").strip()
        if next_url.startswith("/spacemarches/") and not next_url.startswith("//"):
            return redirect(next_url)
        return redirect("spacemarches:character_roster")

    if wants_json:
        return JsonResponse(
            {
                "status": "ok",
                "changed_fields": changed_fields,
                "character": serialize_generated_character(updated_char, include_raw=False),
                "sheet_context": build_sheet_prompt_context(updated_char),
                "pending_sheet_changes": compute_pending_sheet_changes(updated_char),
            }
        )

    if acknowledge_only:
        messages.info(request, f"Marked '{updated_char.character_name}' sheet as synced with current Census/Dossier.")
    elif changed_fields:
        messages.success(
            request,
            f"Updated sheet '{updated_char.character_name}' ({', '.join(changed_fields)}).",
        )
    else:
        messages.info(request, f"Sheet '{updated_char.character_name}' is already up to date.")

    next_url = str(payload.get("next") or "").strip()
    if next_url.startswith("/spacemarches/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect("spacemarches:character_roster")


@login_required
@require_POST
def character_delete(request, pk: int):
    """Delete a saved GeneratedCharacter owned by the user."""
    character = get_object_or_404(GeneratedCharacter, pk=pk, user=request.user)
    name = character.character_name
    character.delete()
    messages.success(request, f"Removed {name} from cloud saves.")
    return redirect("spacemarches:character_roster")


# --- Protection / finalize / public review ---

@login_required
@require_POST
def character_complete(request, pk: int):
    """Toggle a sheet between Draft and Completed. Completion is a soft, reviewable state."""
    character = get_object_or_404(GeneratedCharacter, pk=pk, user=request.user)
    new_status = (request.POST.get("status") or "").strip()
    if new_status not in {GeneratedCharacter.STATUS_DRAFT, GeneratedCharacter.STATUS_COMPLETED}:
        messages.error(request, "Unknown status.")
        return redirect("spacemarches:character_roster")
    if character.status != new_status:
        character.status = new_status
        character.completed_at = timezone.now() if new_status == GeneratedCharacter.STATUS_COMPLETED else None
        character.save(update_fields=["status", "completed_at", "updated_at"])
        messages.success(request, f"{character.character_name} is now {new_status}.")
    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/spacemarches/"):
        return redirect(next_url)
    return redirect("spacemarches:character_roster")


@login_required
@require_POST
def character_public_toggle(request, pk: int):
    """Toggle the public-review flag on a completed sheet."""
    character = get_object_or_404(GeneratedCharacter, pk=pk, user=request.user)
    new_value = request.POST.get("public_view") in {"1", "true", "on", "yes"}
    character.public_view = new_value
    character.save(update_fields=["public_view", "updated_at"])
    messages.success(request, f"Public review is now {'on' if new_value else 'off'}.")
    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/spacemarches/"):
        return redirect(next_url)
    return redirect("spacemarches:character_roster")


@login_required
@require_POST
def character_protection(request, pk: int):
    """Set the protection lock on a sheet, or unlock it with the cipher."""
    character = get_object_or_404(GeneratedCharacter, pk=pk, user=request.user)
    action = (request.POST.get("action") or "save").strip()

    if action == "unlock":
        answer = (request.POST.get("answer") or "").strip()
        if not verify_secret(character, answer):
            messages.error(request, "Incorrect answer — the lock held.")
            return redirect("spacemarches:character_roster")
        mark_unlocked(request, "character", character.pk)
        messages.success(request, f"Authenticated — {character.character_name} is unlocked.")
        next_url = (request.POST.get("next") or "").strip()
        if next_url.startswith("/spacemarches/"):
            return redirect(next_url)
        return redirect("spacemarches:character_roster")

    protection = (request.POST.get("protection") or "none").strip()
    if protection not in {choice[0] for choice in GeneratedCharacter.PROTECTION_CHOICES}:
        protection = GeneratedCharacter.PROTECTION_NONE

    puzzle_prompt = (request.POST.get("secret_puzzle_prompt") or "").strip()
    answer = (request.POST.get("secret_answer") or "").strip()

    character.protection = protection
    character.save(update_fields=["protection", "updated_at"])

    if protection == GeneratedCharacter.PROTECTION_SECRET:
        set_secret(character, puzzle_prompt, answer)
        messages.success(request, f"Secret lock armed for {character.character_name}.")
    else:
        clear_secret(character)
        messages.success(request, f"Protection set to {protection} for {character.character_name}.")
    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/spacemarches/"):
        return redirect(next_url)
    return redirect("spacemarches:character_roster")


@login_required
@require_POST
def dossier_protection(request, slug: str):
    """Set the protection lock on a dossier, or unlock it with the cipher."""
    dossier = get_object_or_404(CharacterDossier, slug=slug, user=request.user)
    action = (request.POST.get("action") or "save").strip()

    if action == "unlock":
        answer = (request.POST.get("answer") or "").strip()
        if not verify_secret(dossier, answer):
            messages.error(request, "Incorrect answer — the lock held.")
            return redirect("spacemarches:dossier_detail", slug=dossier.slug)
        mark_unlocked(request, "dossier", dossier.pk)
        messages.success(request, f"Authenticated — dossier unlocked.")
        return redirect("spacemarches:dossier_detail", slug=dossier.slug)

    protection = (request.POST.get("protection") or "none").strip()
    if protection not in {choice[0] for choice in GeneratedCharacter.PROTECTION_CHOICES}:
        protection = GeneratedCharacter.PROTECTION_NONE

    puzzle_prompt = (request.POST.get("secret_puzzle_prompt") or "").strip()
    answer = (request.POST.get("secret_answer") or "").strip()

    dossier.protection = protection
    dossier.save(update_fields=["protection", "updated_at"])

    if protection == GeneratedCharacter.PROTECTION_SECRET:
        set_secret(dossier, puzzle_prompt, answer)
        messages.success(request, f"Secret lock armed for {dossier.character_name}.")
    else:
        clear_secret(dossier)
        messages.success(request, f"Protection set to {protection}.")
    return redirect("spacemarches:dossier_detail", slug=dossier.slug)


@login_required
@require_http_methods(["GET", "POST"])
def api_characters(request):
    """JSON endpoint listing or saving/importing Point-Buy v2 characters for the authenticated user."""
    if request.method == "GET":
        chars = GeneratedCharacter.objects.filter(user=request.user).select_related("dossier").order_by("-updated_at")
        dossiers = CharacterDossier.objects.filter(user=request.user).order_by("-updated_at")
        return JsonResponse(
            {
                "characters": [serialize_generated_character(c, include_raw=False) for c in chars],
                "dossiers": [
                    {
                        "id": d.pk,
                        "character_name": d.character_name,
                        "slug": d.slug,
                        "url": reverse("spacemarches:dossier_detail", kwargs={"slug": d.slug}),
                    }
                    for d in dossiers
                ],
            }
        )

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "JSON payload must be an object."}, status=400)

    # Support batch import (e.g., migrating anonymous IndexedDB drafts on login)
    if isinstance(payload.get("characters"), list):
        saved_items = []
        for entry in payload["characters"][:25]:
            if not isinstance(entry, dict) or not isinstance(entry.get("raw_data"), dict):
                continue
            try:
                char, created = save_generated_character(
                    request.user,
                    external_id=str(entry.get("external_id") or ""),
                    character_name=str(entry.get("character_name") or ""),
                    source_system=str(entry.get("source_system") or GeneratedCharacter.SOURCE_POINT_BUY_V2),
                    raw_data=entry.get("raw_data"),
                    dossier_id=entry.get("dossier_id"),
                )
                saved_items.append(serialize_generated_character(char, include_raw=False))
            except ValueError as err:
                return JsonResponse({"error": str(err)}, status=400)
        return JsonResponse({"status": "ok", "characters": saved_items})

    raw_data = payload.get("raw_data")
    if raw_data is None:
        return JsonResponse({"error": "Missing raw_data field."}, status=400)

    try:
        char, created = save_generated_character(
            request.user,
            external_id=str(payload.get("external_id") or ""),
            character_name=str(payload.get("character_name") or ""),
            source_system=str(payload.get("source_system") or GeneratedCharacter.SOURCE_POINT_BUY_V2),
            raw_data=raw_data,
            dossier_id=payload.get("dossier_id"),
            character_pk=payload.get("id"),
        )
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    return JsonResponse(
        {
            "status": "ok",
            "created": created,
            "character": serialize_generated_character(char, include_raw=False),
        }
    )


@login_required
@require_http_methods(["GET", "DELETE"])
def api_character_detail(request, pk: int):
    """Fetch full raw_data (for hydrating MeshNet IndexedDB) or delete a saved character."""
    character = get_object_or_404(GeneratedCharacter.objects.select_related("dossier"), pk=pk, user=request.user)
    if request.method == "DELETE":
        character.delete()
        return JsonResponse({"status": "deleted"})
    return JsonResponse({"character": serialize_generated_character(character, include_raw=True)})


@login_required
@require_POST
def api_character_link_dossier(request, pk: int):
    """JSON endpoint matching or creating a CharacterDossier for a GeneratedCharacter."""
    character = get_object_or_404(GeneratedCharacter.objects.select_related("dossier"), pk=pk, user=request.user)
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Invalid JSON payload."}, status=400)

    if not isinstance(payload, dict):
        return JsonResponse({"error": "JSON payload must be an object."}, status=400)

    try:
        link_character_to_dossier(
            request.user,
            character,
            dossier_id=payload.get("dossier_id"),
            create_dossier=bool(payload.get("create_dossier")),
            narrative_voice=str(payload.get("narrative_voice") or CharacterDossier.VOICE_FIRST_PERSON),
        )
    except ValueError as err:
        return JsonResponse({"error": str(err)}, status=400)

    character.refresh_from_db()
    return JsonResponse(
        {
            "status": "ok",
            "character": serialize_generated_character(character, include_raw=False),
        }
    )


# --------------------------------------------------
# Authenticated Interactive Character Dossiers & Discord Link
# --------------------------------------------------


def _is_admin(user) -> bool:
    """Site-wide admin privilege (staff or superuser). Distinct from is_st (Storyteller)."""
    return bool(user and getattr(user, "is_authenticated", False) and (user.is_staff or user.is_superuser))


def _is_st(user) -> bool:
    """Storyteller privilege - required to view ST-only sections."""
    return bool(user and getattr(user, "is_authenticated", False) and getattr(user, "is_st", False))


def _get_accessible_dossier(user, *, slug: str = "", pk: int | None = None) -> CharacterDossier:
    is_admin = _is_admin(user)
    if pk is not None:
        if is_admin:
            return get_object_or_404(CharacterDossier.objects.select_related("user", "invited_by"), pk=pk)
        return get_object_or_404(CharacterDossier.objects.select_related("user", "invited_by"), pk=pk, user=user)

    owned = CharacterDossier.objects.select_related("user", "invited_by").filter(user=user, slug=slug).first()
    if owned is not None:
        return owned
    if is_admin:
        any_match = (
            CharacterDossier.objects.select_related("user", "invited_by")
            .filter(slug=slug)
            .order_by("-updated_at")
            .first()
        )
        if any_match is not None:
            return any_match
    raise Http404("Character dossier not found.")


@login_required
@require_http_methods(["GET", "POST"])
def dossier_list(request):
    """List the user's character dossiers, create a new dossier, and manage Discord link code."""
    if request.method == "POST":
        character_name = (request.POST.get("character_name") or "").strip()
        narrative_voice = (request.POST.get("narrative_voice") or CharacterDossier.VOICE_FIRST_PERSON).strip()
        if narrative_voice not in {CharacterDossier.VOICE_FIRST_PERSON, CharacterDossier.VOICE_OMNISCIENT}:
            narrative_voice = CharacterDossier.VOICE_FIRST_PERSON

        if not character_name:
            messages.error(request, "Character name is required.")
            return redirect("spacemarches:dossier_list")

        base_slug = slugify(character_name)[:140] or "character"
        slug = base_slug
        counter = 1
        while CharacterDossier.objects.filter(user=request.user, slug=slug).exists():
            counter += 1
            slug = f"{base_slug[:140]}-{counter}"

        dossier = CharacterDossier.objects.create(
            user=request.user,
            character_name=character_name[:160],
            slug=slug,
            narrative_voice=narrative_voice,
        )
        return redirect("spacemarches:dossier_detail", slug=dossier.slug)

    dossiers = list(CharacterDossier.objects.filter(user=request.user).order_by("-updated_at"))
    dossier_cards = [
        {"dossier": d, "stats": compute_dossier_stats(d)}
        for d in dossiers
    ]
    gm_dossier_cards = []
    if _is_admin(request.user):
        other_dossiers = list(
            CharacterDossier.objects.filter(Q(user__isnull=True) | ~Q(user=request.user))
            .select_related("user", "invited_by")
            .order_by("-updated_at")
        )
        gm_dossier_cards = [
            {"dossier": d, "stats": compute_dossier_stats(d)}
            for d in other_dossiers
        ]
    discord_link = DiscordLink.objects.filter(user=request.user).first()
    return render(
        request,
        "spacemarches/dossier_list.html",
        {
            "dossier_cards": dossier_cards,
            "gm_dossier_cards": gm_dossier_cards,
            "is_admin": _is_admin(request.user),
            "discord_link": discord_link,
            "voice_choices": CharacterDossier.NARRATIVE_VOICE_CHOICES,
        },
    )


@login_required
@require_POST
def generate_discord_code(request):
    """Generate or refresh a one-time Discord link code for the logged-in user."""
    code = generate_discord_link_code(request.user)
    messages.success(request, f"Generated Discord link code: {code}. Run /link {code} in Discord.")
    return redirect("spacemarches:dossier_list")


def _build_question_node(
    question: dict,
    responses: dict,
    private_keys: set[str],
    include_sensitive: bool,
    *,
    sheet_ctx: dict[str, Any] | None = None,
    has_linked_census: bool = False,
) -> dict:
    qid = question["id"]
    raw_entry = responses.get(qid)
    has_entry = isinstance(raw_entry, dict) and bool(str(raw_entry.get("answer", "")).strip())
    norm = _normalize_existing_record(raw_entry) if has_entry else {}
    temporal_defaults = get_question_temporal_defaults(qid)

    raw_revs = raw_entry.get("revisions", []) if isinstance(raw_entry, dict) else []
    revisions = [
        _normalize_existing_record(rev)
        for rev in reversed(raw_revs)
        if isinstance(rev, dict) and str(rev.get("answer", "")).strip()
    ]

    direct_children = get_children(qid, include_sensitive=include_sensitive)
    child_nodes = []
    for child in direct_children:
        child_node = _build_question_node(
            child,
            responses,
            private_keys,
            include_sensitive,
            sheet_ctx=sheet_ctx,
            has_linked_census=has_linked_census,
        )
        child_nodes.append(child_node)

    return {
        "id": qid,
        "parent_id": question.get("parent_id"),
        "tier": question.get("tier"),
        "category": question.get("category"),
        "prompt": question.get("prompt"),
        "lore_text": question.get("lore_text"),
        "temporal_scope": temporal_defaults["temporal_scope"],
        "temporal_scope_label": temporal_defaults["temporal_scope_label"],
        "default_stardate_era": temporal_defaults["default_stardate_era"],
        "default_sol_number": temporal_defaults["default_sol_number"],
        "answer": norm.get("answer", ""),
        "is_answered": has_entry,
        "updated_at": norm.get("updated_at", ""),
        "entry_kind": norm.get("entry_kind", ""),
        "entry_kind_label": norm.get("entry_kind_label", ""),
        "stardate_era": norm.get("stardate_era", ""),
        "stardate_era_label": norm.get("stardate_era_label", ""),
        "sol_number": norm.get("sol_number", ""),
        "sol_date": norm.get("sol_date", ""),
        "version": norm.get("version", 0),
        "version_label": norm.get("version_label", ""),
        "session_tag": norm.get("version_label", ""),
        "source": norm.get("source", ""),
        "revisions": revisions,
        "revision_count": len(revisions),
        "is_gm_only": qid in private_keys,
        "synced_census_qid": DOSSIER_TO_CENSUS_MAP.get(qid) if has_linked_census else None,
        "sheet_hint": get_dossier_question_sheet_hint(qid, sheet_ctx),
        "children": child_nodes,
    }


def _log_st_only_access(request, dossier: CharacterDossier) -> None:
    """Log ST-only access when the viewer is a Storyteller."""
    if (dossier.protection or "none") != GeneratedCharacter.PROTECTION_ST_ONLY:
        return
    if not _is_st(request.user):
        return
    log_protection_access(
        target_kind="dossier",
        target_pk=dossier.pk,
        owner=dossier.user,
        viewer=request.user,
        protection_type=GeneratedCharacter.PROTECTION_ST_ONLY,
        note="Section view",
    )


def _render_dossier_detail(request, dossier: CharacterDossier, *, by_id: bool = False):
    _log_st_only_access(request, dossier)
    responses = dossier.responses if isinstance(dossier.responses, dict) else {}
    private_keys = set(dossier.private_keys or [])
    include_sensitive = bool(dossier.show_sensitive_appendix)

    is_owner_view = dossier.user_id == request.user.pk
    primary_sheet = get_primary_linked_character_for_dossier(dossier)
    if primary_sheet is not None and not is_owner_view:
        primary_prot = protection_state(primary_sheet, request, viewer=request.user)
        if not (
            primary_prot["protection"] == GeneratedCharacter.PROTECTION_NONE
            or (primary_prot["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY and _is_st(request.user))
        ):
            primary_sheet = None
    sheet_ctx = build_sheet_prompt_context(primary_sheet)
    linked_censuses = list(dossier.censuses.order_by("-updated_at"))
    core_nodes = [
        _build_question_node(
            q,
            responses,
            private_keys,
            include_sensitive,
            sheet_ctx=sheet_ctx,
            has_linked_census=bool(linked_censuses),
        )
        for q in get_core_questions()
    ]
    all_questions = get_all_questions(include_sensitive=include_sensitive)
    categories = get_categories(include_sensitive=include_sensitive)
    stats = compute_dossier_stats(dossier)
    progression = get_dossier_progression_summary(dossier)

    default_entry_kind = (
        ENTRY_KIND_POST_ACTION_REPORT
        if stats["answered_count"] > 0
        else ENTRY_KIND_CHARACTER_CREATION
    )
    default_stardate_era = (
        STARDATE_ERA_POST_FALL
        if stats["answered_count"] > 0
        else STARDATE_ERA_AUTO
    )

    use_id_routes = by_id or dossier.user_id != request.user.pk
    if use_id_routes:
        dossier_answer_url = reverse("spacemarches:dossier_answer_by_id", kwargs={"pk": dossier.pk})
        dossier_export_url = reverse("spacemarches:dossier_export_by_id", kwargs={"pk": dossier.pk})
        dossier_toggle_url = reverse("spacemarches:dossier_toggle_sensitive_by_id", kwargs={"pk": dossier.pk})
    else:
        dossier_answer_url = reverse("spacemarches:dossier_answer", kwargs={"slug": dossier.slug})
        dossier_export_url = reverse("spacemarches:dossier_export", kwargs={"slug": dossier.slug})
        dossier_toggle_url = reverse("spacemarches:dossier_toggle_sensitive", kwargs={"slug": dossier.slug})

    can_admin_reassign = _is_admin(request.user)
    reassign_users = list(User.objects.order_by("username")) if can_admin_reassign else []
    dossier_reassign_url = (
        reverse("spacemarches:dossier_reassign_by_id", kwargs={"pk": dossier.pk})
        if can_admin_reassign
        else ""
    )

    protection = protection_state(dossier, request, viewer=request.user)
    protected_sheets = [
        ch for ch in dossier.generated_characters.order_by("-updated_at")
        if ch.protection != GeneratedCharacter.PROTECTION_NONE
    ]

    linked_characters = list(
        dossier.generated_characters.order_by("-updated_at")
    )

    # Per-sheet protection states: owner always sees their own sheets; non-owners
    # (admin override) see protected sheets as locked cards. ST-only access is
    # logged when a Storyteller views a non-owner's sheet.
    sheet_states = []
    for ch in linked_characters:
        state = protection_state(ch, request, viewer=request.user)
        visible = True
        if not is_owner_view:
            visible = (
                state["protection"] == GeneratedCharacter.PROTECTION_NONE
                or (state["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY and _is_st(request.user))
            )
            if state["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY and _is_st(request.user):
                log_protection_access(
                    target_kind="character", target_pk=ch.pk, owner=ch.user,
                    viewer=request.user,
                    protection_type=GeneratedCharacter.PROTECTION_ST_ONLY, note="Section view",
                )
        sheet_states.append({"sheet": ch, "visible": visible, "protection": state})

    linked_sheet_pks = [ch.pk for ch in linked_characters]
    log_q = Q(target_kind=ProtectionAccessLog.TARGET_DOSSIER, target_pk=dossier.pk)
    if linked_sheet_pks:
        log_q |= Q(target_kind=ProtectionAccessLog.TARGET_CHARACTER, target_pk__in=linked_sheet_pks)
    access_log = (
        list(
            ProtectionAccessLog.objects.filter(log_q)
            .select_related("viewer")
            .order_by("-created_at")[:20]
        )
        if is_owner_view
        else []
    )

    available_characters = (
        list(
            GeneratedCharacter.objects.filter(user=request.user)
            .exclude(dossier=dossier)
            .order_by("-updated_at")
        )
        if dossier.user_id == request.user.pk
        else []
    )

    pending_sheet_changes = (
        compute_pending_sheet_changes(primary_sheet, dossier=dossier)
        if primary_sheet is not None
        else {"has_pending": False, "count": 0, "items": [], "suggested_name": ""}
    )
    return render(
        request,
        "spacemarches/dossier_detail.html",
        {
            "dossier": dossier,
            "linked_censuses": linked_censuses,
            "primary_sheet": primary_sheet,
            "sheet_context": sheet_ctx,
            "skill_pack_choices": get_sheet_skill_pack_choices(),
            "pending_sheet_changes": pending_sheet_changes,
            "linked_characters": linked_characters,
            "available_characters": available_characters,
            "core_nodes": core_nodes,
            "core_question_count": len(core_nodes),
            "all_question_count": len(all_questions),
            "categories": categories,
            "stats": stats,
            "progression": progression,
            "entry_kind_choices": ENTRY_KIND_CHOICES,
            "stardate_era_choices": STARDATE_ERA_CHOICES,
            "default_entry_kind": default_entry_kind,
            "default_stardate_era": default_stardate_era,
            "default_sol_number": progression["latest_sol_number"],
            "attribution_notice": get_attribution_notice(),
            "rendered_attribution": mark_safe(render_markdown_inline_safe(get_attribution_notice())),
            "dossier_answer_url": dossier_answer_url,
            "dossier_export_url": dossier_export_url,
            "dossier_toggle_url": dossier_toggle_url,
            "is_admin_override": dossier.user_id != request.user.pk,
            "can_admin_reassign": can_admin_reassign,
            "reassign_users": reassign_users,
            "dossier_reassign_url": dossier_reassign_url,
            "protection": protection,
            "protected_sheets": protected_sheets,
            "linked_completed_sheets": [ch for ch in linked_characters if ch.status == GeneratedCharacter.STATUS_COMPLETED and ch.public_view],
            "sheet_states": sheet_states,
            "is_owner_view": is_owner_view,
            "access_log": access_log,
        },
    )


@login_required
def dossier_detail(request, slug: str):
    """Interactive progressive-disclosure questionnaire view for an accessible CharacterDossier."""
    dossier = _get_accessible_dossier(request.user, slug=slug)
    return _render_dossier_detail(request, dossier, by_id=False)


@login_required
def dossier_detail_by_id(request, pk: int):
    """Primary-key dossier view supporting admin access to unclaimed or player-owned dossiers."""
    dossier = _get_accessible_dossier(request.user, pk=pk)
    return _render_dossier_detail(request, dossier, by_id=True)


def _handle_dossier_review(request, dossier: CharacterDossier, *, review_url: str):
    """Shared public read-only review handler for slug and PK dossier review routes."""
    review_sheets = [
        ch for ch in dossier.generated_characters.order_by("-updated_at")
        if ch.status == GeneratedCharacter.STATUS_COMPLETED and ch.public_view
    ]

    # POST: secret unlock attempt
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "unlock_dossier":
            answer = (request.POST.get("answer") or "").strip()
            if verify_secret(dossier, answer):
                mark_unlocked(request, "dossier", dossier.pk)
                log_protection_access(target_kind="dossier", target_pk=dossier.pk, owner=dossier.user,
                                      viewer=request.user if request.user.is_authenticated else None,
                                      protection_type=GeneratedCharacter.PROTECTION_SECRET, note="Secret unlocked")
                return redirect(review_url)
            messages.error(request, "Incorrect answer — the lock held.")
            return redirect(review_url)
        if action == "unlock_sheet":
            sheet_pk = request.POST.get("sheet_pk")
            try:
                sheet = get_object_or_404(GeneratedCharacter, pk=sheet_pk, dossier=dossier)
            except Http404:
                return redirect(review_url)
            answer = (request.POST.get("answer") or "").strip()
            if verify_secret(sheet, answer):
                mark_unlocked(request, "character", sheet.pk)
                log_protection_access(target_kind="character", target_pk=sheet.pk, owner=sheet.user,
                                      viewer=request.user if request.user.is_authenticated else None,
                                      protection_type=GeneratedCharacter.PROTECTION_SECRET, note="Secret unlocked")
                return redirect(review_url)
            messages.error(request, "Incorrect answer — the lock held.")
            return redirect(review_url)
        return redirect(review_url)

    # Resolve per-object protection state
    dossier_protection = protection_state(dossier, request, viewer=request.user if request.user.is_authenticated else None)

    viewer = request.user if request.user.is_authenticated else None
    dossier_viewer_is_owner = viewer == dossier.user

    if (
        dossier_protection["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY
        and dossier_protection["unlocked"]
        and not dossier_viewer_is_owner
    ):
        log_protection_access(
            target_kind="dossier", target_pk=dossier.pk, owner=dossier.user,
            viewer=viewer,
            protection_type=GeneratedCharacter.PROTECTION_ST_ONLY, note="Section view",
        )

    sheet_states = []
    for ch in review_sheets:
        ch_protection = protection_state(ch, request, viewer=viewer)
        if (
            ch_protection["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY
            and ch_protection["unlocked"]
            and viewer != ch.user
        ):
            log_protection_access(
                target_kind="character", target_pk=ch.pk, owner=ch.user,
                viewer=viewer,
                protection_type=GeneratedCharacter.PROTECTION_ST_ONLY, note="Section view",
            )
        sheet_states.append({"sheet": ch, "protection": ch_protection})

    return render(
        request,
        "spacemarches/dossier_review.html",
        {
            "dossier": dossier,
            "dossier_protection": dossier_protection,
            "sheets": sheet_states,
            "review_url": review_url,
            "is_anonymous": not request.user.is_authenticated,
            "attribution_notice": get_attribution_notice(),
            "rendered_attribution": mark_safe(render_markdown_inline_safe(get_attribution_notice())),
        },
    )


@require_http_methods(["GET", "POST"])
def dossier_review(request, slug: str):
    """Public read-only review surface for a dossier + its completed public sheets (slug route)."""
    matches = CharacterDossier.objects.select_related("user").filter(slug=slug)
    dossier = None
    if request.user.is_authenticated:
        dossier = matches.filter(user=request.user).first()
    if dossier is None:
        dossier = matches.order_by("-updated_at").first()
    if dossier is None:
        raise Http404("Character dossier not found.")
    review_url = reverse("spacemarches:dossier_review", kwargs={"slug": dossier.slug})
    return _handle_dossier_review(request, dossier, review_url=review_url)


@require_http_methods(["GET", "POST"])
def dossier_review_by_id(request, pk: int):
    """Unambiguous PK-based public read-only review surface for a dossier + its completed public sheets."""
    dossier = get_object_or_404(
        CharacterDossier.objects.select_related("user"),
        pk=pk,
    )
    review_url = reverse("spacemarches:dossier_review_by_id", kwargs={"pk": dossier.pk})
    return _handle_dossier_review(request, dossier, review_url=review_url)


def _handle_toggle_sensitive(request, dossier: CharacterDossier, *, by_id: bool = False):
    dossier.show_sensitive_appendix = not dossier.show_sensitive_appendix
    dossier.save(update_fields=["show_sensitive_appendix", "updated_at"])
    if by_id or dossier.user_id != request.user.pk:
        return redirect("spacemarches:dossier_detail_by_id", pk=dossier.pk)
    return redirect("spacemarches:dossier_detail", slug=dossier.slug)


@login_required
@require_POST
def dossier_toggle_sensitive(request, slug: str):
    """Explicit opt-in toggle for sensitive appendix (13d1-13d6)."""
    dossier = _get_accessible_dossier(request.user, slug=slug)
    return _handle_toggle_sensitive(request, dossier, by_id=False)


@login_required
@require_POST
def dossier_toggle_sensitive_by_id(request, pk: int):
    """Primary-key opt-in toggle for sensitive appendix (13d1-13d6)."""
    dossier = _get_accessible_dossier(request.user, pk=pk)
    return _handle_toggle_sensitive(request, dossier, by_id=True)


def _handle_dossier_answer(request, dossier: CharacterDossier, *, by_id: bool = False):
    redirect_response = (
        redirect("spacemarches:dossier_detail_by_id", pk=dossier.pk)
        if (by_id or dossier.user_id != request.user.pk)
        else redirect("spacemarches:dossier_detail", slug=dossier.slug)
    )

    content_type = (request.content_type or "").lower()
    if "application/json" in content_type:
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid JSON."}, status=400)
        question_id = payload.get("question_id", "")
        answer_text = payload.get("answer_text", "")
        session_tag = payload.get("session_tag", "")
        entry_kind = payload.get("entry_kind", "")
        stardate_era = payload.get("stardate_era", "")
        sol_date = payload.get("sol_date", "")
        privacy_only = bool(payload.get("privacy_only", False))
        raw_gm = payload.get("is_gm_only")
        is_gm_only = bool(raw_gm) if raw_gm is not None else None
        wants_json = True
    else:
        question_id = request.POST.get("question_id", "")
        answer_text = request.POST.get("answer_text", "")
        session_tag = request.POST.get("session_tag", "")
        entry_kind = request.POST.get("entry_kind", "")
        stardate_era = request.POST.get("stardate_era", "")
        sol_date = request.POST.get("sol_date", "")
        privacy_only = request.POST.get("privacy_only") in {"1", "true", "on", "yes"}
        if "is_gm_only_present" in request.POST:
            is_gm_only = request.POST.get("is_gm_only") in {"1", "true", "on", "yes"}
        elif "is_gm_only" in request.POST:
            is_gm_only = request.POST.get("is_gm_only") in {"1", "true", "on", "yes"}
        else:
            is_gm_only = None
        wants_json = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    q = get_question(str(question_id).strip())
    if q is None:
        if wants_json:
            return JsonResponse({"error": f"Unknown question ID: {question_id}"}, status=400)
        messages.error(request, f"Unknown question ID: {question_id}")
        return redirect_response

    if q.get("tier") == "sensitive_appendix" and not dossier.show_sensitive_appendix:
        if wants_json:
            return JsonResponse(
                {"error": "Enable the Sensitive Appendix opt-in toggle before editing 13d questions."},
                status=400,
            )
        messages.error(request, "Enable the Sensitive Appendix opt-in toggle before editing 13d questions.")
        return redirect_response

    try:
        stats = save_dossier_answer(
            dossier,
            question_id=question_id,
            answer_text=answer_text,
            session_tag=session_tag,
            source="web",
            is_gm_only=is_gm_only,
            entry_kind=entry_kind,
            stardate_era=stardate_era,
            sol_date=sol_date,
            privacy_only=privacy_only,
        )
    except ValueError as err:
        if wants_json:
            return JsonResponse({"error": str(err)}, status=400)
        messages.error(request, str(err))
        return redirect_response

    if wants_json:
        return JsonResponse({"status": "saved", **stats})

    if privacy_only:
        messages.success(request, f"Updated GM Eyes Only privacy for [{question_id}].")
    else:
        messages.success(
            request,
            f"Saved [{question_id}] as {stats.get('version_label') or 'updated'}.",
        )
    return redirect_response


@login_required
@require_POST
def dossier_answer(request, slug: str):
    """Save an individual dossier progression update (supports JSON/fetch or standard form POST)."""
    dossier = _get_accessible_dossier(request.user, slug=slug)
    return _handle_dossier_answer(request, dossier, by_id=False)


@login_required
@require_POST
def dossier_answer_by_id(request, pk: int):
    """Primary-key dossier answer endpoint supporting admin edits to unclaimed or player dossiers."""
    dossier = _get_accessible_dossier(request.user, pk=pk)
    return _handle_dossier_answer(request, dossier, by_id=True)


def _handle_dossier_export(request, dossier: CharacterDossier):
    include_private = request.GET.get("include_private") in {"1", "true", "yes"}
    md_text = export_dossier_markdown(dossier, include_private=include_private)
    response = HttpResponse(md_text, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{dossier.slug}-dossier.md"'
    return response


@login_required
def dossier_export(request, slug: str):
    """Export an accessible CharacterDossier as a downloadable Markdown file."""
    dossier = _get_accessible_dossier(request.user, slug=slug)
    return _handle_dossier_export(request, dossier)


@login_required
def dossier_export_by_id(request, pk: int):
    """Primary-key Markdown export supporting admin access to unclaimed or player dossiers."""
    dossier = _get_accessible_dossier(request.user, pk=pk)
    return _handle_dossier_export(request, dossier)


@login_required
@require_POST
def dossier_reassign_by_id(request, pk: int):
    """Staff/Admin endpoint to reassign control of a dossier to a website user or unclaimed Discord ID."""
    if not _is_admin(request.user):
        raise Http404("Character dossier not found.")

    dossier = get_object_or_404(CharacterDossier.objects.select_related("user"), pk=pk)
    raw_target_user_id = (request.POST.get("target_user_id") or "").strip()
    raw_discord_id = (request.POST.get("discord_owner_id") or "").strip()

    target_user = None
    if raw_target_user_id:
        try:
            target_user = User.objects.filter(pk=int(raw_target_user_id)).first()
        except ValueError:
            target_user = None
        if target_user is None:
            messages.error(request, "Selected website user account was not found.")
            return redirect("spacemarches:dossier_detail_by_id", pk=dossier.pk)

    reassign_dossier_control(
        dossier,
        target_user=target_user,
        discord_owner_id=raw_discord_id,
    )
    messages.success(
        request,
        f"Updated control for {dossier.character_name}: {dossier.owner_display}.",
    )
    return redirect("spacemarches:dossier_detail_by_id", pk=dossier.pk)


# --------------------------------------------------
# EP2E Reference Compendium & Design Packs (Ep2Entry / DesignPack)
# --------------------------------------------------


def _truthy_param(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _filter_ep2_queryset(request):
    """Filter visible Ep2Entry queryset using shared query params."""
    include_storyteller = _truthy_param(request.GET.get("storyteller"))
    qs = visible_ep2_entries_qs(request.user, include_storyteller=include_storyteller)
    pack = (request.GET.get("pack") or "").strip()
    design_pack = (request.GET.get("design_pack") or "").strip()
    category = (request.GET.get("category") or "").strip()
    q = (request.GET.get("q") or "").strip()
    if design_pack:
        qs = qs.filter(design_pack__slug=design_pack)
    if category:
        qs = qs.filter(category=category)
    if pack:
        qs = qs.filter(pack=pack)
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(description__icontains=q)
            | Q(reference__icontains=q)
            | Q(pack__icontains=q)
            | Q(entry_type__icontains=q)
            | Q(design_pack__name__icontains=q)
        )
    return qs, category, pack, design_pack, q, include_storyteller


def compendium_list(request):
    """Public searchable browser for seeded & custom Eclipse Phase 2e reference entries."""
    qs, selected_category, selected_pack, selected_design_pack, query, include_storyteller = _filter_ep2_queryset(request)
    browse_all = (request.GET.get("browse") or "").strip().lower() in {"1", "true", "all"} or bool(
        (request.GET.get("page") or "").strip()
    )
    has_active_filter = bool(selected_category or selected_pack or selected_design_pack or query or browse_all)
    catalog = get_ep2_catalog_summary(
        selected_category=selected_category,
        selected_design_pack=selected_design_pack,
        include_storyteller=include_storyteller,
        user=request.user,
    )

    cards = []
    page_obj = None
    total_matching = 0
    if has_active_filter:
        qs = order_ep2_queryset(qs)
        paginator = Paginator(qs, 48)
        page_obj = paginator.get_page(request.GET.get("page"))
        total_matching = paginator.count
        cards = [
            {
                "entry": entry,
                "pack_label": format_pack_label(entry.pack),
                "highlights": extract_ep2_highlights(entry)[:4],
                "excerpt": strip_ep2_text(entry.description, max_length=180),
            }
            for entry in page_obj.object_list
        ]

    return render(
        request,
        "spacemarches/compendium_list.html",
        {
            "cards": cards,
            "page_obj": page_obj,
            "total_matching": total_matching,
            "has_active_filter": has_active_filter,
            "browse_all": browse_all and not (selected_category or selected_pack or selected_design_pack or query),
            "catalog": catalog,
            "selected_category": selected_category,
            "selected_pack": selected_pack,
            "selected_design_pack": selected_design_pack,
            "include_storyteller": include_storyteller,
            "query": query,
        },
    )


def compendium_detail(request, entry_id: str):
    """Detailed view for a single Ep2Entry with sanitized description, stats, and raw system JSON."""
    entry = get_object_or_404(
        visible_ep2_entries_qs(request.user, include_storyteller=True),
        entry_id=entry_id,
    )
    related_entries = list(
        visible_ep2_entries_qs(request.user, include_storyteller=entry.is_storyteller_only)
        .filter(pack=entry.pack)
        .exclude(pk=entry.pk)
        .order_by("name")[:8]
    )
    return render(
        request,
        "spacemarches/compendium_detail.html",
        {
            "entry": entry,
            "pack_label": format_pack_label(entry.pack),
            "source_url": get_ep2_source_url(entry.source),
            "highlights": extract_ep2_highlights(entry),
            "rendered_description": mark_safe(sanitize_ep2_html(entry.description)),
            "system_json": format_ep2_system_json(entry),
            "related_entries": related_entries,
        },
    )


@require_http_methods(["GET"])
def api_ep2_meta(request):
    """Return category, sub-pack, and DesignPack inventory counts for visible Ep2Entry records."""
    category = (request.GET.get("category") or "").strip()
    design_pack = (request.GET.get("design_pack") or "").strip()
    include_storyteller = _truthy_param(request.GET.get("storyteller"))
    return JsonResponse(
        get_ep2_catalog_summary(
            selected_category=category,
            selected_design_pack=design_pack,
            include_storyteller=include_storyteller,
            user=request.user,
        )
    )


@require_http_methods(["GET"])
def api_ep2_entries(request, entry_id: str | None = None):
    """Read-only access to Eclipse Phase 2e reference & custom pack data.

    GET /spacemarches/api/ep2/ — list/search entries.
    GET /spacemarches/api/ep2/<entry_id>/ — single entry (404 if missing).
    """
    if entry_id is not None:
        entry = get_object_or_404(
            visible_ep2_entries_qs(request.user, include_storyteller=True),
            entry_id=entry_id,
        )
        return JsonResponse(_serialize_ep2_entry(entry))

    qs, _, _, _, _, _ = _filter_ep2_queryset(request)
    total = qs.count()
    try:
        limit = min(max(int(request.GET.get("limit") or 100), 1), 500)
    except (TypeError, ValueError):
        limit = 100
    try:
        offset = max(int(request.GET.get("offset") or 0), 0)
    except (TypeError, ValueError):
        offset = 0
    entries = order_ep2_queryset(qs)[offset:offset + limit]
    return JsonResponse(
        {
            "count": total,
            "limit": limit,
            "offset": offset,
            "results": [_serialize_ep2_entry(e) for e in entries],
        }
    )


def _serialize_ep2_entry(entry) -> dict:
    """JSON-safe view of an Ep2Entry — the shape consumed by the MeshNet creator/export path."""
    return {
        "entry_id": entry.entry_id,
        "design_pack": entry.design_pack.slug if entry.design_pack_id else "",
        "design_pack_name": entry.design_pack.name if entry.design_pack_id else "",
        "pack": entry.pack,
        "pack_label": format_pack_label(entry.pack),
        "category": entry.category,
        "category_label": entry.get_category_display(),
        "entry_type": entry.entry_type,
        "name": entry.name,
        "description": entry.description,
        "excerpt": strip_ep2_text(entry.description, max_length=200),
        "reference": entry.reference,
        "is_storyteller_only": entry.is_storyteller_only,
        "is_custom": entry.is_custom,
        "highlights": extract_ep2_highlights(entry),
        "system": entry.system,
        "source": entry.source,
        "source_url": get_ep2_source_url(entry.source),
        "compendium_url": reverse("spacemarches:compendium_detail", kwargs={"entry_id": entry.entry_id}),
    }


def design_pack_list(request):
    """Browse official & custom DesignPacks, create custom packs, or import pack JSON."""
    ensure_canonical_design_packs()

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        action = (request.POST.get("action") or "").strip()
        if action == "create_pack":
            try:
                pack_obj = create_custom_design_pack(
                    request.user,
                    name=request.POST.get("name") or "",
                    slug=request.POST.get("slug") or "",
                    description=request.POST.get("description") or "",
                    is_storyteller_only=_truthy_param(request.POST.get("is_storyteller_only")),
                    is_public=_truthy_param(request.POST.get("is_public") or "on"),
                )
                messages.success(request, f"Created custom pack '{pack_obj.name}'.")
                return redirect("spacemarches:design_pack_detail", slug=pack_obj.slug)
            except ValueError as exc:
                messages.error(request, str(exc))
        elif action == "import_pack":
            raw_json = ""
            upload = request.FILES.get("pack_file")
            if upload is not None:
                if upload.size > 2 * 1024 * 1024:
                    messages.error(request, "Pack JSON file exceeds 2 MB limit.")
                    return redirect("spacemarches:design_pack_list")
                raw_json = upload.read().decode("utf-8", errors="replace")
            else:
                raw_json = request.POST.get("pack_json") or ""
            try:
                pack_obj, created_n, updated_n = import_design_pack_payload(request.user, raw_json)
                messages.success(
                    request,
                    f"Imported '{pack_obj.name}' ({created_n} created, {updated_n} updated).",
                )
                return redirect("spacemarches:design_pack_detail", slug=pack_obj.slug)
            except (ValueError, PermissionError) as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Unknown pack action.")

    packs = get_design_packs_with_counts(request.user, include_storyteller=True)
    official_packs = [p for p in packs if p["is_official"]]
    custom_packs = [p for p in packs if not p["is_official"]]
    return render(
        request,
        "spacemarches/design_pack_list.html",
        {
            "official_packs": official_packs,
            "custom_packs": custom_packs,
        },
    )


def design_pack_detail(request, slug: str):
    """Inspect a DesignPack and manage custom entries when permitted."""
    pack = get_object_or_404(
        visible_design_packs_qs(request.user, include_storyteller=True),
        slug=slug,
    )
    can_edit = can_edit_design_pack(request.user, pack)

    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.get_full_path()}")
        if not can_edit:
            messages.error(request, "This design pack is read-only.")
            return redirect("spacemarches:design_pack_detail", slug=pack.slug)

        action = (request.POST.get("action") or "").strip()
        if action == "add_entry":
            try:
                entry, created_flag = create_or_update_custom_entry(
                    request.user,
                    pack,
                    {
                        "name": request.POST.get("name") or "",
                        "category": request.POST.get("category") or Ep2Entry.CATEGORY_GEAR,
                        "pack": request.POST.get("pack") or pack.slug,
                        "entry_type": request.POST.get("entry_type") or "",
                        "reference": request.POST.get("reference") or "",
                        "description": request.POST.get("description") or "",
                        "is_storyteller_only": _truthy_param(request.POST.get("is_storyteller_only")),
                        "system": request.POST.get("system_json") or "{}",
                    },
                )
                verb = "Added" if created_flag else "Updated"
                messages.success(request, f"{verb} entry '{entry.name}'.")
                return redirect("spacemarches:design_pack_detail", slug=pack.slug)
            except (ValueError, PermissionError) as exc:
                messages.error(request, str(exc))
        elif action == "import_into_pack":
            raw_json = request.POST.get("pack_json") or ""
            upload = request.FILES.get("pack_file")
            if upload is not None:
                if upload.size > 2 * 1024 * 1024:
                    messages.error(request, "Pack JSON file exceeds 2 MB limit.")
                    return redirect("spacemarches:design_pack_detail", slug=pack.slug)
                raw_json = upload.read().decode("utf-8", errors="replace")
            try:
                _, created_n, updated_n = import_design_pack_payload(
                    request.user,
                    raw_json,
                    target_pack=pack,
                )
                messages.success(request, f"Imported into '{pack.name}' ({created_n} created, {updated_n} updated).")
                return redirect("spacemarches:design_pack_detail", slug=pack.slug)
            except (ValueError, PermissionError) as exc:
                messages.error(request, str(exc))
        elif action == "delete_entry":
            entry_id = (request.POST.get("entry_id") or "").strip()
            deleted, _ = pack.entries.filter(entry_id=entry_id, is_custom=True).delete()
            if deleted:
                messages.success(request, f"Deleted entry '{entry_id}'.")
            else:
                messages.error(request, "Entry not found or cannot be deleted.")
            return redirect("spacemarches:design_pack_detail", slug=pack.slug)
        elif action == "delete_pack":
            if pack.is_official:
                messages.error(request, "Official design packs cannot be deleted.")
                return redirect("spacemarches:design_pack_detail", slug=pack.slug)
            pack_name = pack.name
            with transaction.atomic():
                pack.entries.filter(is_custom=True).delete()
                pack.delete()
            messages.success(request, f"Deleted custom pack '{pack_name}'.")
            return redirect("spacemarches:design_pack_list")

    entries = list(order_ep2_queryset(pack.entries.all())[:120])
    total_entries = pack.entries.count()
    return render(
        request,
        "spacemarches/design_pack_detail.html",
        {
            "pack": pack,
            "entries": entries,
            "total_entries": total_entries,
            "can_edit": can_edit,
            "can_delete_pack": can_edit and not pack.is_official,
            "category_choices": Ep2Entry.CATEGORY_CHOICES,
        },
    )


@require_http_methods(["GET"])
def design_pack_export(request, slug: str):
    """Download a DesignPack and its entries as portable spacemarches-design-pack/v1 JSON."""
    pack = get_object_or_404(
        visible_design_packs_qs(request.user, include_storyteller=True),
        slug=slug,
    )
    resp = JsonResponse(
        export_design_pack_payload(pack),
        json_dumps_params={"indent": 2, "ensure_ascii": False},
    )
    resp["Content-Disposition"] = f'attachment; filename="{pack.slug}.designpack.json"'
    return resp


@require_http_methods(["GET"])
def api_design_packs(request):
    """List visible DesignPacks (rulebook tiers + public/owned custom packs)."""
    include_storyteller = _truthy_param(request.GET.get("storyteller"))
    packs = get_design_packs_with_counts(request.user, include_storyteller=include_storyteller)
    return JsonResponse({"count": len(packs), "packs": packs})


@require_http_methods(["GET"])
def api_design_pack_detail(request, slug: str):
    """Return full portable JSON payload for a single visible DesignPack."""
    pack = get_object_or_404(
        visible_design_packs_qs(request.user, include_storyteller=True),
        slug=slug,
    )
    return JsonResponse(export_design_pack_payload(pack))


@require_http_methods(["GET"])
def api_meshnet_packs(request):
    """Return visible DesignPacks formatted as MeshNet DesignPackPartial payloads."""
    include_storyteller = True if "storyteller" not in request.GET else _truthy_param(request.GET.get("storyteller"))
    packs = get_meshnet_packs_payload(request.user, include_storyteller=include_storyteller)
    return JsonResponse({"count": len(packs), "packs": packs})


# --------------------------------------------------
# Guided Eclipse Phase Census (Community Walkthrough)
# --------------------------------------------------


def _get_accessible_census(user, *, pk: int) -> EclipsePhaseCensus:
    qs = EclipsePhaseCensus.objects.select_related("user", "dossier", "character")
    if _is_admin(user):
        return get_object_or_404(qs, pk=pk)
    return get_object_or_404(qs, pk=pk, user=user)


def _log_census_st_only_access(request, census: EclipsePhaseCensus) -> None:
    if (census.protection or "none") != GeneratedCharacter.PROTECTION_ST_ONLY:
        return
    if not _is_st(request.user):
        return
    if request.user.is_authenticated and request.user.pk == census.user_id:
        return
    log_protection_access(
        target_kind=ProtectionAccessLog.TARGET_CENSUS,
        target_pk=census.pk,
        owner=census.user,
        viewer=request.user,
        protection_type=GeneratedCharacter.PROTECTION_ST_ONLY,
        note="Census view",
    )


def _build_census_question_nodes(
    census: EclipsePhaseCensus,
    questions: list[dict[str, Any]],
    *,
    sheet_ctx: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    responses = census.responses if isinstance(census.responses, dict) else {}
    default_voice = (
        "omniscient"
        if census.narrative_voice == EclipsePhaseCensus.VOICE_OMNISCIENT
        else "first_person"
    )
    nodes = []
    for q in questions:
        qid = q["id"]
        norm = normalize_census_record(responses.get(qid), default_voice=default_voice)
        is_answered = bool(q.get("answerable", True) and norm["answer"].strip())
        depth = 0
        pid = q.get("parent_id")
        if pid is not None:
            depth = 2 if (pid.startswith("6.1f") or pid == "6.2a" or pid.startswith("13") and len(pid) >= 3) else 1
        nodes.append(
            {
                "id": qid,
                "display_id": q.get("display_id") or qid,
                "chapter_id": q["chapter_id"],
                "parent_id": pid,
                "heading": q["heading"],
                "primer": q.get("primer") or "",
                "section_group": q.get("section_group", "main"),
                "answerable": bool(q.get("answerable", True)),
                "answer": norm["answer"],
                "voice": norm["voice"],
                "updated_at": norm["updated_at"],
                "is_answered": is_answered,
                "depth": depth,
                "synced_dossier_qid": CENSUS_TO_DOSSIER_MAP.get(qid) if census.dossier_id else None,
                "sheet_hint": get_census_question_sheet_hint(qid, sheet_ctx),
            }
        )
    return nodes


@login_required
@require_http_methods(["GET", "POST"])
def census_list(request):
    """List user's Eclipse Phase Census documents and initialize a new Census walkthrough."""
    user_dossiers = list(CharacterDossier.objects.filter(user=request.user).order_by("-updated_at"))
    user_characters = list(GeneratedCharacter.objects.filter(user=request.user).order_by("-updated_at"))

    if request.method == "POST":
        character_name = (request.POST.get("character_name") or "").strip()
        narrative_voice = (request.POST.get("narrative_voice") or EclipsePhaseCensus.VOICE_FIRST_PERSON).strip()
        dossier_id = (request.POST.get("dossier_id") or "").strip()
        character_id = (request.POST.get("character_id") or "").strip()
        show_sexuality = request.POST.get("show_sexuality_sections") != "0"
        show_appendix = _truthy_param(request.POST.get("show_sensitive_appendix"))

        dossier = None
        if dossier_id:
            dossier = get_object_or_404(CharacterDossier, pk=dossier_id, user=request.user)
        character = None
        if character_id:
            character = get_object_or_404(GeneratedCharacter, pk=character_id, user=request.user)

        try:
            census = create_census(
                request.user,
                character_name=character_name,
                narrative_voice=narrative_voice,
                dossier=dossier,
                character=character,
                show_sexuality_sections=show_sexuality,
                show_sensitive_appendix=show_appendix,
            )
        except ValueError as err:
            messages.error(request, str(err))
            return redirect("spacemarches:census_list")
        return redirect("spacemarches:census_detail", pk=census.pk)

    censuses = list(
        EclipsePhaseCensus.objects.filter(user=request.user)
        .select_related("dossier", "character")
        .order_by("-updated_at")
    )
    census_cards = [{"census": c, "stats": compute_census_stats(c)} for c in censuses]
    meta = get_census_meta()
    return render(
        request,
        "spacemarches/census_list.html",
        {
            "census_cards": census_cards,
            "dossiers": user_dossiers,
            "characters": user_characters,
            "voice_choices": EclipsePhaseCensus.NARRATIVE_VOICE_CHOICES,
            "meta": meta,
            "rendered_attribution": mark_safe(render_markdown_inline_safe(meta.get("attribution_notice") or "")),
            "rendered_source_credits": mark_safe(render_markdown_inline_safe(meta.get("source_credits") or "")),
            "prefill_dossier_id": (request.GET.get("dossier_id") or "").strip(),
            "prefill_character_id": (request.GET.get("character_id") or "").strip(),
        },
    )


@login_required
def census_detail(request, pk: int):
    """Guided chapter-by-chapter Eclipse Phase Census walkthrough."""
    census = _get_accessible_census(request.user, pk=pk)
    _log_census_st_only_access(request, census)

    meta = get_census_meta()
    stats = compute_census_stats(census)
    chapters = stats["chapters"]
    include_sexuality = bool(census.show_sexuality_sections)
    include_appendix = bool(census.show_sensitive_appendix)

    is_owner_view = census.user_id == request.user.pk
    primary_sheet = get_primary_linked_character_for_census(census)
    if primary_sheet is not None and not is_owner_view:
        primary_prot = protection_state(primary_sheet, request, viewer=request.user)
        if not (
            primary_prot["protection"] == GeneratedCharacter.PROTECTION_NONE
            or (primary_prot["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY and _is_st(request.user))
        ):
            primary_sheet = None
    sheet_ctx = build_sheet_prompt_context(primary_sheet)

    requested_chapter = (request.GET.get("chapter") or "").strip()
    valid_chapter_ids = {ch["id"] for ch in chapters}
    if requested_chapter in valid_chapter_ids:
        view_all = False
        active_chapter_id = requested_chapter
        active_chapter = get_census_chapter(active_chapter_id)
    else:
        view_all = True
        active_chapter_id = "all"
        active_chapter = None

    if view_all:
        raw_questions = get_all_census_questions(
            include_sexuality=include_sexuality,
            include_appendix=include_appendix,
            answerable_only=False,
        )
        question_nodes = _build_census_question_nodes(census, raw_questions, sheet_ctx=sheet_ctx)
        chapter_lookup = {ch["id"]: ch for ch in chapters}
        grouped_chapters = []
        for ch in chapters:
            if ch["is_appendix"] and not include_appendix:
                continue
            nodes = [n for n in question_nodes if n["chapter_id"] == ch["id"]]
            grouped_chapters.append({"chapter": ch, "nodes": nodes})
        prev_chapter = None
        next_chapter = None
    else:
        grouped_chapters = []
        raw_questions = get_chapter_questions(
            active_chapter_id,
            include_sexuality=include_sexuality,
            include_appendix=True,
            answerable_only=False,
        )
        question_nodes = _build_census_question_nodes(census, raw_questions, sheet_ctx=sheet_ctx)
        visible_chapters = [ch for ch in chapters if include_appendix or not ch["is_appendix"]]
        if active_chapter_id == "appendix" and not include_appendix:
            visible_chapters = chapters
        idx = next((i for i, ch in enumerate(visible_chapters) if ch["id"] == active_chapter_id), 0)
        prev_chapter = visible_chapters[idx - 1] if idx > 0 else None
        next_chapter = visible_chapters[idx + 1] if idx + 1 < len(visible_chapters) else None

    protection = protection_state(census, request, viewer=request.user)
    access_log = (
        list(
            ProtectionAccessLog.objects.filter(
                target_kind=ProtectionAccessLog.TARGET_CENSUS,
                target_pk=census.pk,
            )
            .select_related("viewer")
            .order_by("-created_at")[:20]
        )
        if is_owner_view
        else []
    )
    user_dossiers = (
        list(CharacterDossier.objects.filter(user=request.user).order_by("-updated_at"))
        if is_owner_view
        else []
    )
    user_characters = (
        list(GeneratedCharacter.objects.filter(user=request.user).order_by("-updated_at"))
        if is_owner_view
        else []
    )

    return render(
        request,
        "spacemarches/census_detail.html",
        {
            "census": census,
            "meta": meta,
            "stats": stats,
            "chapters": chapters,
            "view_all": view_all,
            "active_chapter_id": "all" if view_all else active_chapter_id,
            "active_chapter": active_chapter,
            "question_nodes": question_nodes,
            "grouped_chapters": grouped_chapters,
            "prev_chapter": prev_chapter,
            "next_chapter": next_chapter,
            "voice_choices": EclipsePhaseCensus.NARRATIVE_VOICE_CHOICES,
            "user_dossiers": user_dossiers,
            "user_characters": user_characters,
            "primary_sheet": primary_sheet,
            "sheet_context": sheet_ctx,
            "skill_pack_choices": get_sheet_skill_pack_choices(),
            "pending_sheet_changes": (
                compute_pending_sheet_changes(primary_sheet, dossier=census.dossier, census=census)
                if primary_sheet is not None
                else {"has_pending": False, "count": 0, "items": [], "suggested_name": ""}
            ),
            "is_owner_view": is_owner_view,
            "is_admin_override": not is_owner_view,
            "protection": protection,
            "access_log": access_log,
            "attribution_notice": get_census_attribution(),
            "rendered_attribution": mark_safe(render_markdown_inline_safe(get_census_attribution())),
            "rendered_source_credits": mark_safe(render_markdown_inline_safe(meta.get("source_credits") or "")),
        },
    )


@login_required
@require_POST
def census_answer(request, pk: int):
    """Save or clear an individual Eclipse Phase Census question response (JSON or form POST)."""
    census = _get_accessible_census(request.user, pk=pk)
    wants_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in (request.content_type or "")
    )

    if "application/json" in (request.content_type or ""):
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid JSON payload."}, status=400)
    else:
        payload = request.POST

    question_id = str(payload.get("question_id") or "").strip()
    if str(payload.get("action") or "").strip() == "clear":
        answer = ""
    else:
        answer = str(payload.get("answer_text") if "answer_text" in payload else (payload.get("answer") or ""))
    voice = str(payload.get("voice") or "").strip()
    active_chapter = str(payload.get("chapter") or "").strip()

    try:
        saved = save_census_answer(census, question_id, answer, voice=voice)
    except ValueError as err:
        if wants_json:
            return JsonResponse({"error": str(err)}, status=400)
        messages.error(request, str(err))
        target = reverse("spacemarches:census_detail", kwargs={"pk": census.pk})
        return redirect(f"{target}?chapter={active_chapter}" if active_chapter else target)

    stats = compute_census_stats(census)
    if wants_json:
        return JsonResponse({"status": "saved", **saved, "stats": stats})

    if saved["answered"]:
        messages.success(request, f"Saved response for [{question_id}].")
    else:
        messages.info(request, f"Cleared response for [{question_id}].")
    target = reverse("spacemarches:census_detail", kwargs={"pk": census.pk})
    return redirect(f"{target}?chapter={active_chapter}" if active_chapter else target)


@login_required
@require_POST
def census_settings(request, pk: int):
    """Update Census metadata, linked Dossier/Character, and optional section visibility toggles."""
    census = _get_accessible_census(request.user, pk=pk)
    active_chapter = (request.POST.get("chapter") or "").strip()
    action = (request.POST.get("action") or "update_settings").strip()

    if action == "toggle_sexuality":
        census.show_sexuality_sections = not census.show_sexuality_sections
        census.save(update_fields=["show_sexuality_sections", "updated_at"])
        messages.success(
            request,
            "Optional sexuality & experience sections (13c, 13e) enabled."
            if census.show_sexuality_sections
            else "Optional sexuality & experience sections (13c, 13e) hidden.",
        )
    elif action == "toggle_appendix":
        census.show_sensitive_appendix = not census.show_sensitive_appendix
        census.save(update_fields=["show_sensitive_appendix", "updated_at"])
        messages.success(
            request,
            "Sensitive Topics appendix enabled."
            if census.show_sensitive_appendix
            else "Sensitive Topics appendix hidden.",
        )
    elif action == "toggle_public":
        census.public_view = not census.public_view
        census.save(update_fields=["public_view", "updated_at"])
        messages.success(
            request,
            f"Public review enabled for {census.character_name}."
            if census.public_view
            else f"Public review disabled for {census.character_name}.",
        )
    else:
        new_name = (request.POST.get("character_name") or "").strip()
        if new_name:
            census.character_name = new_name[:160]
        raw_voice = (request.POST.get("narrative_voice") or "").strip()
        if raw_voice in {EclipsePhaseCensus.VOICE_FIRST_PERSON, EclipsePhaseCensus.VOICE_OMNISCIENT}:
            census.narrative_voice = raw_voice

        if census.user_id == request.user.pk:
            dossier_id = (request.POST.get("dossier_id") or "").strip()
            if dossier_id:
                census.dossier = get_object_or_404(CharacterDossier, pk=dossier_id, user=request.user)
            elif "dossier_id" in request.POST:
                census.dossier = None

            character_id = (request.POST.get("character_id") or "").strip()
            if character_id:
                census.character = get_object_or_404(GeneratedCharacter, pk=character_id, user=request.user)
            elif "character_id" in request.POST:
                census.character = None

        if "show_sexuality_sections" in request.POST:
            census.show_sexuality_sections = _truthy_param(request.POST.get("show_sexuality_sections"))
        if "show_sensitive_appendix" in request.POST:
            census.show_sensitive_appendix = _truthy_param(request.POST.get("show_sensitive_appendix"))
        if "public_view" in request.POST:
            census.public_view = _truthy_param(request.POST.get("public_view"))
        census.save()
        if census.dossier_id and census.dossier is not None:
            backfill_linked_census_and_dossier(census, census.dossier)
        messages.success(request, "Census preferences updated.")

    target = reverse("spacemarches:census_detail", kwargs={"pk": census.pk})
    return redirect(f"{target}?chapter={active_chapter}" if active_chapter else target)


@login_required
@require_POST
def census_protection(request, pk: int):
    """Set the protection lock on an EclipsePhaseCensus, or unlock it with the cipher."""
    census = get_object_or_404(EclipsePhaseCensus, pk=pk, user=request.user)
    active_chapter = (request.POST.get("chapter") or "").strip()
    target = reverse("spacemarches:census_detail", kwargs={"pk": census.pk})
    back_url = f"{target}?chapter={active_chapter}" if active_chapter else target
    action = (request.POST.get("action") or "save").strip()

    if action == "unlock":
        answer = (request.POST.get("answer") or "").strip()
        if not verify_secret(census, answer):
            messages.error(request, "Incorrect answer — the lock held.")
            return redirect(back_url)
        mark_unlocked(request, ProtectionAccessLog.TARGET_CENSUS, census.pk)
        messages.success(request, "Authenticated — Census unlocked.")
        return redirect(back_url)

    protection = (request.POST.get("protection") or "none").strip()
    if protection not in {choice[0] for choice in GeneratedCharacter.PROTECTION_CHOICES}:
        protection = GeneratedCharacter.PROTECTION_NONE

    puzzle_prompt = (request.POST.get("secret_puzzle_prompt") or "").strip()
    answer = (request.POST.get("secret_answer") or "").strip()

    census.protection = protection
    census.save(update_fields=["protection", "updated_at"])

    if protection == GeneratedCharacter.PROTECTION_SECRET:
        set_secret(census, puzzle_prompt, answer)
        messages.success(request, f"Secret lock armed for {census.character_name}.")
    else:
        clear_secret(census)
        messages.success(request, f"Protection set to {protection}.")
    return redirect(back_url)


@login_required
def census_export(request, pk: int):
    """Export an accessible EclipsePhaseCensus in Markdown, HTML, or JSON format."""
    census = _get_accessible_census(request.user, pk=pk)
    fmt = (request.GET.get("format") or "md").strip().lower()
    include_unanswered = _truthy_param(request.GET.get("include_unanswered"))

    if fmt == "json":
        payload = export_census_json(census)
        resp = JsonResponse(payload, json_dumps_params={"indent": 2, "ensure_ascii": False})
        resp["Content-Disposition"] = f'attachment; filename="{census.slug}-census.json"'
        return resp
    if fmt == "html":
        html_text = export_census_html(census, include_unanswered=include_unanswered)
        resp = HttpResponse(html_text, content_type="text/html; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{census.slug}-census.html"'
        return resp
    md_text = export_census_markdown(census, include_unanswered=include_unanswered)
    resp = HttpResponse(md_text, content_type="text/markdown; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{census.slug}-census.md"'
    return resp


@require_http_methods(["GET", "POST"])
def census_review(request, pk: int):
    """Public read-only review surface for a shared EclipsePhaseCensus, honoring protection locks."""
    census = get_object_or_404(
        EclipsePhaseCensus.objects.select_related("user", "dossier", "character"),
        pk=pk,
    )
    viewer = request.user if request.user.is_authenticated else None
    is_owner = viewer is not None and viewer.pk == census.user_id
    if not census.public_view and not is_owner:
        raise Http404("Eclipse Phase Census is private.")

    review_url = reverse("spacemarches:census_review", kwargs={"pk": census.pk})
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action == "unlock_census":
            answer = (request.POST.get("answer") or "").strip()
            if verify_secret(census, answer):
                mark_unlocked(request, ProtectionAccessLog.TARGET_CENSUS, census.pk)
                log_protection_access(
                    target_kind=ProtectionAccessLog.TARGET_CENSUS,
                    target_pk=census.pk,
                    owner=census.user,
                    viewer=viewer,
                    protection_type=GeneratedCharacter.PROTECTION_SECRET,
                    note="Secret unlocked",
                )
                return redirect(review_url)
            messages.error(request, "Incorrect answer — the lock held.")
            return redirect(review_url)
        return redirect(review_url)

    census_protection_state = protection_state(census, request, viewer=viewer)
    if (
        census_protection_state["protection"] == GeneratedCharacter.PROTECTION_ST_ONLY
        and census_protection_state["unlocked"]
        and not is_owner
    ):
        log_protection_access(
            target_kind=ProtectionAccessLog.TARGET_CENSUS,
            target_pk=census.pk,
            owner=census.user,
            viewer=viewer,
            protection_type=GeneratedCharacter.PROTECTION_ST_ONLY,
            note="Census review view",
        )

    stats = compute_census_stats(census)
    grouped_chapters = []
    if not census_protection_state["locked"]:
        all_qs = get_all_census_questions(
            include_sexuality=bool(census.show_sexuality_sections),
            include_appendix=bool(census.show_sensitive_appendix),
            answerable_only=True,
        )
        nodes = _build_census_question_nodes(census, all_qs)
        answered_nodes = [n for n in nodes if n["is_answered"]]
        for ch in stats["chapters"]:
            if ch["is_appendix"] and not census.show_sensitive_appendix:
                continue
            ch_nodes = [n for n in answered_nodes if n["chapter_id"] == ch["id"]]
            if ch_nodes:
                grouped_chapters.append({"chapter": ch, "nodes": ch_nodes})

    meta = get_census_meta()
    return render(
        request,
        "spacemarches/census_review.html",
        {
            "census": census,
            "census_protection": census_protection_state,
            "stats": stats,
            "grouped_chapters": grouped_chapters,
            "meta": meta,
            "review_url": review_url,
            "attribution_notice": get_census_attribution(),
            "rendered_attribution": mark_safe(render_markdown_inline_safe(get_census_attribution())),
            "rendered_source_credits": mark_safe(render_markdown_inline_safe(meta.get("source_credits") or "")),
        },
    )


@login_required
@require_POST
def census_delete(request, pk: int):
    """Delete an owned Eclipse Phase Census."""
    census = get_object_or_404(EclipsePhaseCensus, pk=pk, user=request.user)
    name = census.character_name
    census.delete()
    messages.info(request, f"Removed Census '{name}'.")
    return redirect("spacemarches:census_list")
