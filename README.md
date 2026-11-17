# Binary Companion shared configuration

Organization defaults and reusable workflows for Binary Companion repositories. Public: never put secrets or internal infrastructure detail here.

How work is tracked (issues, the TimeTug and Libraries projects, manual tasks): see the `tracking-work-in-issues` skill in [binary-companion/timetug](https://github.com/binary-companion/timetug/blob/master/.agents/skills/tracking-work-in-issues/SKILL.md). The sweeper (`.github/workflows/sweep.yml`) tracks every repository that has a `.github/tracking.yml`; a repository adds the `pr-check` workflow from `docs/pr-check-caller.yml` and the `track` workflow from `docs/track-caller.yml`, which updates the board and parent issues the moment an issue is opened, closed or reopened (the sweeper reconciles whatever events miss).
