from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Literal, Tuple

HITTER_POSITIONS = {"C", "1B", "2B", "3B", "SS", "OF", "DH"}
PITCHER_POSITIONS = {"SP", "RP"}
POSITION_ALIASES = {
    "LF": "OF",
    "CF": "OF",
    "RF": "OF",
    "UTIL": "DH",
    "UT": "DH",
}


def normalize_position(position: str) -> str:
    normalized = position.strip().upper()
    return POSITION_ALIASES.get(normalized, normalized)


def normalize_positions(positions: Iterable[str]) -> Tuple[str, ...]:
    cleaned: List[str] = []
    for position in positions:
        if not position:
            continue
        normalized = normalize_position(position)
        if normalized not in cleaned:
            cleaned.append(normalized)
    return tuple(cleaned)


@dataclass(frozen=True, slots=True)
class Player:
    player_id: str
    name: str
    projected_points: float
    positions: Tuple[str, ...]

    @property
    def is_pitcher(self) -> bool:
        return any(position in PITCHER_POSITIONS for position in self.positions)

    @property
    def is_hitter(self) -> bool:
        return any(position in HITTER_POSITIONS for position in self.positions)

    def can_fill(self, slot: str) -> bool:
        if slot in self.positions:
            return True
        if slot == "DH":
            return self.is_hitter
        return False


@dataclass(slots=True)
class RosterConfig:
    active_slots: Dict[str, int]
    reserve_slots: int

    @property
    def total_active_slots(self) -> int:
        return sum(self.active_slots.values())

    @property
    def total_roster_size(self) -> int:
        return self.total_active_slots + self.reserve_slots

    @property
    def expanded_active_slots(self) -> List[str]:
        slots: List[str] = []
        for slot, count in self.active_slots.items():
            slots.extend([slot] * count)
        return slots


def default_roster_config() -> RosterConfig:
    return RosterConfig(
        active_slots={
            "C": 1,
            "1B": 1,
            "2B": 1,
            "3B": 1,
            "SS": 1,
            "OF": 3,
            "DH": 2,
            "SP": 5,
            "RP": 2,
        },
        reserve_slots=7,
    )


@dataclass(frozen=True, slots=True)
class DraftEvent:
    side: Literal["my", "other"]
    player_id: str | None
    label: str
    from_pool: bool


@dataclass(slots=True)
class DraftState:
    players: Dict[str, Player]
    roster_config: RosterConfig
    league_size: int
    draft_slot: int
    current_pick_number: int = 0
    my_picks: List[str] = field(default_factory=list)
    other_picks: List[str] = field(default_factory=list)
    history: List[DraftEvent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 1 <= self.draft_slot <= self.league_size:
            raise ValueError("draft_slot must be between 1 and league_size.")

    @property
    def drafted_ids(self) -> set[str]:
        return set(self.my_picks) | set(self.other_picks)

    @property
    def available_ids(self) -> set[str]:
        return set(self.players.keys()) - self.drafted_ids

    @property
    def my_picks_remaining(self) -> int:
        return self.roster_config.total_roster_size - len(self.my_picks)

    def _validate_available(self, player_id: str) -> None:
        if player_id not in self.players:
            raise KeyError(f"Unknown player_id: {player_id}")
        if player_id in self.drafted_ids:
            raise ValueError(f"Player already drafted: {player_id}")

    def record_my_pick(self, player_id: str) -> None:
        self._validate_available(player_id)
        self.my_picks.append(player_id)
        self.current_pick_number += 1
        player = self.players[player_id]
        self.history.append(
            DraftEvent(
                side="my",
                player_id=player_id,
                label=f"{player.player_id} {player.name}",
                from_pool=True,
            )
        )

    def record_other_pick(self, player_id: str) -> None:
        self._validate_available(player_id)
        self.other_picks.append(player_id)
        self.current_pick_number += 1
        player = self.players[player_id]
        self.history.append(
            DraftEvent(
                side="other",
                player_id=player_id,
                label=f"{player.player_id} {player.name}",
                from_pool=True,
            )
        )

    def record_other_external_pick(self, label: str) -> None:
        cleaned = label.strip() or "Unknown player"
        self.current_pick_number += 1
        self.history.append(
            DraftEvent(
                side="other",
                player_id=None,
                label=cleaned,
                from_pool=False,
            )
        )

    def undo_last_pick(self) -> DraftEvent | None:
        if not self.history:
            return None
        event = self.history.pop()
        if event.from_pool and event.player_id is not None:
            if event.side == "my":
                self.my_picks.remove(event.player_id)
            else:
                self.other_picks.remove(event.player_id)
        self.current_pick_number -= 1
        return event

    def my_pick_numbers(self) -> List[int]:
        picks: List[int] = []
        rounds = self.roster_config.total_roster_size
        for round_number in range(1, rounds + 1):
            round_start = (round_number - 1) * self.league_size + 1
            if round_number % 2 == 1:
                pick = round_start + self.draft_slot - 1
            else:
                pick = round_start + (self.league_size - self.draft_slot)
            picks.append(pick)
        return picks

    def team_for_pick_number(self, pick_number: int) -> int:
        if pick_number < 1:
            raise ValueError("pick_number must be >= 1")
        round_number = ((pick_number - 1) // self.league_size) + 1
        pick_in_round = ((pick_number - 1) % self.league_size) + 1
        if round_number % 2 == 1:
            return pick_in_round
        return self.league_size - pick_in_round + 1

    def is_my_turn(self) -> bool:
        return (self.current_pick_number + 1) in set(self.my_pick_numbers())

    def picks_until_my_next_pick(self) -> int:
        current = self.current_pick_number
        for pick_number in self.my_pick_numbers():
            if pick_number > current:
                return pick_number - current - 1
        return 0

    def picks_until_my_pick_after_current(self) -> int:
        current = self.current_pick_number
        upcoming = [pick for pick in self.my_pick_numbers() if pick > current]
        if not upcoming:
            return 0
        if upcoming[0] == current + 1:
            if len(upcoming) == 1:
                return 0
            return upcoming[1] - upcoming[0] - 1
        return upcoming[0] - current - 1

    def my_position_counts(self) -> Counter[str]:
        counts: Counter[str] = Counter()
        for player_id in self.my_picks:
            for position in self.players[player_id].positions:
                counts[position] += 1
        return counts
