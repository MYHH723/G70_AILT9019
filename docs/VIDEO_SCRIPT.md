# 60-second recording plan

Target length 55-58 s. One real input, the system processing it, the resulting output. No slides.
Record the actual running app, not a mock-up.

## Before you press record (5 minutes)

1. `cd pathfinder && ./run.sh` - confirm `http://127.0.0.1:8765` loads.
2. Browser: new window, no other tabs, hide the bookmarks bar (`Cmd+Shift+B`), zoom to 110% (`Cmd +`).
3. macOS: turn on Do Not Disturb (Control Centre -> Focus -> Do Not Disturb). Quit Mail, Messages,
   Slack and anything that can pop a notification.
4. Close every window that shows your name, UID, transcript, email or an API key. The recording must
   contain no personal data.
5. Screen resolution 1440x900 or larger. QuickTime: **File -> New Screen Recording**, then drag a
   region around the browser window only (not the whole desktop).
6. Do one silent rehearsal. The plan below is tight; the first take is usually 15 s too long.

## Shot list

| Time | On screen | Say (or put on screen as a caption) |
|---|---|---|
| 0:00-0:04 | App header + the filled request panel. Cursor parked, nothing moving. | "HKU Pathfinder turns a student's goal into a plan that cites its evidence." |
| 0:04-0:12 | Scroll the request panel slowly: programme, cohort, year, completed courses, semester, interests, question. | "One real input: a Year 2 student, two courses completed, interested in data science, asking what to take next." |
| 0:12-0:16 | Click **Build plan**. The status line under the button changes. | "The plan is built from a frozen corpus, not from a language model guessing." |
| 0:16-0:22 | Result header: summary line + the yellow notice bar. | "Two courses pass every documented check - and one retrieved record tried to instruct the system, so it was quarantined." |
| 0:22-0:34 | Recommended courses. Hover the `STAT2601` card, then `COMP2119`. Point at `source - as of 2026-10-20`. | "Each course carries the reason it was allowed, a source link and an as-of date." |
| 0:34-0:42 | Opportunity card `OPP-NLP-RA`, then the "Leads that cannot be confirmed" panel: closed, snapshot, login wall. | "Only the lead with a live window is called open. The expired call is closed; the unreachable page is a dated snapshot marked verify manually." |
| 0:42-0:48 | Scroll to "Checked and not recommended": `COMP3314 blocked`, `COMP2120 not offered`. | "Blocked means a named missing prerequisite. Not offered means the target semester." |
| 0:48-0:53 | Scroll back up, click **Helpful** on the `COMP2119` card; the counter under it updates. | "Every recommendation takes a rating, stored locally and anonymously." |
| 0:53-0:58 | Scroll to **Next steps**, then stop. | "Same input, same output, every time - reproducible by anyone who clones the repository." |

## Captions

If you would rather not narrate, put these five lines on screen at the times shown. Keep them in the
top-left corner with a solid background so they stay readable.

- 0:00 `HKU Pathfinder - mid-term core workflow`
- 0:04 `Input: Year 2, COMP1117 + MATH1013 completed, data science`
- 0:16 `Retrieval -> documented constraint checks -> cited plan`
- 0:34 `Only a live window is labelled open`
- 0:53 `Deterministic and reproducible from the repository`

## Export

QuickTime -> **File -> Export As -> 1080p**, or `Save` and then:

```bash
ffmpeg -i recording.mov -vf "scale=1280:-2" -c:v libx264 -crf 23 -pix_fmt yuv420p \
       -c:a aac -b:a 128k AILT9019_GroupX_demo.mp4
```

Check before submitting:

- [ ] `ffprobe AILT9019_GroupX_demo.mp4` reports a duration of 60 s or less
- [ ] plays in QuickTime with sound (or readable captions if silent)
- [ ] no notification, no personal data, no API key, no terminal history visible
- [ ] the input, the processing and the output are all visible in the same take
- [ ] file size well under 100 MB (this recording should be 5-15 MB)

## If you run long

Cut, in this order: the `COMP2120` line (0:42-0:48), then the feedback click (0:48-0:53). Never cut
the blocked course, the closed call or the snapshot fallback - those are the evidence the rubric
asks for.
