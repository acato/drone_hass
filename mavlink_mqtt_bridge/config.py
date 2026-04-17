"""Bridge configuration — YAML file, Pydantic-validated."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class DroneConfig(BaseModel):
    id: str = Field(min_length=1, description="Stable drone identifier used in MQTT topics")
    mavlink_connection: str = Field(
        default="udp://:14540",
        description="MAVSDK connection URL. SITL default is udp://:14540 for MAVSDK.",
    )
    system_id: int = Field(default=1, ge=1, le=255)
    component_id: int = Field(default=190, ge=1, le=255)

    @field_validator("id")
    @classmethod
    def _no_slashes(cls, v: str) -> str:
        if "/" in v or "#" in v or "+" in v:
            raise ValueError("drone.id must not contain MQTT wildcard or separator chars")
        return v


class MqttConfig(BaseModel):
    host: str = "localhost"
    port: int = Field(default=1883, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    tls: bool = False
    base_topic_prefix: str = Field(
        default="drone_hass",
        description="Topics will be published under {prefix}/{drone.id}/...",
    )
    client_id: str = "mavlink_mqtt_bridge"
    keepalive: int = Field(default=30, ge=5, le=300)


class ComplianceConfig(BaseModel):
    mode: Literal["part107", "part108"] = "part107"
    operational_area_geojson: Path | None = None
    database_path: Path = Path("./data/compliance.db")


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    format: Literal["json", "console"] = "console"


class BridgeConfig(BaseModel):
    drone: DroneConfig
    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    compliance: ComplianceConfig = Field(default_factory=ComplianceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @property
    def base_topic(self) -> str:
        return f"{self.mqtt.base_topic_prefix}/{self.drone.id}"


def load(path: Path) -> BridgeConfig:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return BridgeConfig.model_validate(raw)
