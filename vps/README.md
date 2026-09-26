# Knowledge Nuggets persistent render worker

This replaces GitHub Actions as the production runtime. GitHub stores code only; Make remains the orchestrator.

## Reliability boundary

1. `POST /jobs` only accepts READY packages.
2. The worker first ingests every remote video/audio asset into persistent `/data/cache` and ffprobes it.
3. Rendering starts only after all required assets are local and verified.
4. The renderer receives local filesystem paths only. A remote 429/5xx cannot interrupt an active render.
5. The final frame is checked against `KN_LAYOUT_V1`; header MAE > 12 fails QC.
6. After every production gate succeeds, the worker can publish the result to
   YouTube only as `private`. A failed gate cannot produce an upload.

## Publish metadata contract

Immediately before any YouTube upload, Make calls `POST /social-metadata` with
the Short's English `topic` and a concise factual statement from the approved
script. Use the returned `title` and `description` together: the title is
always the exact beginning of the description, starts with `but the fact is,`
and remains within YouTube's 100-character title limit. The description
contains at most five relevant hashtags, including `#Shorts`.

## Unattended private publishing

After a render passes every production gate, the worker uploads it directly to
YouTube as `private`. It never has a public or unlisted code path. The OAuth
credential has the YouTube upload scope and remains only in the protected
production Redis store. The worker refreshes access tokens itself for every
run. A missing or invalid OAuth configuration fails the job rather than
silently leaving a finished video unpublished.

Set `KN_YOUTUBE_DATA_API_KEY` on the worker to live-rank topic-related hashtags
from recent high-view YouTube Shorts. Set `KN_YOUTUBE_TREND_REGION` if the
target market is not US. Without the API key the endpoint returns a labelled
topic fallback, never pretends to have a live trend signal. Store the API key in
the deployment's environment only, never in this repository.

## Deploy

Copy `.env.example` to `.env`, set a long `KN_API_TOKEN`, then:

```bash
docker compose -f docker-compose.vps.yml up -d --build
```

Expose port 8080 through HTTPS before connecting Make. Do not expose the worker directly without TLS and bearer auth.

## Job payload

`POST /jobs` with `Authorization: Bearer <KN_API_TOKEN>` and JSON containing:

- `content_id`
- `production_status: READY`
- `core_question_lines` (exactly two)
- `tts_provider: EDGE` with an approved natural male Edge voice and a natural
  speaking rate
- `scenes[]` with an official `source_url`, exact verified visual interval,
  plain-language phrase and matching tight caption beats
- optional `callback_url`
