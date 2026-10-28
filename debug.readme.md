# Audiopile debugging and TODO

## Documentation index

- [Usage manual](README.md)
- [Development and pipeline](dev.readme.md)
- [Debugging and TODO](debug.readme.md)

The items below distinguish observed failures from unimplemented improvements.

## Observed issues

| Symptom | Evidence / interpretation | Current handling |
|---|---|---|
| Whole job stopped updating progress | Windows denied replacement of `progress.json` (`WinError 5`), aborting the job. | Bounded replacement retries added and regression-tested; exhaustion can still abort. |
| Audio rename/access failures | `WinError 32`, `WinError 5` and missing-file errors during `.part`/audio renames. The locking process/root cause has not been established. | Song fails independently; do not assume overlapping workers caused it. |
| Audio postprocessing failure | yt-dlp reported it could not obtain the audio codec with ffprobe. | Not yet diagnosed; inspect source audio and FFmpeg/ffprobe availability before blaming YouTube restrictions. |
| Sign-in required | Midnight City's cached video returned generic `Please sign in`, not explicit age evidence. | Leave failed; generic sign-in alone does not establish age restriction. |
| Explicit age confirmation | Some later failures explicitly said `Sign in to confirm your age`. | Record separately; no restriction bypass or automatic authentication. |
| HTTP 403 | Download access denied. | Not proof of age restriction; preserve the error and cached URL. |
| HTTP 429 | Rate limiting was observed during an earlier retry. | Bulk requests were paused; shared automatic cooldown is not implemented. |
| Empty search result | Lookup produced no usable top result. | Leave the CSV URL blank; do not conclude the recording does not exist. |
| Stale results after interruption | Final `results.json`/CSV link writes may not have happened. | Consult tracker/progress and the run timestamp, not old results as current failures. |

### Last completed download snapshot: October 28, 2026

The CSV contained **1,326 playlist occurrences / 1,154 unique song IDs** across
41 catalog playlists. The last completed retry left **1,065 tracked songs**,
**89 audio failures** and **14 unresolved YouTube links**.

| Remaining category | Songs |
|---|---:|
| Windows file errors | 60 |
| Audio postprocessing | 7 |
| Empty search results | 14 |
| Explicit age confirmation | 3 |
| Generic sign-in | 1 |
| HTTP 403 | 3 |
| Other | 1 |

An earlier "718 missing audio / 715 missing links" snapshot was **not 718 failed
attempts**: 707 songs had not been attempted and 11 had previously failed.
Counts were deduplicated by song ID, excluding 172 repeated playlist occurrences.
These are historical snapshots, not live status.

`downloads\pending_songs.csv` and `downloads\sync_audit.json` were generated
during troubleshooting. They are local snapshots, not automatically refreshed
by the normal CLI. Current runtime files are described in `README.md`.

## Recovery and investigation

- Stop downloads before editing the tracker or removing a particular failed
  artifact. Never delete all downloads as a retry strategy.
- Resume from the existing song CSV with `--workers 2` or `--workers 1`; do not
  repeat Amazon scans unless playlist data needs updating. Tracked MP3s stay untouched.
- For file locks, identify the process holding the specific path; investigate
  concurrent jobs, external readers and scanners without assuming a culprit.
  Preserve completed files and source audio that may allow local conversion.
- For ffprobe errors, inspect the saved source and selected FFmpeg executable.
  Do not disable validation or mark a conversion failure as downloaded.
- For access errors, inspect the actual video's public playback/error message.
  Generic authentication, confirmed age restrictions, 403 and 429 are distinct.
  Do not bypass restrictions. Any future authenticated mode must be explicit and
  keep browser-session credentials out of Git and chat.
- Direct Amazon playlist links worked where profile discovery showed no public
  content. Signed-in library discovery remains experimental:
  `python .\src\export_playlists.py --library`. Sign in on Amazon itself; do not
  store credentials here. Public user-playlist totals often cannot be verified,
  and Amazon page-component changes may require extractor maintenance.

## Challenges / TODO

- Persist structured per-song states (`pending`, `downloaded`, `lookup_failed`,
  `auth_required`, `rate_limited`, `download_failed`) and resolved links
  incrementally. Distinguish never-attempted work from recorded failures.
- Define the fallback condition: classify 401/403 or sign-in responses first.
  For video-specific access failures, consider a matching publicly accessible,
  non-age-restricted recording; do not bypass restrictions or silently change
  versions. Commit a replacement CSV URL only after successful download/tagging.
- Defer fallback searches and bounded retries to a later pass instead of
  repeatedly occupying initial-batch workers. Preserve strict worker-sized
  barriers and the job-wide 10-worker ceiling. Finalize attempt deadlines,
  retry budgets and recording-match checks; these are not implemented yet.
- Implement shared HTTP 429 cooldown/backoff and reduced request concurrency,
  rather than searching alternate videos or immediately retrying every worker.
- Diagnose the Windows audio-file locks and postprocessing failures; make
  recovery bounded and avoid re-downloading recoverable source audio.
- Make progress reporting nonfatal after bounded file-lock retries, with a
  fallback diagnostic. Bounded progress replacement retries are implemented;
  nonfatal fallback is not.
