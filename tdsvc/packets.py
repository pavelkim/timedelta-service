#!/usr/bin/env python3
# pylint: disable=line-too-long, missing-function-docstring, logging-fstring-interpolation
# pylint: disable=import-error
"""

    TimeDelta Service (tdsvc) - Packet dataclasses

"""

import json
import socket
import time
import uuid
from dataclasses import dataclass, field, asdict

from decouple import config

HOST_ID: str = config("HOST_ID", default=socket.gethostname(), cast=str)  # type: ignore[assignment]


@dataclass
class SyncStats:
    """Running statistics for time synchronisation with a neighbour."""
    sync_count: int = 0
    last_sync: float = 0.0
    last_clock_delta: float = 0.0
    last_rtt: float = 0.0
    min_clock_delta: float = 0.0
    max_clock_delta: float = 0.0
    mean_clock_delta: float = 0.0
    min_rtt: float = 0.0
    max_rtt: float = 0.0
    mean_rtt: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SyncStats":
        return cls(
            sync_count=data.get("sync_count", 0),
            last_sync=data.get("last_sync", 0.0),
            last_clock_delta=data.get("last_clock_delta", 0.0),
            last_rtt=data.get("last_rtt", 0.0),
            min_clock_delta=data.get("min_clock_delta", 0.0),
            max_clock_delta=data.get("max_clock_delta", 0.0),
            mean_clock_delta=data.get("mean_clock_delta", 0.0),
            min_rtt=data.get("min_rtt", 0.0),
            max_rtt=data.get("max_rtt", 0.0),
            mean_rtt=data.get("mean_rtt", 0.0),
        )


@dataclass
class Neighbour:
    """
    Represents a known neighbour (peer service instance).

    :param host_id: str: Configured host identifier of the neighbour.
    :param source: str: Source name of the neighbour.
    :param version: str: Application version reported by the neighbour.
    :param age: float: Timestamp of the last discovery message received.
    :param time: str: Human-readable time from the last discovery message.
    :param timestamp: float: Epoch timestamp from the last discovery message.
    :param dead: bool: Whether the neighbour is considered unreachable.
    :param sync_stats: SyncStats: Running time-sync statistics.
    """
    host_id: str = ""
    source: str = ""
    version: str = ""
    age: float = field(default_factory=time.time)
    time: str = ""
    timestamp: float = 0.0
    dead: bool = False
    sync_stats: SyncStats = field(default_factory=SyncStats)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Neighbour":
        sync_stats_data = data.get("sync_stats")
        return cls(
            host_id=data.get("host_id", ""),
            source=data.get("source", ""),
            version=data.get("version", ""),
            age=data.get("age", 0.0),
            time=data.get("time", ""),
            timestamp=data.get("timestamp", 0.0),
            dead=data.get("dead", False),
            sync_stats=SyncStats.from_dict(sync_stats_data) if isinstance(sync_stats_data, dict) else SyncStats(),
        )


@dataclass
class BasePacket:
    """
        Base packet for RabbitMQ exchange communication.

        :param type: str: Type of the packet (e.g., "keepalive", "data", etc.)
        :param source: str: Source identifier (e.g., hostname)
        :param host_id: str: Configured host identifier for this service instance.
        :param id: str: Unique identifier for the packet (default: UUID)
    """

    type: str = "base"
    source: str = field(default_factory=lambda: BasePacket.get_source_name())
    host_id: str = field(default_factory=lambda: BasePacket.get_source_name())
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @staticmethod
    def get_source_name() -> str:
        return HOST_ID

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type", "base"),
            source=data.get("source", cls.get_source_name()),
            host_id=data.get("host_id", cls.get_source_name()),
            id=data.get("id", str(uuid.uuid4())),
        )

    @classmethod
    def from_json(cls, json_str: str):
        return cls.from_dict(json.loads(json_str))

    @staticmethod
    def decode_packet(json_str: str) -> "BasePacket":
        """Decode a JSON string into the appropriate packet subclass based on the 'type' field."""
        data = json.loads(json_str)
        packet_type = data.get("type", "base")

        packet_type_map = {
            "keepalive": KeepalivePacket,
            "what_time_is_it": WhatTimeIsItPacket,
            "my_time": MyTimePacket,
            "neighbor_discovery": NeighborDiscoveryPacket,
        }

        packet_cls = packet_type_map.get(packet_type, BasePacket)
        return packet_cls.from_dict(data)


@dataclass
class KeepalivePacket(BasePacket):
    """Keepalive packet with a timestamp for clock comparison."""
    type: str = "keepalive"
    timestamp: float = field(default_factory=time.time)
    time: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()))
    version: str = config("APP_VERSION", default="0.0.0", cast=str)  # type: ignore[assignment]

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type", "keepalive"),
            source=data.get("source", cls.get_source_name()),
            host_id=data.get("host_id", cls.get_source_name()),
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", time.time()),
            time=data.get("time", time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())),
            version=data.get("version", config("APP_VERSION", default="0.0.0", cast=str)),
        )


@dataclass
class NeighborDiscoveryPacket(BasePacket):
    """Neighbor discovery packet carrying the sender's known neighbours."""
    type: str = "neighbor_discovery"
    timestamp: float = field(default_factory=time.time)
    time: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()))
    version: str = config("APP_VERSION", default="0.0.0", cast=str)  # type: ignore[assignment]
    neighbours: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type", "neighbor_discovery"),
            source=data.get("source", cls.get_source_name()),
            host_id=data.get("host_id", cls.get_source_name()),
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", time.time()),
            time=data.get("time", time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())),
            version=data.get("version", config("APP_VERSION", default="0.0.0", cast=str)),
            neighbours=data.get("neighbours", []),
        )


@dataclass
class WhatTimeIsItPacket(BasePacket):
    """
    Broadcast packet asking all peers for their current time.

    :param timestamp: float: The sender's local timestamp at the moment of sending.
    :param time: str: Human-readable local time string.
    """
    type: str = "what_time_is_it"
    timestamp: float = field(default_factory=time.time)
    time: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()))

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type", "what_time_is_it"),
            source=data.get("source", cls.get_source_name()),
            host_id=data.get("host_id", cls.get_source_name()),
            id=data.get("id", str(uuid.uuid4())),
            timestamp=data.get("timestamp", time.time()),
            time=data.get("time", time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())),
        )


@dataclass
class MyTimePacket(BasePacket):
    """
    Response to a WhatTimeIsItPacket with the responder's own current time.

    :param request_id: str: The ID of the original WhatTimeIsItPacket being responded to.
    :param request_timestamp: float: The timestamp from the original WhatTimeIsItPacket.
    :param received_at: float: The responder's local timestamp when it received the request.
    :param timestamp: float: The responder's local timestamp when it created this response.
    :param time: str: Human-readable local time string.
    """
    type: str = "my_time"
    request_id: str = ""
    request_timestamp: float = 0.0
    received_at: float = 0.0
    timestamp: float = field(default_factory=time.time)
    time: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()))

    @classmethod
    def from_dict(cls, data: dict):
        return cls(
            type=data.get("type", "my_time"),
            source=data.get("source", cls.get_source_name()),
            host_id=data.get("host_id", cls.get_source_name()),
            id=data.get("id", str(uuid.uuid4())),
            request_id=data.get("request_id", ""),
            request_timestamp=data.get("request_timestamp", 0.0),
            received_at=data.get("received_at", 0.0),
            timestamp=data.get("timestamp", time.time()),
            time=data.get("time", time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())),
        )


@dataclass
class TimeDeltaResult:
    """
    Result of a time delta calculation between this service and a remote peer.

    :param request_id: str: The ID of the original WhatTimeIsItPacket.
    :param remote_source: str: Hostname/identifier of the responding peer.
    :param clock_delta: float: Estimated clock offset (remote - local), in seconds.
    :param rtt: float: Round-trip time in seconds.
    :param local_send_ts: float: Local timestamp when the request was sent.
    :param remote_receive_ts: float: Remote timestamp when the request was received.
    :param remote_send_ts: float: Remote timestamp when the response was created.
    :param local_receive_ts: float: Local timestamp when the response was received.
    """
    request_id: str = ""
    remote_source: str = ""
    clock_delta: float = 0.0
    rtt: float = 0.0
    local_send_ts: float = 0.0
    remote_receive_ts: float = 0.0
    remote_send_ts: float = 0.0
    local_receive_ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)
