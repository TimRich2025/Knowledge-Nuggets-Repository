from __future__ import annotations
import base64, hashlib, hmac, json, os, re, secrets, subprocess, tempfile, time, urllib.parse, uuid
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from redis import Redis
from .config import API_TOKEN, REDIS_URL, OUTPUTS, ALLOWED_CALLBACK_URL, YOUTUBE_DATA_API_KEY, YOUTUBE_TREND_REGION, YOUTUBE_OAUTH_BOOTSTRAP_ENABLED, YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_REDIRECT_URI
from .visual_contract import validate_visual_contract
from .production_contract import validate_submission_contract
from .source_cache import IngestError
from .visual_probe import create_source_probe, make_probe_token, probe_frame_path, source_probe_key, verify_probe_token
from .source_catalog import SourceCatalogError, search_nasa_video_candidates
from .source_pool import (MAX_WIDENING_ROUNDS, SourcePoolError, UnmatchedBeats,
                          apply_observations, build_source_pool, collect_sources,
                          describe_request, loads_tolerant, observation_map,
                          plan_from_observations, probe_stream, unplaced_observations,
                          vision_payload, widen_for_beats)
from .scene_match import MATCH_FLOOR
from .storyboard import StoryboardError, sheet_path
from .social_metadata import MetadataError, build_social_metadata

app=FastAPI(title="Knowledge Nuggets Render Worker",version="1.1")
# Long enough for a vision pass and a retry, short enough that a forgotten pool
# does not sit in Redis for a day.
POOL_TTL_SECONDS=3600
_public_probe_requests: dict[str, list[float]] = {}
_MISSING_PROBE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WlP2r8AAAAASUVORK5CYII="
)

_LEGAL_STYLE = """
<style>
body{margin:0;background:#0a0d11;color:#eef2f7;font-family:Arial,sans-serif;line-height:1.65}
main{max-width:760px;margin:0 auto;padding:72px 24px}h1{font-size:clamp(2rem,6vw,3.6rem);line-height:1.05;margin:0 0 24px}
h2{margin-top:42px;color:#ff6b21}a{color:#ff8a4b}p,li{color:#c9d1da}.eyebrow{color:#ff6b21;font-weight:700;letter-spacing:.12em;text-transform:uppercase}
footer{margin-top:64px;border-top:1px solid #29313b;padding-top:20px;font-size:.9rem}
</style>
"""

def legal_page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title} | Knowledge Nuggets</title>{_LEGAL_STYLE}</head><body><main><p class='eyebrow'>Knowledge Nuggets</p><h1>{title}</h1>{body}<footer><a href='/'>Home</a> &nbsp; <a href='/privacy'>Privacy</a> &nbsp; <a href='/terms'>Terms</a><br>Contact: <a href='mailto:knowledge.nuggets1221@gmail.com'>knowledge.nuggets1221@gmail.com</a></footer></main></body></html>")

@app.get("/", include_in_schema=False)
def public_home():
    return legal_page("Knowledge Nuggets", "<p>Knowledge Nuggets produces short, fact-led educational videos. The production system creates and publishes videos privately to the channel authorized by its owner.</p><p>It is a private creator tool, not a public sign-up service.</p>")

@app.get("/privacy", include_in_schema=False)
def privacy_policy():
    return legal_page("Privacy Policy", "<p>Last updated: September 26, 2026.</p><h2>What this tool accesses</h2><p>Knowledge Nuggets uses the YouTube upload permission only after the channel owner grants it through Google. This permission is used solely to upload videos as private videos to the authorized YouTube channel.</p><h2>Data handling</h2><p>The system processes video files, production metadata and the OAuth credentials required for that upload. Credentials are stored as protected production configuration and are not sold, shared or used to access unrelated Google services.</p><h2>Retention and deletion</h2><p>The channel owner may revoke access at any time in their Google Account or request deletion of production data by contacting us. Revoking access prevents future uploads.</p><h2>Contact</h2><p>Questions about privacy can be sent to the contact address below.</p>")

@app.get("/terms", include_in_schema=False)
def terms_of_service():
    return legal_page("Terms of Service", "<p>Last updated: September 26, 2026.</p><h2>Purpose</h2><p>Knowledge Nuggets is a private production tool for creating educational short-form videos and uploading them privately to the channel selected by its owner.</p><h2>Authorized use</h2><p>The channel owner is responsible for the factual accuracy of published material, the rights to all assets and compliance with YouTube policies. The tool may only be connected to channels for which the owner has granted authorization.</p><h2>Availability</h2><p>The service may be updated, paused or improved to maintain production quality and security.</p><h2>Contact</h2><p>Questions about these terms can be sent to the contact address below.</p>")

class Job(BaseModel):
    content_id: str = Field(min_length=1,max_length=120)
    production_status: str
    core_question_lines: list[str]
    audio_url: str | None = None
    audio_base64: str | None = None
    # Make's Array Aggregator returns objects.  Accept the minimal object shape
    # (scene_number + audio_base64) as well as a bare base64 list, then enforce
    # the exact scene order during ingestion.
    scene_audio_base64: list[dict | str] | None = None
    tts_provider: str | None = None
    tts_voice: str | None = None
    tts_rate: str | None = None
    scenes: list[dict]
    callback_url: str | None = None
    topic: str | None = Field(default=None, max_length=240)
    fact_statement: str | None = Field(default=None, max_length=600)

class SourceProbe(BaseModel):
    source_url: str = Field(min_length=12, max_length=4000)
    candidate_start_seconds: float = Field(ge=0)
    candidate_end_seconds: float = Field(gt=0)

class SourceCandidateSearch(BaseModel):
    query: str = Field(min_length=2, max_length=240)
    limit: int = Field(default=6, ge=1, le=24)

class SourceSegment(BaseModel):
    query: str = Field(min_length=2, max_length=240)
    beats: int = Field(ge=1, le=40)

class SourcePoolRequest(BaseModel):
    segments: list[SourceSegment] = Field(min_length=1, max_length=8)
    # Broader terms, used only when the segments alone miss the source floor.
    fallback_queries: list[str] = Field(default_factory=list, max_length=6)
    per_query: int = Field(default=10, ge=1, le=24)
    window_seconds: float = Field(default=3.2, ge=1.5, le=4.0)
    callback_url: str | None = None

class ObservedFrame(BaseModel):
    index: int = Field(ge=1, le=64)
    at_seconds: float = Field(ge=0)
    describes: str = Field(default="", max_length=2000)

class ObservedWork(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=200)
    direct_download_url: str = Field(min_length=12, max_length=4000)
    selected_asset_page_url: str = Field(default="", max_length=4000)
    title: str = Field(default="", max_length=400)
    width: int = Field(default=1920, ge=0)
    height: int = Field(default=1080, ge=0)
    measured_duration_seconds: float = Field(gt=0)
    frames: list[ObservedFrame] = Field(default_factory=list, max_length=64)

class BeatRequirement(BaseModel):
    visual_target: str = Field(default="", max_length=600)
    spoken_phrase: str = Field(default="", max_length=600)
    must_show: list[str] = Field(default_factory=list, max_length=12)

class FrameObservation(BaseModel):
    index: int = Field(ge=1, le=64)
    describes: str = Field(default="", max_length=2000)

class WorkObservation(BaseModel):
    # Either the work's own id, copied back, or the image number the request
    # listed it under. The number is one or two digits and a model gets it right;
    # a seventy-character catalogue id it sometimes does not, and a description
    # that lands on no work at all is the same as not having looked.
    candidate_id: str = Field(default="", max_length=200)
    image: int | None = Field(default=None, ge=1, le=64)
    frames: list[FrameObservation] = Field(default_factory=list, max_length=64)

class SourcePlanRequest(BaseModel):
    # Both lists may arrive as JSON text, which is what a language model hands
    # back when a scenario splices its answer straight into a request body.
    beats: list[BeatRequirement] | str = Field(min_length=1)
    # Either the pool this plan belongs to, or the works spelled out in full.
    # The pool id is the normal path: it keeps every URL and measured number on
    # this side, so no model can mistype one into a job.
    pool_id: str = Field(default="", max_length=64)
    observations: list[WorkObservation] | str = Field(default_factory=list)
    works: list[ObservedWork] = Field(default_factory=list, max_length=40)
    window_seconds: float = Field(default=3.2, ge=1.5, le=4.0)
    match_floor: float = Field(default=MATCH_FLOOR, ge=0.1, le=0.9)
    # The last look there will be. A caller that can still run another vision
    # pass leaves this false and is offered one; a caller that cannot sets it,
    # and an unserved beat is then a refusal rather than another round.
    final: bool = False
    callback_url: str | None = None

class SocialMetadata(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    fact_statement: str = Field(default="", max_length=600)

def db():
    if not REDIS_URL: raise HTTPException(503,"REDIS_URL is not configured")
    return Redis.from_url(REDIS_URL,decode_responses=True,socket_connect_timeout=5,socket_timeout=5)

def auth(authorization: str | None):
    if not API_TOKEN: raise HTTPException(503,"KN_API_TOKEN is not configured")
    if authorization != f"Bearer {API_TOKEN}": raise HTTPException(401,"unauthorized")

def safe_id(v: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+","-",v).strip("-")[:80] or "job"

def public_base_url(request: Request) -> str:
    configured = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
    if configured:
        return configured
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host", request.headers.get("host", request.url.netloc)).split(",")[0].strip()
    if not host:
        raise HTTPException(500, "public host unavailable")
    return f"{proto}://{host}"

def allow_public_probe(request: Request) -> None:
    """Rate-limit the image-only gateway used by Make's existing Vision module."""
    client = request.client.host if request.client else "unknown"
    now = time.time()
    recent = [stamp for stamp in _public_probe_requests.get(client, []) if stamp > now - 600]
    if len(recent) >= 12:
        raise HTTPException(429, "source probe rate limit reached")
    recent.append(now)
    _public_probe_requests[client] = recent


def oauth_bootstrap_state_key() -> str:
    return "kn:youtube_oauth:state"


def oauth_bootstrap_available() -> None:
    if not YOUTUBE_OAUTH_BOOTSTRAP_ENABLED:
        raise HTTPException(404, "YouTube OAuth bootstrap is disabled")
    if not YOUTUBE_OAUTH_CLIENT_ID or not YOUTUBE_OAUTH_REDIRECT_URI:
        raise HTTPException(503, "YouTube OAuth bootstrap is not configured")


@app.get("/oauth/youtube/start", include_in_schema=False)
def youtube_oauth_start():
    """One-time, time-bounded consent handoff for the private publisher."""
    oauth_bootstrap_available()
    state = secrets.token_urlsafe(32)
    db().setex(oauth_bootstrap_state_key(), 600, state)
    query = urllib.parse.urlencode({
        "client_id": YOUTUBE_OAUTH_CLIENT_ID,
        "redirect_uri": YOUTUBE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/youtube.upload",
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@app.get("/oauth/youtube/callback", include_in_schema=False)
def youtube_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    oauth_bootstrap_available()
    expected = db().get(oauth_bootstrap_state_key())
    if not expected or not state or not hmac.compare_digest(expected, state):
        raise HTTPException(400, "invalid or expired OAuth session")
    r = db()
    if error or not code:
        r.setex("kn:youtube_oauth:error", 600, error or "Google returned no authorization code")
        return legal_page("Authorization not completed", "<p>YouTube permission was not granted. Return to the production setup and try again.</p>")
    r.setex("kn:youtube_oauth:code", 300, code)
    poll = f"/oauth/youtube/result?state={urllib.parse.quote(state)}"
    body = (
        "<p>YouTube permission was received. The production worker is creating the private upload credential now.</p>"
        "<p id='status'>Waiting for the worker. Keep this page open.</p>"
        f"<script>const u='{poll}';const p=async()=>{{const r=await fetch(u);if(r.status===202){{setTimeout(p,1500);return}}document.getElementById('status').textContent=await r.text();}};p();</script>"
    )
    return legal_page("YouTube authorization received", body)


@app.get("/oauth/youtube/result", include_in_schema=False)
def youtube_oauth_result(state: str):
    oauth_bootstrap_available()
    r = db()
    expected = r.get(oauth_bootstrap_state_key())
    if not expected or not hmac.compare_digest(expected, state):
        raise HTTPException(404, "OAuth session unavailable")
    error = r.get("kn:youtube_oauth:error")
    if error:
        r.delete(oauth_bootstrap_state_key(), "kn:youtube_oauth:error")
        raise HTTPException(422, error)
    if r.get("kn:youtube_oauth:status") != "READY":
        return Response(status_code=202)
    r.delete(oauth_bootstrap_state_key(), "kn:youtube_oauth:status")
    return HTMLResponse("<p id='ready'>Private YouTube publishing is connected.</p>")

@app.get("/health")
def health():
    try: db().ping(); queue="ok"
    except Exception as e: raise HTTPException(503,f"queue unavailable: {e}")
    return {"ok":True,"service":"kn-render-api","queue":queue,"layout":"KN_LAYOUT_V1"}

@app.post("/source-probes")
def source_probe(payload: SourceProbe, request: Request, authorization: str | None = Header(default=None)):
    auth(authorization)
    try:
        result = create_source_probe(payload.source_url, payload.candidate_start_seconds, payload.candidate_end_seconds)
    except IngestError as exc:
        raise HTTPException(422, str(exc))
    token = make_probe_token(result["probe_id"])
    base = public_base_url(request)
    result["frame_urls"] = [
        f"{base}/source-probes/{result['probe_id']}/{frame['name']}?token={token}&t={frame['approx_seconds']}"
        for frame in result.pop("frames")
    ]
    result["contact_sheet_url"] = (
        f"{base}/source-probes/{result['probe_id']}/{result.pop('contact_sheet_name')}?token={token}"
    )
    result["evidence_policy"] = "Vision may mark VERIFIED only for a continuous interval visibly proven by these frames; otherwise UNVERIFIED."
    return result

@app.post("/source-candidates")
def source_candidates(payload: SourceCandidateSearch, authorization: str | None = Header(default=None)):
    """Discover direct official candidates, never an approval or render input."""
    auth(authorization)
    try:
        candidates = search_nasa_video_candidates(payload.query, payload.limit)
    except SourceCatalogError as exc:
        raise HTTPException(502, str(exc))
    return {
        "query": payload.query,
        "source_family": "NASA Images",
        "candidates": candidates,
        "approval_policy": "Every candidate remains UNVERIFIED. A visible-frame review and an exact continuous shot interval are mandatory before rendering.",
    }

@app.post("/source-pool")
def source_pool(payload: SourcePoolRequest, request: Request, authorization: str | None = Header(default=None)):
    """Return a measured multi-source beat plan, so no model has to invent one.

    Authorised the same way as /jobs: Make identifies itself by the callback URL
    it is already configured with, anything else needs the bearer token.  The
    rate limit applies either way, because every call costs the NASA catalogue
    several queries and one header read per candidate clip.
    """
    if not (ALLOWED_CALLBACK_URL and payload.callback_url == ALLOWED_CALLBACK_URL):
        auth(authorization)
    allow_public_probe(request)
    try:
        return build_source_pool(
            [segment.model_dump() for segment in payload.segments],
            fallback_queries=[q for q in payload.fallback_queries if q.strip()],
            per_query=payload.per_query,
            window_seconds=payload.window_seconds,
        )
    except SourcePoolError as exc:
        raise HTTPException(422, str(exc))
    except SourceCatalogError as exc:
        raise HTTPException(502, str(exc))

@app.get("/storyboards/{identifier}.jpg")
def storyboard_sheet(identifier: str, request: Request):
    """Serve a prebuilt sheet of catalogue stills.

    Public and unauthenticated for the same reason the contact-sheet route is:
    the vision pass fetches it by URL and carries no credential. It exposes
    nothing but a tiling of images the catalogue already publishes openly.
    """
    allow_public_probe(request)
    try:
        return FileResponse(sheet_path(identifier), media_type="image/jpeg",
                            filename=f"{identifier}.jpg")
    except StoryboardError as exc:
        raise HTTPException(404, str(exc))

@app.post("/source-pool/candidates")
def source_pool_candidates(payload: SourcePoolRequest, request: Request,
                           authorization: str | None = Header(default=None)):
    """Discover works and hand back the picture evidence needed to judge them.

    The plan is deliberately not built here. A beat can only be paired with
    footage once something has looked at the footage, so this call ends with a
    contact sheet per work and the second of each numbered frame.
    """
    if not (ALLOWED_CALLBACK_URL and payload.callback_url == ALLOWED_CALLBACK_URL):
        auth(authorization)
    allow_public_probe(request)
    try:
        sources = collect_sources(
            [segment.model_dump() for segment in payload.segments],
            payload.per_query, payload.window_seconds,
            search_nasa_video_candidates, probe_stream)
    except SourcePoolError as exc:
        raise HTTPException(422, str(exc))
    except SourceCatalogError as exc:
        raise HTTPException(502, str(exc))
    described = describe_request(sources, public_base_url(request))
    pool_id = uuid.uuid4().hex
    try:
        db().setex(f"kn:pool:{pool_id}", POOL_TTL_SECONDS,
                   json.dumps({"works": described, "observations": {}, "rounds": 0}))
    except HTTPException:
        pool_id = ""
    return {"pool_id": pool_id, "sources": described, **vision_payload(described),
            "frame_policy": ("Each frame's at_seconds is its real position in the clip. "
                             "Describe what is visible in that tile only, in plain nouns.")}

@app.post("/source-pool/plan")
def source_pool_plan(payload: SourcePlanRequest, request: Request,
                     authorization: str | None = Header(default=None)):
    """Pair every beat with footage that was seen to contain what it needs.

    When some beat has nothing, the call does not simply refuse. It searches
    again for what those beats ask for, adds the new works to the same pool and
    hands back their contact sheets, so the caller's next move is one more look
    rather than a fresh start.

    The caller that drives this runs its second look whether or not it was
    needed, because a linear flow cannot skip a step and carry on. So a call
    that matched everything answers MATCHED and still offers something to look
    at, the plan it produced is kept, and the second call is given that same
    plan back: a pairing already made can never be unmade by a look that was
    only taken for the sake of the flow. `final` says this is the last look
    there will be, and then an unserved beat is a refusal rather than another
    round.
    """
    if not (ALLOWED_CALLBACK_URL and payload.callback_url == ALLOWED_CALLBACK_URL):
        auth(authorization)
    beats = loads_tolerant(payload.beats) if isinstance(payload.beats, str) \
        else [beat.model_dump() for beat in payload.beats]
    if not beats:
        raise HTTPException(422, "no readable beats were supplied")
    incoming = loads_tolerant(payload.observations) if isinstance(payload.observations, str) \
        else [entry.model_dump() for entry in payload.observations]

    key = f"kn:pool:{safe_id(payload.pool_id)}" if payload.pool_id else ""
    state = {"works": [work.model_dump() for work in payload.works],
             "observations": {}, "rounds": 0, "plan": None}
    if key:
        stored = db().get(key)
        if not stored:
            raise HTTPException(409, "that source pool has expired; discover the works again")
        loaded = json.loads(stored)
        # An older pool held the works alone. Read both shapes so a run started
        # before this change can still finish.
        state = loaded if isinstance(loaded, dict) else {"works": loaded, "observations": {},
                                                         "rounds": 0, "plan": None}
    settled = state.get("plan")
    if settled:
        return {**settled, "status": "MATCHED"}

    held = state.get("works", [])
    described = {**state.get("observations", {}), **observation_map(incoming, held)}
    works = apply_observations(held, described)
    if not works:
        raise HTTPException(422, "supply either a pool_id with observations, or works in full")
    stray = unplaced_observations(incoming, held)
    if stray and not described:
        # Every description named something this pool does not hold, so nothing
        # was looked at as far as the matcher is concerned. Say which names, or
        # the next person sees only "no frame descriptions" and cannot tell why.
        raise HTTPException(422, "the vision pass described works this pool does not "
                                 f"hold: {', '.join(stray[:10])}")

    def remember(**changed) -> None:
        if key:
            db().setex(key, POOL_TTL_SECONDS,
                       json.dumps({**state, "observations": described, **changed}))

    try:
        result = plan_from_observations(beats, works, window_seconds=payload.window_seconds,
                                        match_floor=payload.match_floor)
    except UnmatchedBeats as exc:
        rounds = int(state.get("rounds", 0))
        fresh = []
        if key and not payload.final and rounds < MAX_WIDENING_ROUNDS:
            fresh = widen_for_beats(state.get("works", []), exc.retry_queries,
                                    public_base_url(request),
                                    window_seconds=payload.window_seconds)
        if fresh:
            remember(works=state.get("works", []) + fresh, rounds=rounds + 1)
            # 200, not an error: the request was well formed, the footage simply
            # did not show what these beats need, and the body is the next step.
            return {"status": "LOOK_AGAIN", "pool_id": payload.pool_id,
                    "detail": str(exc), "unmatched_beats": exc.unmatched,
                    "retry_queries": exc.retry_queries, "round": rounds + 1,
                    "new_sources": fresh, "second_look": vision_payload(fresh)}
        remember()
        raise HTTPException(409, {"detail": str(exc), "status": "NO_MATCHING_FOOTAGE",
                                  "unmatched_beats": exc.unmatched,
                                  "retry_queries": exc.retry_queries,
                                  "rounds_spent": rounds})
    except (SourcePoolError, ValueError) as exc:
        raise HTTPException(422, str(exc))

    remember(plan=result)
    if payload.final:
        return {**result, "status": "MATCHED"}
    # Something valid to look at, so the caller's unconditional second look is a
    # well formed request. Its answer changes nothing: the plan above is kept.
    return {**result, "status": "MATCHED", "second_look": vision_payload(works[:1])}

@app.post("/social-metadata")
def social_metadata(payload: SocialMetadata, authorization: str | None = Header(default=None)):
    """Build the unique publish copy immediately before a Short is uploaded."""
    auth(authorization)
    try:
        return build_social_metadata(
            payload.topic,
            payload.fact_statement,
            api_key=YOUTUBE_DATA_API_KEY,
            region=YOUTUBE_TREND_REGION,
        )
    except MetadataError as exc:
        raise HTTPException(422, str(exc)) from exc

@app.get("/source-probes/{probe_id}/{frame_name}")
def source_probe_frame(probe_id: str, frame_name: str, token: str):
    if not verify_probe_token(probe_id, token):
        raise HTTPException(401, "invalid probe token")
    try:
        path = probe_frame_path(probe_id, frame_name)
    except IngestError as exc:
        raise HTTPException(404, str(exc))
    return FileResponse(path, media_type="image/jpeg", filename=frame_name)

@app.get("/source-probes/contact-sheet.jpg")
def public_source_probe_contact_sheet(
    request: Request,
    source_url: str,
    candidate_start_seconds: float,
    candidate_end_seconds: float,
    samples: int = 0,
):
    # This route exists because Make's image analyser can fetch an image URL but
    # the user's plan cannot run Make's generic HTTP module. It exposes only a
    # bounded contact sheet from an approved public source family, never media.
    allow_public_probe(request)
    if source_url == "MISSING":
        return Response(content=_MISSING_PROBE_PNG, media_type="image/png")
    try:
        wanted = max(0, min(12, int(samples)))
        probe_id = source_probe_key(source_url, candidate_start_seconds,
                                    candidate_end_seconds + wanted / 1000.0)
        result = create_source_probe(source_url, candidate_start_seconds, candidate_end_seconds,
                                     probe_id=probe_id, samples=wanted or None)
        path = probe_frame_path(result["probe_id"], result["contact_sheet_name"])
    except IngestError as exc:
        raise HTTPException(422, str(exc))
    return FileResponse(path, media_type="image/jpeg", filename="contact-sheet.jpg")

@app.post("/jobs",status_code=202)
def submit(job: Job, authorization: str | None = Header(default=None)):
    make_callback_ok = bool(ALLOWED_CALLBACK_URL and job.callback_url == ALLOWED_CALLBACK_URL)
    if not make_callback_ok:
        auth(authorization)
    if job.production_status != "READY": raise HTTPException(422,"production_status must be READY")
    if len(job.core_question_lines)!=2: raise HTTPException(422,"exactly two core question lines required")
    if not job.scenes: raise HTTPException(422,"at least one scene required")
    try:
        validate_submission_contract(job.model_dump())
    except ValueError as e:
        raise HTTPException(422, str(e))
    for i,s in enumerate(job.scenes,1):
        try: validate_visual_contract(s, i)
        except ValueError as e: raise HTTPException(422, str(e))
        if s.get("semantic_match") != "EXACT":
            raise HTTPException(422,f"scene {i}: semantic_match must be EXACT")
        if s.get("temporal_match") != "VERIFIED":
            raise HTTPException(422,f"scene {i}: temporal_match must be VERIFIED")
        try:
            ss=float(s["shot_start_seconds"]); se=float(s["shot_end_seconds"])
        except Exception:
            raise HTTPException(422,f"scene {i}: verified shot interval required")
        if float(s.get("semantic_score") or 0) < 94:
            raise HTTPException(422,f"scene {i}: semantic score below exact-match gate")
        if str(s.get("media_type") or "").upper() != "VIDEO":
            raise HTTPException(422,f"scene {i}: real video source required")
        if not (s.get("source_url") or s.get("direct_download_url")):
            raise HTTPException(422,f"scene {i}: exact direct video URL required")
    jid=f"{safe_id(job.content_id)}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    r=db(); payload=job.model_dump(); payload["_job_id"]=jid
    r.hset(f"kn:job:{jid}",mapping={"state":"PENDING","payload":json.dumps(payload),"updated_at":str(time.time())})
    r.rpush("kn:queue",jid)
    return {"accepted":True,"job_id":jid,"state":"PENDING"}

@app.get("/jobs/{job_id}")
def status(job_id: str, authorization: str | None = Header(default=None)):
    auth(authorization); r=db(); data=r.hgetall(f"kn:job:{safe_id(job_id)}")
    if not data: raise HTTPException(404,"job not found")
    return {"job_id":job_id,"state":data.get("state"),"result":json.loads(data["result"]) if data.get("result") else None,"error":json.loads(data["error"]) if data.get("error") else None}


@app.get("/jobs/{job_id}/preview")
def preview(job_id: str, authorization: str | None = Header(default=None)):
    auth(authorization); r=db(); data=r.hgetall(f"kn:job:{safe_id(job_id)}")
    if not data: raise HTTPException(404,"job not found")
    if data.get("state") != "COMPLETED" or not data.get("result"):
        raise HTTPException(409,"preview is not ready")
    result=json.loads(data["result"]); p=Path(result.get("preview_path") or "").resolve()
    root=OUTPUTS.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404,"preview artifact unavailable")
    return FileResponse(p,media_type="video/mp4",filename=f"{safe_id(job_id)}.mp4")


@app.get("/preview/{content_id}")
def public_preview(content_id: str, token: str):
    cid=safe_id(content_id)
    expected=hashlib.sha256(f"{API_TOKEN}:{cid}".encode()).hexdigest()
    if not API_TOKEN or not hmac.compare_digest(token,expected):
        raise HTTPException(401,"invalid preview token")
    p=(OUTPUTS/cid/"preview.mp4").resolve(); root=OUTPUTS.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404,"preview artifact unavailable")
    return FileResponse(p,media_type="video/mp4",filename=f"{cid}.mp4")


@app.get("/preview/{content_id}/frame")
def public_preview_frame(content_id: str, token: str, t: float = 1.0):
    cid=safe_id(content_id)
    expected=hashlib.sha256(f"{API_TOKEN}:{cid}".encode()).hexdigest()
    if not API_TOKEN or not hmac.compare_digest(token,expected):
        raise HTTPException(401,"invalid preview token")
    p=(OUTPUTS/cid/"preview.mp4").resolve(); root=OUTPUTS.resolve()
    if root not in p.parents or not p.is_file():
        raise HTTPException(404,"preview artifact unavailable")
    out=OUTPUTS/cid/f"frame-{max(0.0,min(float(t),60.0)):.2f}.jpg"
    cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-ss",f"{max(0.0,min(float(t),60.0)):.3f}","-i",str(p),"-frames:v","1","-vf","scale=270:480","-q:v","5",str(out)]
    q=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
    if q.returncode or not out.is_file():
        raise HTTPException(500,"frame extraction failed")
    return FileResponse(out,media_type="image/jpeg",filename=out.name)
