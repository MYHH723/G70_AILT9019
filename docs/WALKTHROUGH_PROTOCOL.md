# Walkthrough protocol

Five volunteers, three minutes each. This is the only acceptance item in the proposal that a script
cannot produce, so the protocol is written to make it cheap and to make the record trustworthy.

**Target:** at least 4 of 5 volunteers reach a result that shows a source link and an as-of date,
without editing code, changing configuration, or installing anything.

## 1. Before the session

- Recruit five people who are **not** in the team. Undergraduates outside the module are better than
  classmates, because classmates already know how the pilot works.
- Use a clean copy of the repository, not your working tree:
  ```bash
  git clone https://github.com/MYHH723/G70_AILT9019.git /tmp/pathfinder-walkthrough
  cd /tmp/pathfinder-walkthrough
  ./run.sh
  ```
- Have the browser open at <http://127.0.0.1:8765> and nothing else on screen.

## 2. What to say, word for word

> "This is a prototype that helps students plan courses and find research or internship leads.
> Your job is to complete one task. I will not help you, and I am timing it. Please think aloud if
> you can. If something is confusing, say so — that is the useful part."

Then read the task text from the table below and start the timer.

## 3. Tasks

| Letter | Task text to read |
|---|---|
| A | Build a plan with the default profile. Open one source link and confirm it matches the plan. |
| B | Load preset P3, build a plan, and tell me in one sentence why a course was blocked or deferred. |
| C | Ask whether the computer vision internship is still open, and tell me what the answer means. |
| D | Ask a question about a different programme, and tell me what the system does. |

Rotate the letters so the five sessions cover all four tasks and one repeat.

## 4. What not to do

- Do not point at the screen, name a button, or finish a sentence.
- Do not explain the difference between a blocked and a deferred course.
- Do not rescue a volunteer who is stuck for less than two minutes. Note the stall instead.
- If they ask "is this right?", answer "what do you think?" and record the question.

## 5. Recording

```bash
python3 -m tests.walkthrough --start --task A          # prints a session id
python3 -m tests.walkthrough --finish <id> --cited yes --edited no --seconds 187
python3 -m tests.walkthrough --report                  # writes docs/walkthrough_<date>.md
```

| Field | Counts as success | Counts as failure |
|---|---|---|
| `--cited` | The result shows a source link and an as-of date, and the volunteer noticed it | No citation found, or the volunteer could not tell what the source was |
| `--edited` | No file was edited, no config changed, no package installed | Any edit, even a trivial one — the criterion is first use without editing |

Record `--seconds` from the timer, not from memory. Add a short `--notes` only for a blocking defect,
for example `--notes "could not find the export button"`.

## 6. Privacy

The record holds a random session id, a task letter, timings and two yes/no answers. It must not hold
a name, student number, email, screenshot, or anything the volunteer typed about themselves. Do not
ask volunteers to enter real course records; the default profiles are synthetic for this reason.

## 7. What to do with the result

- **4 or 5 succeed:** report the number as measured, and note that five computing students are not a
  representative sample.
- **3 or fewer succeed:** treat it as a usability defect. The usual causes are the result cards being
  too long to scan, the source link being below the fold, and "blocked" reading as an error rather
  than a finding. Fix one thing, then re-run the sessions that failed.
- **A volunteer edits code:** the session is a failure even if the plan was correct, because the
  hand-off claim is about first use.

Never write the report before the sessions exist. `tests/walkthrough.py` refuses to claim the target
until five sessions are recorded, and reports `INCOMPLETE` instead.
