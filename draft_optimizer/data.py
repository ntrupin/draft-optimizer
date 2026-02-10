from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Dict, List, Sequence

from .models import Player, normalize_positions

try:
    import numpy as np
except Exception:
    np = None

HITTER_CORE_POSITIONS = ("C", "1B", "2B", "3B", "SS", "OF")
HITTER_POSITION_WEIGHTS = (0.1, 0.12, 0.12, 0.12, 0.12, 0.42)

HITTER_MEAN_POINTS = {
    "C": 330.0,
    "1B": 395.0,
    "2B": 375.0,
    "3B": 385.0,
    "SS": 390.0,
    "OF": 390.0,
}
PITCHER_MEAN_POINTS = {
    "SP": 420.0,
    "RP": 290.0,
}


def _random_name(prefix: str, index: int) -> str:
    return f"{prefix}_{index:03d}"


def _draw_normal(mean: float, stddev: float, rng: random.Random) -> float:
    if np is not None:
        return float(np.random.normal(mean, stddev))
    return rng.normalvariate(mean, stddev)


def generate_fake_players(
    num_hitters: int = 260,
    num_sp: int = 110,
    num_rp: int = 80,
    seed: int = 7,
) -> Dict[str, Player]:
    rng = random.Random(seed)
    if np is not None:
        np.random.seed(seed)

    players: Dict[str, Player] = {}
    next_id = 1

    for idx in range(1, num_hitters + 1):
        primary = rng.choices(HITTER_CORE_POSITIONS, weights=HITTER_POSITION_WEIGHTS, k=1)[0]
        positions: List[str] = [primary]
        if rng.random() < 0.32:
            secondary_candidates = [position for position in HITTER_CORE_POSITIONS if position != primary]
            positions.append(rng.choice(secondary_candidates))
        mean = HITTER_MEAN_POINTS[primary]
        projection = max(120.0, _draw_normal(mean, 55.0, rng))
        player_id = f"P{next_id:04d}"
        players[player_id] = Player(
            player_id=player_id,
            name=_random_name("H", idx),
            projected_points=round(projection, 1),
            positions=normalize_positions(positions),
        )
        next_id += 1

    for idx in range(1, num_sp + 1):
        positions = ["SP"]
        if rng.random() < 0.08:
            positions.append("RP")
        mean = PITCHER_MEAN_POINTS["SP"]
        projection = max(150.0, _draw_normal(mean, 65.0, rng))
        player_id = f"P{next_id:04d}"
        players[player_id] = Player(
            player_id=player_id,
            name=_random_name("SP", idx),
            projected_points=round(projection, 1),
            positions=normalize_positions(positions),
        )
        next_id += 1

    for idx in range(1, num_rp + 1):
        positions = ["RP"]
        if rng.random() < 0.05:
            positions.append("SP")
        mean = PITCHER_MEAN_POINTS["RP"]
        projection = max(90.0, _draw_normal(mean, 50.0, rng))
        player_id = f"P{next_id:04d}"
        players[player_id] = Player(
            player_id=player_id,
            name=_random_name("RP", idx),
            projected_points=round(projection, 1),
            positions=normalize_positions(positions),
        )
        next_id += 1

    return players


def _parse_positions(raw_positions: str) -> Sequence[str]:
    separators = ["/", ",", "|", ";"]
    normalized = raw_positions
    for separator in separators[1:]:
        normalized = normalized.replace(separator, separators[0])
    return [token.strip() for token in normalized.split(separators[0]) if token.strip()]


def load_players_from_csv(path: str | Path) -> Dict[str, Player]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(path)

    players: Dict[str, Player] = {}
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"name", "projected_points", "positions"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(
                "CSV must contain columns: name, projected_points, positions. "
                "Optional column: player_id."
            )

        for idx, row in enumerate(reader, start=1):
            raw_id = (row.get("player_id") or "").strip()
            player_id = raw_id or f"P{idx:04d}"
            if player_id in players:
                player_id = f"{player_id}_{idx}"
            name = (row.get("name") or "").strip() or f"Player_{idx:03d}"
            points = float(row["projected_points"])
            positions = normalize_positions(_parse_positions(row["positions"]))
            players[player_id] = Player(
                player_id=player_id,
                name=name,
                projected_points=points,
                positions=positions,
            )

    return players
