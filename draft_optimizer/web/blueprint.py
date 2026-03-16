from __future__ import annotations

from typing import Any, Callable

from flask import Blueprint, jsonify, render_template, request

from . import service


def create_blueprint(name: str = "baseball_draft") -> Blueprint:
    blueprint = Blueprint(
        name,
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    def json_error(message: str, status_code: int = 400) -> tuple[Any, int]:
        return jsonify({"error": message}), status_code

    def handle_value_errors(fn: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except (KeyError, TypeError, ValueError) as exc:
                return json_error(str(exc), 400)

        wrapped.__name__ = fn.__name__
        return wrapped

    @blueprint.get("/")
    def index() -> str:
        return render_template(
            "baseball_draft/index.html",
            default_settings=service.default_settings(),
        )

    @blueprint.post("/api/upload")
    @handle_value_errors
    def api_upload() -> tuple[Any, int] | Any:
        upload = request.files.get("csv_file")
        if upload is None or not upload.filename:
            return json_error("Choose a CSV file to upload.", 400)

        csv_text = upload.read().decode("utf-8-sig")
        players = service.players_from_csv_text(csv_text)
        return jsonify(
            {
                "message": f"Loaded {len(players)} players from {upload.filename}.",
                "players": service.serialize_players(players),
            }
        )

    @blueprint.post("/api/snapshot")
    @handle_value_errors
    def api_snapshot() -> Any:
        payload = request.get_json(silent=True) or {}
        snapshot = service.build_snapshot(
            raw_players=payload.get("players"),
            raw_settings=payload.get("settings"),
            raw_history=payload.get("history"),
        )
        return jsonify(snapshot)

    @blueprint.post("/api/action")
    @handle_value_errors
    def api_action() -> Any:
        payload = request.get_json(silent=True) or {}
        response = service.apply_action(
            raw_players=payload.get("players"),
            raw_settings=payload.get("settings"),
            raw_history=payload.get("history"),
            action=payload.get("action"),
        )
        return jsonify(response)

    return blueprint
