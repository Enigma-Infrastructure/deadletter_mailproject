import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods, require_POST

from .markdown_utils import render_markdown_safe
from .models import ArchiveEntry, CharacterDossier, DiscordLink, ForumPost, ForumThread
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
    save_dossier_answer,
)
from .services.game_sync_service import load_agent_save, sync_agent_save


# --------------------------------------------------
# Public Portal, Archives & Forum Reading
# --------------------------------------------------


def portal(request):
    """Public landing portal for Spacemarches."""
    recent_archives = ArchiveEntry.objects.filter(is_public=True).order_by("-created_at")[:5]
    recent_threads = ForumThread.objects.filter(is_public=True).select_related("author")[:5]
    summary = get_user_spacemarches_summary(request.user)
    return render(
        request,
        "spacemarches/portal.html",
        {
            "recent_archives": recent_archives,
            "recent_threads": recent_threads,
            "summary": summary,
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
# Authenticated Terminal & Cloud Save Sync (mesh-net)
# --------------------------------------------------


@login_required
def terminal(request):
    """Authenticated shell hosting the mesh-net terminal bundle and localStorage bridge."""
    slot_name = (request.GET.get("slot") or "auto").strip() or "auto"
    saved = load_agent_save(request.user, slot_name=slot_name)
    return render(
        request,
        "spacemarches/terminal.html",
        {
            "slot_name": saved["slot_name"],
            "initial_save": saved,
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


# --------------------------------------------------
# Authenticated Interactive Character Dossiers & Discord Link
# --------------------------------------------------


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
    discord_link = DiscordLink.objects.filter(user=request.user).first()
    return render(
        request,
        "spacemarches/dossier_list.html",
        {
            "dossier_cards": dossier_cards,
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


@login_required
def dossier_detail(request, slug: str):
    """Interactive progressive-disclosure questionnaire view for an owned CharacterDossier."""
    dossier = get_object_or_404(CharacterDossier, user=request.user, slug=slug)
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

    return render(
        request,
        "spacemarches/dossier_detail.html",
        {
            "dossier": dossier,
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
        },
    )


@login_required
@require_POST
def dossier_toggle_sensitive(request, slug: str):
    """Explicit opt-in toggle for sensitive appendix (13d1-13d6)."""
    dossier = get_object_or_404(CharacterDossier, user=request.user, slug=slug)
    dossier.show_sensitive_appendix = not dossier.show_sensitive_appendix
    dossier.save(update_fields=["show_sensitive_appendix", "updated_at"])
    return redirect("spacemarches:dossier_detail", slug=dossier.slug)


@login_required
@require_POST
def dossier_answer(request, slug: str):
    """Save an individual dossier progression update (supports JSON/fetch or standard form POST)."""
    dossier = get_object_or_404(CharacterDossier, user=request.user, slug=slug)

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
        return redirect("spacemarches:dossier_detail", slug=dossier.slug)

    if q.get("tier") == "sensitive_appendix" and not dossier.show_sensitive_appendix:
        if wants_json:
            return JsonResponse(
                {"error": "Enable the Sensitive Appendix opt-in toggle before editing 13d questions."},
                status=400,
            )
        messages.error(request, "Enable the Sensitive Appendix opt-in toggle before editing 13d questions.")
        return redirect("spacemarches:dossier_detail", slug=dossier.slug)

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
        return redirect("spacemarches:dossier_detail", slug=dossier.slug)

    if wants_json:
        return JsonResponse({"status": "saved", **stats})

    if privacy_only:
        messages.success(request, f"Updated GM Eyes Only privacy for [{question_id}].")
    else:
        messages.success(
            request,
            f"Saved [{question_id}] as {stats.get('version_label') or 'updated'}.",
        )
    return redirect("spacemarches:dossier_detail", slug=dossier.slug)


@login_required
def dossier_export(request, slug: str):
    """Export an owned CharacterDossier as a downloadable Markdown file."""
    dossier = get_object_or_404(CharacterDossier, user=request.user, slug=slug)
    include_private = request.GET.get("include_private") in {"1", "true", "yes"}
    md_text = export_dossier_markdown(dossier, include_private=include_private)
    response = HttpResponse(md_text, content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{dossier.slug}-dossier.md"'
    return response
