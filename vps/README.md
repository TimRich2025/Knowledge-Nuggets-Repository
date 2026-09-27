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

## Footage variety

A Short cut from one clip is one long take with jump cuts in it, and every
Short published before this section existed was built that way. Three rules in
`production_contract.py` now decide the matter, and both `POST /jobs` and the
ingest apply them:

- at least five distinct works per Short
- no work carrying more than a third of the scenes
- no more than two neighbouring scenes from the same work

A work is identified by its NASA asset id, so the catalogue page and the media
file of one asset count once.

Supplying that variety is the harder half, and asking a writing model for more
sources is what failed: a model cannot see a video, so it invents plausible
URLs and plausible timecodes and the ingest rejects the job. `POST /source-pool`
measures instead. It takes one search segment per third of the script and
returns a beat plan in which every URL is a real catalogue asset and every
interval was cut inside that asset's measured length. Beats are dealt out
across the works by rule, so the plan satisfies the three rules by
construction; the writing model only describes what each work shows.

Two things decide whether a run succeeds:

- **Search for the subject, never for the mission.** `Saturn V launch pad
  gantry` matches three usable works, `rocket launch pad ignition` matches
  eight. Five is the floor.
- **Send `fallback_queries`.** Two broader terms, used only when the segments
  miss the floor, so a script whose subject was named too exactly widens
  instead of failing.

What is measured is the interval, not the content: a beat is described from its
work's catalogue title. The pool carries each work's official storyboard frames
so a later vision pass can look before a beat claims what it shows.

## Soundtrack

No track ships with this repository. The renderer plays whatever licensed audio
sits in the music directory, `KN_MUSIC_DIR` (default `/data/music`), and renders
without a bed when the directory is empty, because a missing soundtrack is never
a reason to fail a finished Short.

One track is chosen per Short by hashing its content id, so a re-render sounds
identical and consecutive Shorts move through the library. The track is looped
to the narration's length, faded at both ends, set to `KN_MUSIC_GAIN_DB`
(default -19) and then ducked by the finished narration: measured against a
spoken passage the bed dips 11.5 dB while a word is being said and comes back in
the pause. A steeper setting reached 24 dB, which reads as the music switching
off and on rather than as it making room.

Put only audio you are licensed to publish on YouTube in that directory.
Nothing in this pipeline checks a licence.

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
