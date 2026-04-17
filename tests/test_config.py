"""Config loader round-trip + validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from mavlink_mqtt_bridge import config


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "bridge.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_minimal_config_loads(tmp_path: Path) -> None:
    p = _write(tmp_path, {"drone": {"id": "sitl1"}})
    cfg = config.load(p)
    assert cfg.drone.id == "sitl1"
    assert cfg.mqtt.host == "localhost"
    assert cfg.base_topic == "drone_hass/sitl1"
    assert cfg.compliance.mode == "part107"


def test_base_topic_uses_prefix_and_id(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {
            "drone": {"id": "hangar_west"},
            "mqtt": {"base_topic_prefix": "uas"},
        },
    )
    cfg = config.load(p)
    assert cfg.base_topic == "uas/hangar_west"


def test_drone_id_rejects_mqtt_wildcards(tmp_path: Path) -> None:
    p = _write(tmp_path, {"drone": {"id": "bad/id"}})
    with pytest.raises(ValidationError):
        config.load(p)


def test_compliance_mode_rejects_unknown(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        {"drone": {"id": "sitl1"}, "compliance": {"mode": "part99"}},
    )
    with pytest.raises(ValidationError):
        config.load(p)
