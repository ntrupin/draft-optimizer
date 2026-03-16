from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ..data import load_players_from_csv_text
from ..models import DraftEvent, DraftState, Player, default_roster_config, normalize_positions
from ..optimizer import DraftOptimizer, Recommendation

DEFAULT_SETTINGS: Dict[str, Any] = {
    "teams": 12,
    "draft_slot": 1,
    "top_n": 10,
    "disable_mc": False,
    "mc_trials": 220,
    "mc_seed": 17,
    "mc_candidate_pool": 75,
    "mc_temperature": 16.0,
    "opponent_need_bonus": 22.0,
    "opponent_scarcity_weight": 0.22,
}


def default_settings() -> Dict[str, Any]:
    return dict(DEFAULT_SETTINGS)


def players_from_csv_text(csv_text: str) -> Dict[str, Player]:
    return load_players_from_csv_text(csv_text)


def serialize_player(player: Player) -> Dict[str, Any]:
    return {
        "player_id": player.player_id,
        "name": player.name,
        "projected_points": player.projected_points,
        "positions": list(player.positions),
    }


def serialize_players(players: Mapping[str, Player]) -> List[Dict[str, Any]]:
    return [serialize_player(player) for player in players.values()]


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def _coerce_int(value: Any, *, default: int, minimum: int | None = None) -> int:
    if value is None or value == "":
        result = default
    else:
        result = int(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"Value must be >= {minimum}")
    return result


def _coerce_float(value: Any, *, default: float, minimum: float | None = None) -> float:
    if value is None or value == "":
        result = default
    else:
        result = float(value)
    if minimum is not None and result < minimum:
        raise ValueError(f"Value must be >= {minimum}")
    return result


def normalize_settings(raw_settings: Mapping[str, Any] | None) -> Dict[str, Any]:
    raw = raw_settings or {}
    settings = {
        "teams": _coerce_int(raw.get("teams"), default=DEFAULT_SETTINGS["teams"], minimum=2),
        "draft_slot": _coerce_int(raw.get("draft_slot"), default=DEFAULT_SETTINGS["draft_slot"], minimum=1),
        "top_n": _coerce_int(raw.get("top_n"), default=DEFAULT_SETTINGS["top_n"], minimum=1),
        "disable_mc": _coerce_bool(raw.get("disable_mc"), default=DEFAULT_SETTINGS["disable_mc"]),
        "mc_trials": _coerce_int(raw.get("mc_trials"), default=DEFAULT_SETTINGS["mc_trials"], minimum=1),
        "mc_seed": _coerce_int(raw.get("mc_seed"), default=DEFAULT_SETTINGS["mc_seed"]),
        "mc_candidate_pool": _coerce_int(
            raw.get("mc_candidate_pool"),
            default=DEFAULT_SETTINGS["mc_candidate_pool"],
            minimum=8,
        ),
        "mc_temperature": _coerce_float(
            raw.get("mc_temperature"),
            default=DEFAULT_SETTINGS["mc_temperature"],
            minimum=0.0,
        ),
        "opponent_need_bonus": _coerce_float(
            raw.get("opponent_need_bonus"),
            default=DEFAULT_SETTINGS["opponent_need_bonus"],
            minimum=0.0,
        ),
        "opponent_scarcity_weight": _coerce_float(
            raw.get("opponent_scarcity_weight"),
            default=DEFAULT_SETTINGS["opponent_scarcity_weight"],
            minimum=0.0,
        ),
    }
    if settings["draft_slot"] > settings["teams"]:
        raise ValueError("draft_slot must be between 1 and teams")
    return settings


def deserialize_players(raw_players: Sequence[Mapping[str, Any]] | None) -> Dict[str, Player]:
    if not raw_players:
        raise ValueError("Upload a CSV before starting a draft.")

    players: Dict[str, Player] = {}
    for item in raw_players:
        player_id = str(item.get("player_id", "")).strip()
        name = str(item.get("name", "")).strip()
        if not player_id or not name:
            raise ValueError("Each player must include player_id and name.")
        if player_id in players:
            raise ValueError(f"Duplicate player_id in session payload: {player_id}")
        projected_points = float(item.get("projected_points"))
        positions = normalize_positions(
            str(position).strip() for position in item.get("positions", []) if str(position).strip()
        )
        if not positions:
            raise ValueError(f"Player {name} must include at least one position.")
        players[player_id] = Player(
            player_id=player_id,
            name=name,
            projected_points=projected_points,
            positions=positions,
        )
    return players


def serialize_event(event: DraftEvent) -> Dict[str, Any]:
    return {
        "side": event.side,
        "player_id": event.player_id,
        "label": event.label,
        "from_pool": event.from_pool,
    }


def serialize_history(history: Iterable[DraftEvent]) -> List[Dict[str, Any]]:
    return [serialize_event(event) for event in history]


def _normalize_history_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    side = str(item.get("side", "")).strip().lower()
    if side not in {"my", "other"}:
        raise ValueError("History side must be 'my' or 'other'.")

    from_pool = _coerce_bool(item.get("from_pool"), default=True)
    player_id = item.get("player_id")
    label = str(item.get("label", "")).strip()

    if from_pool:
        normalized_player_id = str(player_id or "").strip()
        if not normalized_player_id:
            raise ValueError("History entries from the player pool must include player_id.")
        return {
            "side": side,
            "from_pool": True,
            "player_id": normalized_player_id,
            "label": label,
        }

    if side != "other":
        raise ValueError("Only opponent picks may be recorded as off-list entries.")

    return {
        "side": side,
        "from_pool": False,
        "player_id": None,
        "label": label or "Unknown player",
    }


def _replay_history(
    state: DraftState,
    history_payload: Sequence[Mapping[str, Any]] | None,
) -> None:
    for raw_item in history_payload or []:
        item = _normalize_history_item(raw_item)
        if item["from_pool"]:
            if item["side"] == "my":
                state.record_my_pick(item["player_id"])
            else:
                state.record_other_pick(item["player_id"])
        else:
            state.record_other_external_pick(item["label"])


def _build_optimizer(state: DraftState, settings: Mapping[str, Any]) -> DraftOptimizer:
    return DraftOptimizer(
        state,
        use_monte_carlo_replacement=not bool(settings["disable_mc"]),
        monte_carlo_trials=int(settings["mc_trials"]),
        monte_carlo_seed=int(settings["mc_seed"]),
        opponent_candidate_pool=int(settings["mc_candidate_pool"]),
        opponent_temperature=float(settings["mc_temperature"]),
        opponent_need_bonus=float(settings["opponent_need_bonus"]),
        opponent_scarcity_weight=float(settings["opponent_scarcity_weight"]),
    )


def build_runtime(
    raw_players: Sequence[Mapping[str, Any]] | None,
    raw_settings: Mapping[str, Any] | None,
    raw_history: Sequence[Mapping[str, Any]] | None,
) -> tuple[DraftState, DraftOptimizer, Dict[str, Any]]:
    players = deserialize_players(raw_players)
    settings = normalize_settings(raw_settings)
    state = DraftState(
        players=players,
        roster_config=default_roster_config(),
        league_size=settings["teams"],
        draft_slot=settings["draft_slot"],
    )
    _replay_history(state, raw_history)
    optimizer = _build_optimizer(state, settings)
    return state, optimizer, settings


def _serialize_recommendation(rec: Recommendation) -> Dict[str, Any]:
    return {
        "player_id": rec.player_id,
        "name": rec.name,
        "positions": list(rec.positions),
        "projected_points": rec.projected_points,
        "score": rec.score,
        "suggested_slot": rec.suggested_slot,
        "replacement_at_next_pick": rec.replacement_at_next_pick,
        "scarcity_dropoff": rec.scarcity_dropoff,
        "feasible": rec.feasible,
        "rationale": rec.rationale,
    }


def _active_needs_dict(state: DraftState, optimizer: DraftOptimizer) -> Dict[str, int]:
    needs = optimizer.active_need_summary()
    ordered: Dict[str, int] = {}
    for slot in state.roster_config.active_slots:
        count = int(needs.get(slot, 0))
        if count > 0:
            ordered[slot] = count
    return ordered


def _snapshot_from_state(
    state: DraftState,
    optimizer: DraftOptimizer,
    settings: Mapping[str, Any],
) -> Dict[str, Any]:
    recommendations = optimizer.recommend(top_n=int(settings["top_n"]))
    return {
        "settings": dict(settings),
        "summary": {
            "current_pick_number": state.current_pick_number,
            "my_picks_count": len(state.my_picks),
            "other_picks_count": len(state.other_picks),
            "my_picks_remaining": state.my_picks_remaining,
            "available_count": len(state.available_ids),
            "my_turn": state.is_my_turn(),
            "picks_until_my_next_turn_after_current": state.picks_until_my_pick_after_current(),
            "total_roster_size": state.roster_config.total_roster_size,
            "total_active_slots": state.roster_config.total_active_slots,
            "reserve_slots": state.roster_config.reserve_slots,
            "active_needs": _active_needs_dict(state, optimizer),
            "my_pick_numbers": state.my_pick_numbers(),
        },
        "recommendations": [_serialize_recommendation(rec) for rec in recommendations],
        "my_picks": [serialize_player(state.players[player_id]) for player_id in state.my_picks],
        "history": serialize_history(state.history),
        "drafted_ids": list(state.drafted_ids),
    }


def build_snapshot(
    raw_players: Sequence[Mapping[str, Any]] | None,
    raw_settings: Mapping[str, Any] | None,
    raw_history: Sequence[Mapping[str, Any]] | None,
) -> Dict[str, Any]:
    state, optimizer, settings = build_runtime(raw_players, raw_settings, raw_history)
    return _snapshot_from_state(state, optimizer, settings)


def _auto_remove_best_available(state: DraftState, count: int) -> List[str]:
    removed_ids: List[str] = []
    for _ in range(count):
        if not state.available_ids:
            break
        player_id = max(
            state.available_ids,
            key=lambda candidate_id: state.players[candidate_id].projected_points,
        )
        state.record_other_pick(player_id)
        removed_ids.append(player_id)
    return removed_ids


def apply_action(
    raw_players: Sequence[Mapping[str, Any]] | None,
    raw_settings: Mapping[str, Any] | None,
    raw_history: Sequence[Mapping[str, Any]] | None,
    action: Mapping[str, Any] | None,
) -> Dict[str, Any]:
    state, optimizer, settings = build_runtime(raw_players, raw_settings, raw_history)
    payload = action or {}
    action_type = str(payload.get("type", "refresh")).strip().lower()

    result: Dict[str, Any]
    if action_type == "refresh":
        result = {"type": "refresh", "message": "Draft refreshed."}
    elif action_type == "mine":
        player_id = str(payload.get("player_id", "")).strip()
        if not player_id:
            raise ValueError("Mine action requires player_id.")
        state.record_my_pick(player_id)
        player = state.players[player_id]
        result = {"type": "mine", "message": f"My pick: {player.name}", "player_id": player_id}
    elif action_type == "other":
        player_id = str(payload.get("player_id", "")).strip()
        if not player_id:
            raise ValueError("Other action requires player_id.")
        state.record_other_pick(player_id)
        player = state.players[player_id]
        result = {"type": "other", "message": f"Other pick: {player.name}", "player_id": player_id}
    elif action_type == "other_external":
        label = str(payload.get("label", "")).strip()
        if not label:
            raise ValueError("Off-list opponent picks require a name.")
        state.record_other_external_pick(label)
        result = {"type": "other_external", "message": f"Other pick: {label}", "label": label}
    elif action_type == "undo":
        count = _coerce_int(payload.get("count"), default=1, minimum=1)
        undone: List[Dict[str, Any]] = []
        for _ in range(count):
            event = state.undo_last_pick()
            if event is None:
                break
            undone.append(serialize_event(event))
        result = {
            "type": "undo",
            "message": f"Undid {len(undone)} pick(s).",
            "undone": undone,
        }
    elif action_type == "run":
        count = _coerce_int(payload.get("count"), default=1, minimum=1)
        removed_ids = _auto_remove_best_available(state, count)
        result = {
            "type": "run",
            "message": f"Removed {len(removed_ids)} best-available player(s).",
            "player_ids": removed_ids,
        }
    else:
        raise ValueError(f"Unknown action type: {action_type}")

    snapshot = _snapshot_from_state(state, optimizer, settings)
    return {
        "result": result,
        "snapshot": snapshot,
    }
