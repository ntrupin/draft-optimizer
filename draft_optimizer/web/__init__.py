from __future__ import annotations

from flask import Blueprint


def create_blueprint(name: str = "baseball_draft") -> Blueprint:
    from .blueprint import create_blueprint as _create_blueprint

    return _create_blueprint(name=name)


__all__ = ["create_blueprint"]
