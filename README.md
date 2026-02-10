# Fantasy Baseball Draft Optimizer

Scarcity-aware live draft assistant for a 24-player roster format:

- 17 active: `C, 1B, 2B, 3B, SS, OF x3, DH x2, SP x5, RP x2`
- 7 reserve

At each draft decision point, it recommends players using:

- Projected season fantasy points
- Position-specific replacement value at your next pick (Monte Carlo opponent simulation)
- Position drop-off (scarcity) before your next turn
- A feasibility guardrail so remaining active slots can still be completed

## Quick Start

Use the project venv interpreter:

```bash
.venv/bin/python -m draft_optimizer.cli --teams 12 --draft-slot 7
```

With custom projection CSV:

```bash
.venv/bin/python -m draft_optimizer.cli --csv projections.csv --teams 12 --draft-slot 7
```

Use deterministic replacement (no opponent simulation):

```bash
.venv/bin/python -m draft_optimizer.cli --disable-mc
```

CSV columns:

- Required: `name`, `projected_points`, `positions`
- Optional: `player_id`
- `positions` can be delimited with `/`, `,`, `|`, or `;`

Example:

```csv
player_id,name,projected_points,positions
P0001,Ronald Acuna Jr,510,OF
P0002,Mookie Betts,488,2B/OF
P0003,Spencer Strider,460,SP
```

## CLI Commands

- `recommend` or `r [n]`: show top recommendations
- `mine <id|name>`: record your pick
- `other <id|name>`: record another team's pick (off-list names are allowed)
- `run <n>`: auto-remove `n` best available players as opponents' picks
- `state`: show draft status and remaining active-slot needs
- `undo [n]`: undo last `n` picks (default `1`)
- `find <text>`: search available players
- `quit`: exit

If an opponent drafts a player not in your loaded pool, enter their name with
`other <name>`. The draft pick order advances, but no player is removed from your
modeled pool.

## Notes

- `torch`, `numpy`, and `pandas` are optional.
- If `torch` is installed, sorting in the ranking pipeline uses tensors.
- Fake data generation works without external dependencies.
- Monte Carlo controls:
  - `--mc-trials` (default `220`)
  - `--mc-temperature` (default `16.0`; lower is greedier opponents)
  - `--mc-candidate-pool` (default `75`)
  - `--opponent-need-bonus` and `--opponent-scarcity-weight`
