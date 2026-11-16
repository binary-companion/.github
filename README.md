# Binary Companion shared configuration

Organization defaults and reusable workflows for Binary Companion repositories. Public: never put secrets or internal infrastructure detail here.

How work is tracked (issues, the TimeTug and Libraries projects, manual tasks): see the `tracking-work-in-issues` skill in [binary-companion/timetug](https://github.com/binary-companion/timetug/blob/master/.agents/skills/tracking-work-in-issues/SKILL.md). The tracking logic is a composite action in `.github/actions/tracking`; repositories call it from their own workflow (see `docs/caller-template.yml`).
