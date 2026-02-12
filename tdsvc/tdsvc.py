#!/usr/bin/env python3
# pylint: disable=line-too-long, missing-function-docstring, logging-fstring-interpolation
# pylint: disable=too-many-locals, broad-except, too-many-arguments, raise-missing-from
# pylint: disable=import-error
"""

    TimeDelta Service (tdsvc) - Clock comparison

"""

import json
import logging
import queue
import random
import socket
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

import pyp8s
from decouple import config
from py_rmq_exchange import ExchangeThread

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


class TimeDeltaService:
    """TimeDelta Service (tdsvc) - Clock comparison"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.host_id = HOST_ID
        self.logger.info(f"Host ID: {self.host_id}")

        self.publisher = None
        self.publisher_queue = queue.Queue()

        self.keepalive_thread = None
        self.keepalive_interval = config("KEEPALIVE_INTERVAL", default=5, cast=int)

        self.time_query_thread = None
        self.time_query_interval = config("TIME_QUERY_INTERVAL", default=2, cast=int)
        
        self.neighbor_discovery_thread = None
        self.neighbor_discovery_interval = config("NEIGHBOR_DISCOVERY_INTERVAL", default=5, cast=int)
        self.neighbor_age_timeout = config("NEIGHBOR_AGE_TIMEOUT", default=10, cast=int)
        self.neighbours: dict[str, Neighbour] = {}
        self.neighbours_lock = threading.Lock()

        self.pending_requests: dict[str, float] = {}
        self.pending_requests_lock = threading.Lock()

        self.time_deltas: list[TimeDeltaResult] = []
        self.time_deltas_lock = threading.Lock()

        self.rmq_server_uri = config("RMQ_SERVER_URI", default="amqp://guest:guest@localhost:5672/")
        self.rmq_exchange = config("RMQ_EXCHANGE", default="tdsvc_exchange")
        self.rmq_dlx_exchange = config("RMQ_DLX_EXCHANGE", default="dlx_tdsvc_exchange")
        self.consumer_queue_name = config("RMQ_CONSUMER_QUEUE_NAME", default="tdsvc_consumer_local")

        self.logger.info("Setting up consumer")
        self.datasource_consumer_params = {
            "exchange": self.rmq_exchange,
            "exchange_type": "direct",
            "routing_keys": [
                "keepalive",
                "what_time_is_it",
                "my_time",
                "neighbor_discovery",
                "",
            ],
            "on_message_callback": self.consumer_callback,
            # "queue_name": self.consumer_queue_name,
            "auto_ack": False,
            "exclusive": True,
            "prefetch_count": config("RMQ_PREFETCH_COUNT", default=1, cast=int),
            "queue_declare_arguments": {
                "x-dead-letter-exchange": self.rmq_dlx_exchange,
            },
        }
        
        self.setup_consumer()

        self.logger.info("Setting up posts publisher")
        self.publisher_params = {
            "exchange": self.rmq_exchange,
            "exchange_type": "direct",
            "publish_queue": self.publisher_queue,
        }
        self.setup_publisher()
        # self.setup_keepalive_thread()
        self.setup_neighbor_discovery_thread()
        self.setup_time_query_thread()
        

    def setup_neighbor_discovery_thread(self):
        self.logger.info(f"Setting up the neighbor discovery thread")
        self.neighbor_discovery_thread = threading.Thread(target=self.neighbor_discovery_loop, daemon=True)
        self.neighbor_discovery_thread.start()

    def setup_time_query_thread(self):
        """Set up a background thread that periodically broadcasts 'what_time_is_it' packets."""
        self.logger.info(f"Setting up the time query thread (interval={self.time_query_interval}s)")
        self.time_query_thread = threading.Thread(target=self.time_query_loop, daemon=True)
        self.time_query_thread.start()

    def setup_keepalive_thread(self):
        self.logger.info(f"Setting up the keepalive thread")
        self.keepalive_thread = threading.Thread(target=self.keepalive_loop, daemon=True)
        self.keepalive_thread.start()
    
    def setup_publisher(self):
        self.logger.info(f"Setting up the publisher")

        if self.publisher is not None:
            self.logger.error(f"Publisher distruction not implemented yet")
            raise Exception(f"Publisher distruction not implemented yet")

        self.publisher = ExchangeThread(rmq_server_uri=self.rmq_server_uri)
        self.publisher.setup_publisher(**self.publisher_params)
        self.publisher.start()

        return self.publisher

    def setup_consumer(self):
        self.logger.info(f"Setting up the consumer")

        self.datasource_consumer = ExchangeThread(rmq_server_uri=self.rmq_server_uri)
        self.datasource_consumer.setup_consumer(**self.datasource_consumer_params)
        self.datasource_consumer.start()

        return self.datasource_consumer

    def consumer_callback(self, event):
        """Main consumer callback: decodes incoming messages and routes them by packet type."""
        self.logger.debug(f"Received event: {event}")

        channel = event['channel']
        method = event['method']
        delivery_tag = method.delivery_tag
        result = None

        try:
            body_str = event['body']
            packet = BasePacket.decode_packet(body_str)

            # Ignore packets originating from this service instance
            if packet.host_id == (HOST_ID or socket.gethostname()) or packet.source == socket.gethostname():
                self.logger.debug(f"Ignoring own packet {packet.type} id={packet.id} host_id={packet.host_id}")
                result = True

            elif isinstance(packet, NeighborDiscoveryPacket):
                self.handle_neighbor_discovery(packet)
                result = True

            elif isinstance(packet, WhatTimeIsItPacket):
                self.handle_what_time_is_it(packet)
                result = True

            elif isinstance(packet, MyTimePacket):
                self.handle_my_time(packet)
                result = True

            elif packet.type == "keepalive":
                self.logger.debug(f"Received keepalive from {packet.source}")
                result = True

            else:
                self.logger.warning(f"Unknown packet type: {packet.type}")
                result = True

        except Exception as e:
            self.logger.exception(f"ERROR while processing event: {e.__class__.__name__}: {e}")
            self.logger.error(f"ERROR raw event body: {event.get('body', '<missing>')}")
            result = False

        finally:
            if result:
                channel.basic_ack(delivery_tag)
            else:
                channel.basic_nack(delivery_tag)

    def neighbor_discovery_loop(self):
        """Periodically broadcasts 'neighbor_discovery' packets to find other instances."""
        self.logger.info(f"Starting neighbor discovery loop (interval={self.neighbor_discovery_interval}s)")
        while True:
            try:
                self.publish_neighbor_discovery()

                # Check neighbours' age and mark dead ones
                with self.neighbours_lock:
                    now = time.time()
                    neighbour_timeout = self.neighbor_age_timeout
                    for source, neighbour in self.neighbours.items():
                        age = now - neighbour.age
                        if age > neighbour_timeout:
                            if not neighbour.dead:
                                self.logger.warning(f"Neighbour {source} is dead (age={age:.1f}s, timeout={neighbour_timeout}s)")
                                neighbour.dead = True
                        else:
                            if neighbour.dead:
                                self.logger.info(f"Neighbour {source} is alive again (age={age:.1f}s)")
                                neighbour.dead = False

            except Exception as e:
                self.logger.exception(f"Error in neighbor discovery loop {e.__class__.__name__}: {e}")
            time.sleep(self.neighbor_discovery_interval)

    def publish_neighbor_discovery(self):
        """Broadcast a 'neighbor_discovery' packet including known neighbours."""
        with self.neighbours_lock:
            neighbours_data = [
                neighbour.to_dict()
                for neighbour in self.neighbours.values()
            ]
        packet = NeighborDiscoveryPacket(neighbours=neighbours_data)
        self.logger.debug(f"Broadcasting neighbor_discovery id={packet.id} with {len(neighbours_data)} known neighbours")
        self.publish_packet(packet)

    def handle_neighbor_discovery(self, packet: NeighborDiscoveryPacket):
        """Handle an incoming 'neighbor_discovery' packet by recording the sender as a neighbor
        and merging its known-neighbours list into our own."""

        self.logger.debug(f"neighbor_discovery from {packet.source} id={packet.id} time={packet.time}")

        with self.neighbours_lock:
            # Update or create the direct sender as a neighbour
            if packet.source not in self.neighbours:
                self.logger.info(f"Discovered new neighbor: {packet.source} (host_id={packet.host_id}, knows {len(packet.neighbours)} neighbours)")
                self.neighbours[packet.source] = Neighbour()

            sender = self.neighbours[packet.source]
            sender.host_id = packet.host_id
            sender.source = packet.source
            sender.age = time.time()
            sender.time = packet.time
            sender.timestamp = packet.timestamp
            sender.version = packet.version
            sender.dead = False

            # Merge neighbours reported by the sender
            for remote_neighbour_data in packet.neighbours:
                remote_neighbour = Neighbour.from_dict(remote_neighbour_data)
                remote_source = remote_neighbour.source

                # Skip ourselves and empty sources
                if not remote_source or remote_source == HOST_ID:
                    continue

                if remote_source not in self.neighbours:
                    self.logger.info(
                        f"Discovered indirect neighbor: {remote_source} "
                        f"(host_id={remote_neighbour.host_id}, via {packet.source})"
                    )
                    self.neighbours[remote_source] = Neighbour(
                        host_id=remote_neighbour.host_id,
                        source=remote_source,
                        version=remote_neighbour.version,
                        age=remote_neighbour.age,
                        time=remote_neighbour.time,
                        timestamp=remote_neighbour.timestamp,
                    )

    def time_query_loop(self):
        """Periodically broadcasts 'what_time_is_it' packets"""
        self.logger.info(f"Starting time query loop (interval={self.time_query_interval}s)")
        while True:
            try:
                self.send_what_time_is_it()
            except Exception as e:
                self.logger.exception(f"Error in time query loop {e.__class__.__name__}: {e}")
            time.sleep(self.time_query_interval)

    def send_what_time_is_it(self):
        """Broadcast a 'what_time_is_it' packet and remember when it was sent."""
        packet = WhatTimeIsItPacket()
        send_ts = time.time()

        with self.pending_requests_lock:
            self.pending_requests[packet.id] = send_ts

        self.logger.debug(f"Broadcasting what_time_is_it id={packet.id}")
        self.publish_packet(packet)

    def handle_what_time_is_it(self, packet: WhatTimeIsItPacket):
        """
        Handle an incoming 'what_time_is_it' packet by responding with 'my_time'.
        Records the local receive time and includes it in the response.
        """
        received_at = time.time()
        self.logger.debug(
            f"what_time_is_it REQUEST from {packet.source} id={packet.id} "
            f"(their time={packet.time})"
        )

        response = MyTimePacket(
            request_id=packet.id,
            request_timestamp=packet.timestamp,
            received_at=received_at,
        )
        self.logger.debug(f"my_time RESPONSE id={response.id} to request {packet.id}")
        self.publish_packet(response)

    def handle_my_time(self, packet: MyTimePacket):
        """
        Handle an incoming 'my_time' response: calculate clock delta and RTT.
        Only processes responses from known neighbours.
        """
        local_receive_ts = time.time()

        lock_wait_start = time.time()
        self.logger.debug("Acquiring pending_requests_lock")
        with self.pending_requests_lock:
            lock_wait_duration = time.time() - lock_wait_start
            local_send_ts = self.pending_requests.pop(packet.request_id, None)

        if lock_wait_duration > 0.001:
            self.logger.warning(f"pending_requests_lock acquisition took {lock_wait_duration:.6f}s")
        else:
            self.logger.debug(f"pending_requests_lock acquisition took {lock_wait_duration:.6f}s")
        self.logger.debug("Releasing pending_requests_lock")

        if local_send_ts is None:
            self.logger.debug(f"my_time UNKNOWN for unknown/expired request_id={packet.request_id} from {packet.source}")
            return None

        result = self.calculate_time_delta(
            local_send_ts=local_send_ts,
            remote_receive_ts=packet.received_at,
            remote_send_ts=packet.timestamp,
            local_receive_ts=local_receive_ts,
            request_id=packet.request_id,
            remote_source=packet.source,
        )

        with self.time_deltas_lock:
            self.time_deltas.append(result)

        # Update neighbour stats
        self.update_neighbour_stats(packet.source, result)

        self.logger.info(
            f"TimeDelta {result.remote_source}: "
            f"clock_delta={result.clock_delta:+.6f}s  RTT={result.rtt:.6f}s  "
            f"(id={result.request_id})"
        )

    def update_neighbour_stats(self, source: str, result: TimeDeltaResult):
        """Update a neighbour's sync statistics with the latest time delta result."""
        with self.neighbours_lock:
            neighbour = self.neighbours.get(source)
            if neighbour is None:
                self.logger.debug(f"Can't update stats for unknown neighbour {source}")
                return

            stats = neighbour.sync_stats
            sync_count = stats.sync_count + 1

            # Running min / max (first sample initialises both)
            if stats.sync_count == 0:
                min_clock_delta = result.clock_delta
                max_clock_delta = result.clock_delta
                min_rtt = result.rtt
                max_rtt = result.rtt
            else:
                min_clock_delta = min(stats.min_clock_delta, result.clock_delta)
                max_clock_delta = max(stats.max_clock_delta, result.clock_delta)
                min_rtt = min(stats.min_rtt, result.rtt)
                max_rtt = max(stats.max_rtt, result.rtt)

            # Cumulative moving average
            mean_clock_delta = stats.mean_clock_delta + (result.clock_delta - stats.mean_clock_delta) / sync_count
            mean_rtt = stats.mean_rtt + (result.rtt - stats.mean_rtt) / sync_count

            neighbour.sync_stats = SyncStats(
                sync_count=sync_count,
                last_sync=time.time(),
                last_clock_delta=result.clock_delta,
                last_rtt=result.rtt,
                min_clock_delta=min_clock_delta,
                max_clock_delta=max_clock_delta,
                mean_clock_delta=mean_clock_delta,
                min_rtt=min_rtt,
                max_rtt=max_rtt,
                mean_rtt=mean_rtt,
            )

            self.logger.debug(
                f"Neighbour {source} sync_stats: "
                f"count={sync_count}  "
                f"delta=[min:{min_clock_delta:+.6f}, avg:{mean_clock_delta:+.6f}, max:{max_clock_delta:+.6f}]  "
                f"rtt=[min:{min_rtt:.6f}, avg:{mean_rtt:.6f}, max:{max_rtt:.6f}]"
            )

    @staticmethod
    def calculate_time_delta(
        local_send_ts: float,
        remote_receive_ts: float,
        remote_send_ts: float,
        local_receive_ts: float,
        request_id: str = "",
        remote_source: str = "",
    ) -> TimeDeltaResult:
        """
        Calculate clock offset and round-trip time using the four timestamps
        (similar to NTP symmetric algorithm).

        Clock delta (θ) ≈ ((T2 - T1) + (T3 - T4)) / 2
        RTT (δ)          = (T4 - T1) - (T3 - T2)

        Where:
            T1 = local_send_ts      (local time when request was sent)
            T2 = remote_receive_ts  (remote time when request was received)
            T3 = remote_send_ts     (remote time when response was sent)
            T4 = local_receive_ts   (local time when response was received)
        """
        rtt = (local_receive_ts - local_send_ts) - (remote_send_ts - remote_receive_ts)
        clock_delta = ((remote_receive_ts - local_send_ts) + (remote_send_ts - local_receive_ts)) / 2.0

        return TimeDeltaResult(
            request_id=request_id,
            remote_source=remote_source,
            clock_delta=clock_delta,
            rtt=rtt,
            local_send_ts=local_send_ts,
            remote_receive_ts=remote_receive_ts,
            remote_send_ts=remote_send_ts,
            local_receive_ts=local_receive_ts,
        )

    def get_time_deltas(self) -> list[TimeDeltaResult]:
        """Return a copy of the collected time delta results."""
        with self.time_deltas_lock:
            return list(self.time_deltas)


    def keepalive_loop(self):
        self.logger.info(f"Starting keepalive loop")
        while True:
            try:
                self.publish_keepalive()
            except Exception as e:
                self.logger.exception(f"Error in keepalive loop {e.__class__.__name__}: {e}")
            time.sleep(self.keepalive_interval)

    def publish_packet(self, packet: BasePacket):
        self.logger.debug(f"Publishing packet: {packet}")
        payload = {
            "body": packet.to_json(),
            "routing_key": packet.type,
        }
        self.publisher_queue.put(payload)

    def publish_keepalive(self):
        self.logger.debug(f"Publishing keepalive message")
        packet = KeepalivePacket()
        self.publish_packet(packet)



if __name__ == "__main__":
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("ExchangeThread").setLevel(logging.WARNING)

    log_level: str = config("LOG_LEVEL", default="INFO", cast=str)  # type: ignore[assignment]
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    tdsvc = TimeDeltaService()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Shutting down TimeDelta Service")
