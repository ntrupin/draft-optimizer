from __future__ import annotations

import csv
import io
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
CSV_COLUMN_ALIASES = {
    "player_id": ("playerid", "player_id", "id"),
    "name": ("name", "player", "playername", "player_name"),
    "projected_points": (
        "projectedpoints",
        "projected_points",
        "projection",
        "projected",
        "proj",
        "points",
        "fantasypoints",
        "fantasy_points",
    ),
    "positions": (
        "positions",
        "position",
        "postion",
        "eligiblepositions",
        "eligible_positions",
        "pos",
    ),
}

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


def _normalize_fieldname(fieldname: str) -> str:
    return "".join(char for char in fieldname.strip().lower() if char.isalnum())


def _resolve_csv_columns(fieldnames: Sequence[str] | None) -> Dict[str, str]:
    available = {
        _normalize_fieldname(fieldname): fieldname for fieldname in (fieldnames or []) if fieldname
    }
    columns: Dict[str, str] = {}
    for canonical_name, aliases in CSV_COLUMN_ALIASES.items():
        for alias in aliases:
            source_name = available.get(alias)
            if source_name is not None:
                columns[canonical_name] = source_name
                break

    required = {"name", "projected_points", "positions"}
    if not required.issubset(columns):
        raise ValueError(
            "CSV must contain columns equivalent to name, projected_points, and positions. "
            "Optional column: player_id."
        )

    return columns


def _merge_player_key(raw_player_id: str, name: str, raw_points: str) -> tuple[str, str, str]:
    if raw_player_id:
        return ("player_id", raw_player_id, "")
    return ("name_projection", name.strip().casefold(), raw_points.strip())


def _next_generated_player_id(reserved_ids: set[str], sequence_number: int) -> tuple[str, int]:
    next_sequence_number = sequence_number
    while True:
        candidate = f"P{next_sequence_number:04d}"
        next_sequence_number += 1
        if candidate not in reserved_ids:
            return candidate, next_sequence_number


def _same_player_name(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def _load_players_from_reader(reader: csv.DictReader) -> Dict[str, Player]:
    merged_rows: Dict[tuple[str, str, str], Dict[str, object]] = {}
    merge_order: List[tuple[str, str, str]] = []
    columns = _resolve_csv_columns(reader.fieldnames)

    for idx, row in enumerate(reader, start=1):
        raw_id = (row.get(columns.get("player_id", "")) or "").strip()
        name = (row.get(columns["name"]) or "").strip() or f"Player_{idx:03d}"
        raw_points = (row.get(columns["projected_points"]) or "").strip()
        points = float(raw_points)
        positions = normalize_positions(_parse_positions(row.get(columns["positions"], "")))

        merge_key = _merge_player_key(raw_id, name, raw_points)
        existing = merged_rows.get(merge_key)
        if existing is None:
            merged_rows[merge_key] = {
                "raw_id": raw_id,
                "name": name,
                "projected_points": points,
                "positions": list(positions),
            }
            merge_order.append(merge_key)
            continue

        if raw_id and not _same_player_name(str(existing["name"]), name):
            raise ValueError(f"Conflicting names for player_id {raw_id}: {existing['name']} vs {name}")
        if abs(float(existing["projected_points"]) - points) > 1e-9:
            raise ValueError(
                f"Conflicting projected_points for {name}: "
                f"{existing['projected_points']} vs {points}"
            )
        existing_positions = list(existing["positions"])
        existing["positions"] = list(normalize_positions(existing_positions + list(positions)))

    reserved_ids = {
        entry["raw_id"] for entry in merged_rows.values() if isinstance(entry.get("raw_id"), str) and entry["raw_id"]
    }
    players: Dict[str, Player] = {}
    next_generated_id = 1
    for merge_key in merge_order:
        entry = merged_rows[merge_key]
        raw_id = str(entry["raw_id"])
        if raw_id:
            player_id = raw_id
        else:
            player_id, next_generated_id = _next_generated_player_id(reserved_ids, next_generated_id)
            reserved_ids.add(player_id)

        players[player_id] = Player(
            player_id=player_id,
            name=str(entry["name"]),
            projected_points=float(entry["projected_points"]),
            positions=normalize_positions(entry["positions"]),
        )

    return players


def load_players_from_csv(path: str | Path) -> Dict[str, Player]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(path)

    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return _load_players_from_reader(reader)


def load_players_from_csv_text(csv_text: str) -> Dict[str, Player]:
    handle = io.StringIO(csv_text.lstrip("\ufeff"))
    reader = csv.DictReader(handle)
    return _load_players_from_reader(reader)
