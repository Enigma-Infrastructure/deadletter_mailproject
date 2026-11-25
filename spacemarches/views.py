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
from django.utils.safestring import mark_safe
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from .markdown_utils import render_markdown_safe
from .models import ArchiveEntry, CharacterDossier, DesignPack, DiscordLink, Ep2Entry, ForumPost, ForumThread, GeneratedCharacter
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
from .services.character_sync_service import (
    export_generated_character_html,
    export_generated_character_markdown,
    link_character_to_dossier,
    save_generated_character,
    serialize_generated_character,
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
        GeneratedCharacter.objects.filter(user=request.user).select_related("dossier").order_by("-updated_at")
    )
    dossiers = list(CharacterDossier.objects.filter(user=request.user).order_by("-updated_at"))
    return render(
        request,
        "spacemarches/character_roster.html",
        {
            "characters": characters,
            "dossiers": dossiers,
            "voice_choices": CharacterDossier.NARRATIVE_VOICE_CHOICES,
        },
    )


@login_required
def character_export(request, pk: int):
    """Download a saved GeneratedCharacter as HTML, JSON, or Markdown."""
    qs = GeneratedCharacter.objects.select_related("dossier")
    if _is_gm_or_admin(request.user):
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

    if next_url.startswith("/spacemarches/"):
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


def _is_gm_or_admin(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False) and (user.is_staff or user.is_superuser))


def _get_accessible_dossier(user, *, slug: str = "", pk: int | None = None) -> CharacterDossier:
    is_admin = _is_gm_or_admin(user)
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
    if _is_gm_or_admin(request.user):
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
            "is_gm_or_admin": _is_gm_or_admin(request.user),
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


def _build_question_node(question: dict, responses: dict, private_keys: set[str], include_sensitive: bool) -> dict:
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
        child_node = _build_question_node(child, responses, private_keys, include_sensitive)
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
        "children": child_nodes,
    }


def _render_dossier_detail(request, dossier: CharacterDossier, *, by_id: bool = False):
    responses = dossier.responses if isinstance(dossier.responses, dict) else {}
    private_keys = set(dossier.private_keys or [])
    include_sensitive = bool(dossier.show_sensitive_appendix)

    core_nodes = [
        _build_question_node(q, responses, private_keys, include_sensitive)
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

    can_admin_reassign = _is_gm_or_admin(request.user)
    reassign_users = list(User.objects.order_by("username")) if can_admin_reassign else []
    dossier_reassign_url = (
        reverse("spacemarches:dossier_reassign_by_id", kwargs={"pk": dossier.pk})
        if can_admin_reassign
        else ""
    )

    linked_characters = list(
        dossier.generated_characters.order_by("-updated_at")
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

    return render(
        request,
        "spacemarches/dossier_detail.html",
        {
            "dossier": dossier,
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
            "dossier_answer_url": dossier_answer_url,
            "dossier_export_url": dossier_export_url,
            "dossier_toggle_url": dossier_toggle_url,
            "is_admin_override": dossier.user_id != request.user.pk,
            "can_admin_reassign": can_admin_reassign,
            "reassign_users": reassign_users,
            "dossier_reassign_url": dossier_reassign_url,
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
    if not _is_gm_or_admin(request.user):
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
