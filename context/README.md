# context/

Who the owner is, so every session starts already knowing you. The assistant reads this folder before acting on your behalf. Each file ships as a fill-in template with a clearly-fake example; `scripts/setup.py` walks you through the first pass.

- `about-me.md`: who you are, how you work, what to optimize for.
- `about-business.md`: what you're building or doing for work; delete or rename if "business" isn't your frame.
- `about-team.md`: the people around you, one row each. The wiki's name resolution reads this.
- `priorities.md`: this quarter's focus, a live heading refreshed with you. The one file the root map points at by name.
- `goals.md`: the frozen quarterly yardstick. Write it once per quarter, grade against it, don't edit mid-quarter.

Lifecycle: `priorities.md` and the about-files are live, edited as reality changes; `goals.md` is frozen per quarter. History belongs in `records/`, not here; this folder is always the current picture.
