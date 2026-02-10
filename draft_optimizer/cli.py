from __future__ import annotations

import argparse
import shlex
from typing import Dict, List, Literal, Sequence

from .data import generate_fake_players, load_players_from_csv
from .models import DraftState, Player, default_roster_config
from .optimizer import DraftOptimizer


def _format_positions(positions: Sequence[str]) -> str:
    return "/".join(positions)


ResolveStatus = Literal["found", "ambiguous", "not_found"]


def _resolve_player(
    query: str,
    players: Dict[str, Player],
    available_ids: set[str],
) -> tuple[Player | None, ResolveStatus]:
    q = query.strip()
    if not q:
        return None, "not_found"

    if q in players and q in available_ids:
        return players[q], "found"

    lowered = q.lower()
    exact_name = [
        player
        for player_id, player in players.items()
        if player_id in available_ids and player.name.lower() == lowered
    ]
    if exact_name:
        return exact_name[0], "found"

    partials: List[Player] = []
    for player_id in available_ids:
        player = players[player_id]
        if lowered in player.name.lower() or lowered in player.player_id.lower():
            partials.append(player)
    partials.sort(key=lambda player: player.projected_points, reverse=True)
    if len(partials) == 1:
        return partials[0], "found"
    if partials:
        print("Ambiguous match. Top candidates:")
        for player in partials[:5]:
            print(
                f"  {player.player_id:>6}  {player.name:<16}  "
                f"{player.projected_points:>6.1f}  {_format_positions(player.positions)}"
            )
        return None, "ambiguous"
    return None, "not_found"


def _print_recommendations(optimizer: DraftOptimizer, top_n: int) -> None:
    recommendations = optimizer.recommend(top_n=top_n)
    if not recommendations:
        print("No feasible recommendations available.")
        return

    print(
        " ID      Name               Pts   Score   Slot  "
        "RepNext DropOff  Pos"
    )
    print("-" * 78)
    for rec in recommendations:
        print(
            f" {rec.player_id:>6}  {rec.name:<16}  {rec.projected_points:>5.1f}  "
            f"{rec.score:>6.1f}  {rec.suggested_slot:>4}  {rec.replacement_at_next_pick:>7.1f}  "
            f"{rec.scarcity_dropoff:>6.1f}  {_format_positions(rec.positions)}"
        )


def _print_state(state: DraftState, optimizer: DraftOptimizer) -> None:
    unmet = optimizer.active_need_summary()
    next_gap = state.picks_until_my_pick_after_current()
    print(
        f"Current overall pick: {state.current_pick_number} | "
        f"My picks: {len(state.my_picks)}/{state.roster_config.total_roster_size} | "
        f"Available players: {len(state.available_ids)}"
    )
    print(
        f"My turn now: {state.is_my_turn()} | "
        f"Opponent picks until my next turn after current pick: {next_gap}"
    )
    if unmet:
        needs = ", ".join([f"{slot}:{count}" for slot, count in unmet.items() if count > 0])
        print(f"Unfilled active slots: {needs}")
    else:
        print("Active lineup can be filled with currently drafted players.")


def _auto_remove_best_available(state: DraftState, count: int) -> None:
    for _ in range(count):
        if not state.available_ids:
            return
        player_id = max(
            state.available_ids,
            key=lambda pid: state.players[pid].projected_points,
        )
        state.record_other_pick(player_id)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Live fantasy baseball draft optimizer")
    parser.add_argument("--csv", type=str, default=None, help="CSV with player projections")
    parser.add_argument("--teams", type=int, default=12, help="Number of teams in draft")
    parser.add_argument("--draft-slot", type=int, default=1, help="Your draft slot (1-indexed)")
    parser.add_argument("--top-n", type=int, default=12, help="Top recommendations to display")
    parser.add_argument("--seed", type=int, default=7, help="Seed for fake data generation")
    parser.add_argument("--num-hitters", type=int, default=260)
    parser.add_argument("--num-sp", type=int, default=110)
    parser.add_argument("--num-rp", type=int, default=80)
    parser.add_argument(
        "--disable-mc",
        action="store_true",
        help="Disable Monte Carlo opponent simulation for replacement estimates",
    )
    parser.add_argument(
        "--mc-trials",
        type=int,
        default=220,
        help="Monte Carlo trials per recommendation refresh",
    )
    parser.add_argument(
        "--mc-seed",
        type=int,
        default=17,
        help="Seed for Monte Carlo opponent simulation",
    )
    parser.add_argument(
        "--mc-candidate-pool",
        type=int,
        default=75,
        help="Top-N candidates opponents evaluate per simulated pick",
    )
    parser.add_argument(
        "--mc-temperature",
        type=float,
        default=16.0,
        help="Opponent pick softmax temperature (lower = greedier)",
    )
    parser.add_argument(
        "--opponent-need-bonus",
        type=float,
        default=22.0,
        help="Extra points opponents assign to needed active slots",
    )
    parser.add_argument(
        "--opponent-scarcity-weight",
        type=float,
        default=0.22,
        help="How much opponents react to positional dropoff",
    )
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    if args.csv:
        players = load_players_from_csv(args.csv)
    else:
        players = generate_fake_players(
            num_hitters=args.num_hitters,
            num_sp=args.num_sp,
            num_rp=args.num_rp,
            seed=args.seed,
        )

    roster = default_roster_config()
    state = DraftState(
        players=players,
        roster_config=roster,
        league_size=args.teams,
        draft_slot=args.draft_slot,
    )
    optimizer = DraftOptimizer(
        state,
        use_monte_carlo_replacement=not args.disable_mc,
        monte_carlo_trials=args.mc_trials,
        monte_carlo_seed=args.mc_seed,
        opponent_candidate_pool=args.mc_candidate_pool,
        opponent_temperature=args.mc_temperature,
        opponent_need_bonus=args.opponent_need_bonus,
        opponent_scarcity_weight=args.opponent_scarcity_weight,
    )

    print(
        f"Loaded {len(players)} players. Roster size={roster.total_roster_size} "
        f"(active={roster.total_active_slots}, reserve={roster.reserve_slots})."
    )
    if args.disable_mc:
        print("Replacement model: deterministic (Monte Carlo disabled)")
    else:
        print(
            "Replacement model: Monte Carlo "
            f"(trials={args.mc_trials}, temp={args.mc_temperature}, pool={args.mc_candidate_pool})"
        )
    print("Commands: recommend|r [n], mine|m <id|name>, other|o <id|name>,")
    print("          run <n>, state, undo [n], find <text>, help, quit")
    _print_state(state, optimizer)
    _print_recommendations(optimizer, args.top_n)

    while True:
        try:
            raw = input("\ndraft> ").strip()
        except EOFError:
            print()
            break
        if not raw:
            _print_recommendations(optimizer, args.top_n)
            continue

        parts = shlex.split(raw)
        command = parts[0].lower()

        if command in {"quit", "exit", "q"}:
            break

        if command in {"help", "h", "?"}:
            print("recommend|r [n]     Show top recommendations")
            print("mine|m <query>      Record your pick")
            print("other|o <query>     Record another team's pick (off-list allowed)")
            print("run <n>             Auto-remove n best available as other picks")
            print("state               Show draft status")
            print("undo [n]            Undo last n recorded picks (default: 1)")
            print("find <text>         Search available players")
            print("quit                Exit")
            continue

        if command in {"state", "s"}:
            _print_state(state, optimizer)
            continue

        if command in {"recommend", "r"}:
            n = args.top_n
            if len(parts) > 1:
                n = int(parts[1])
            _print_recommendations(optimizer, n)
            continue

        if command == "undo":
            undo_count = 1
            if len(parts) > 1:
                undo_count = int(parts[1])
            if undo_count <= 0:
                print("Usage: undo [n], where n >= 1")
                continue

            undone_total = 0
            for _ in range(undo_count):
                undone = state.undo_last_pick()
                if undone is None:
                    break
                if undone.from_pool and undone.player_id is not None:
                    player = state.players[undone.player_id]
                    print(f"Undid {undone.side} pick: {player.player_id} {player.name}")
                else:
                    print(f"Undid {undone.side} external pick: {undone.label}")
                undone_total += 1

            if undone_total == 0:
                print("No picks to undo.")
            elif undone_total < undo_count:
                print(f"Undid {undone_total} pick(s); no more picks in history.")
            continue

        if command == "run":
            if len(parts) < 2:
                print("Usage: run <n>")
                continue
            count = int(parts[1])
            _auto_remove_best_available(state, count)
            print(f"Removed {count} best-available players as other picks.")
            _print_recommendations(optimizer, args.top_n)
            continue

        if command in {"mine", "m", "other", "o"}:
            if len(parts) < 2:
                print(f"Usage: {command} <id|name>")
                continue
            query = " ".join(parts[1:])
            player, status = _resolve_player(query, players=state.players, available_ids=state.available_ids)
            if command in {"mine", "m"}:
                if status != "found" or player is None:
                    print("No unique available player match found.")
                    continue
                if state.my_picks_remaining <= 0:
                    print("You have no remaining picks.")
                    continue
                state.record_my_pick(player.player_id)
                print(f"My pick: {player.player_id} {player.name} ({player.projected_points:.1f})")
            else:
                if status == "found" and player is not None:
                    state.record_other_pick(player.player_id)
                    print(f"Other pick: {player.player_id} {player.name} ({player.projected_points:.1f})")
                elif status == "ambiguous":
                    print("No unique available player match found.")
                    continue
                else:
                    state.record_other_external_pick(query)
                    print(f"Other pick (off-list): {query}")
            _print_recommendations(optimizer, args.top_n)
            continue

        if command == "find":
            if len(parts) < 2:
                print("Usage: find <text>")
                continue
            query = " ".join(parts[1:]).lower()
            matches = [
                state.players[player_id]
                for player_id in state.available_ids
                if query in state.players[player_id].name.lower()
                or query in player_id.lower()
            ]
            matches.sort(key=lambda player: player.projected_points, reverse=True)
            for player in matches[:15]:
                print(
                    f"{player.player_id:>6}  {player.name:<16}  "
                    f"{player.projected_points:>6.1f}  {_format_positions(player.positions)}"
                )
            if not matches:
                print("No matches.")
            continue

        print("Unknown command. Type 'help'.")


if __name__ == "__main__":
    main()
