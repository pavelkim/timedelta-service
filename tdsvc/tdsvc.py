#!/usr/bin/env python3
# pylint: disable=line-too-long, missing-function-docstring, logging-fstring-interpolation
# pylint: disable=too-many-locals, broad-except, too-many-arguments, raise-missing-from
# pylint: disable=import-error
"""

    TimeDelta Service (tdsvc) - Clock comparison

"""

import logging
import queue
import socket
import threading
import time

import pyp8s
from decouple import config
from py_rmq_exchange import ExchangeThread

from tdsvc.packets import (
    HOST_ID,
    SyncStats,
    Neighbour,
    BasePacket,
    KeepalivePacket,
    NeighborDiscoveryPacket,
    WhatTimeIsItPacket,
    MyTimePacket,
    TimeDeltaResult,
)

def calculate_time_delta(
    local_send_ts: float,
    remote_receive_ts: float,
    remote_send_ts: float,
    local_receive_ts: float,
    response_delay: float = 0.0,
    request_id: str = "",
    remote_source: str = "",
) -> TimeDeltaResult:
    """
    Calculate clock offset and round-trip time using the four timestamps
    (similar to NTP symmetric algorithm).

    Clock delta (θ) ≈ ((T2 - T1) + (T3 - T4)) / 2
    RTT (δ)          = (T4 - T1) - (T3 - T2) + response_delay

    Where:
        T1 = local_send_ts      (local time when request was sent)
        T2 = remote_receive_ts  (remote time when request was received)
        T3 = remote_send_ts     (remote time when response was sent)
        T4 = local_receive_ts   (local time when response was received)
        response_delay          (intentional delay added by remote before responding)
    
    The response_delay is added back to get the actual network RTT,
    excluding the intentional processing delay.
    """
    # Calculate RTT excluding intentional delay
    rtt = (local_receive_ts - local_send_ts) - (remote_send_ts - remote_receive_ts) + response_delay
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


class TimeDeltaService:
    """TimeDelta Service (tdsvc) - Clock comparison"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.host_id = HOST_ID
        self.logger.info(f"Host ID: {self.host_id}")

        self.publisher = None
        self.publisher_queue = queue.Queue()

        self.time_query_thread = None
        self.time_query_interval = config("TIME_QUERY_INTERVAL", default=2, cast=int)
        
        self.neighbor_discovery_thread = None
        self.neighbor_discovery_interval = config("NEIGHBOR_DISCOVERY_INTERVAL", default=5, cast=int)
        self.neighbor_age_timeout = config("NEIGHBOR_AGE_TIMEOUT", default=10, cast=int)
        self.exclude_dead_neighbours = config("EXCLUDE_DEAD_NEIGHBOURS", default=True, cast=bool)
        self.neighbours: dict[str, Neighbour] = {}
        self.neighbours_lock = threading.Lock()

        self.pending_requests: dict[str, float] = {}
        self.pending_requests_lock = threading.Lock()
        # Base max age for pending requests configuration
        base_max_age = config("PENDING_REQUESTS_MAX_AGE", default=10, cast=int)
        
        self.time_deltas: list[TimeDeltaResult] = []
        self.time_deltas_lock = threading.Lock()

        # RTT-based filtering configuration
        self.measurements_window_size = config("MEASUREMENTS_WINDOW_SIZE", default=20, cast=int)
        self.filtered_measurements_count = config("FILTERED_MEASUREMENTS_COUNT", default=5, cast=int)
        
        # Optional static response delay (in seconds) - makes RTT variations proportionally smaller
        # Default 0 (disabled). Set to e.g. 5.0 to add 5-second delay before responding
        self.response_delay = config("RESPONSE_DELAY", default=0.0, cast=float)
        
        # Actual max age accounting for response delay to prevent premature cleanup
        # If peers use response_delay, we need to wait longer for responses
        self.pending_requests_max_age = base_max_age + (self.response_delay * 2)

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
        self.setup_neighbor_discovery_thread()
        self.setup_time_query_thread()
        

    def setup_neighbor_discovery_thread(self):
        self.logger.info(f"Setting up the neighbor discovery thread")
        self.neighbor_discovery_thread = threading.Thread(target=self.neighbor_discovery_loop, daemon=True)
        self.neighbor_discovery_thread.start()

    def setup_time_query_thread(self):
        """Set up a background thread that periodically broadcasts 'what_time_is_it' packets."""
        self.logger.info(
            f"Setting up the time query thread (interval={self.time_query_interval}s, "
            f"pending_requests_ttl={self.pending_requests_max_age}s)"
        )
        self.time_query_thread = threading.Thread(target=self.time_query_loop, daemon=True)
        self.time_query_thread.start()

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
            if self.exclude_dead_neighbours:
                # Only broadcast alive neighbours
                neighbours_data = [
                    neighbour.to_dict()
                    for neighbour in self.neighbours.values()
                    if not neighbour.dead
                ]
            else:
                # Broadcast all neighbours including dead ones
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
                self.cleanup_pending_requests()
                self.send_what_time_is_it()
            except Exception as e:
                self.logger.exception(f"Error in time query loop {e.__class__.__name__}: {e}")
            time.sleep(self.time_query_interval)

    def cleanup_pending_requests(self):
        """Remove pending requests older than the configured max age to prevent unbounded growth."""
        max_age = self.pending_requests_max_age
        now = time.time()
        with self.pending_requests_lock:
            stale = [rid for rid, ts in self.pending_requests.items() if (now - ts) > max_age]
            for rid in stale:
                self.logger.debug(f"Cleaning up stale pending request id={rid} age={(now - self.pending_requests[rid]):.1f}s max_age={max_age}s")
                del self.pending_requests[rid]
            if stale:
                self.logger.debug(f"Cleaned up {len(stale)} stale pending requests")

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
        Optional: adds configured delay before responding to reduce proportional RTT variance.
        
        CRITICAL: If response_delay > 0, spawns a background thread to avoid blocking
        the consumer thread and causing message queue buildup.
        """
        received_at = time.time()
        self.logger.debug(
            f"what_time_is_it REQUEST from {packet.source} id={packet.id} "
            f"(their time={packet.time})"
        )

        # Optional static delay to reduce proportional impact of RTT variations
        # IMPORTANT: Use background thread to avoid blocking the consumer
        if self.response_delay > 0:
            thread = threading.Thread(
                target=self._send_delayed_response,
                args=(packet.id, packet.timestamp, packet.source, received_at, self.response_delay),
                daemon=True
            )
            thread.start()
        else:
            # No delay - respond immediately
            response = MyTimePacket(
                request_id=packet.id,
                request_timestamp=packet.timestamp,
                received_at=received_at,
                response_delay=0.0,
            )
            self.logger.debug(f"my_time RESPONSE to {packet.source} id={packet.id} resp={response.id}")
            self.publish_packet(response)

    def _send_delayed_response(self, request_id: str, request_timestamp: float, 
                               source: str, received_at: float, delay: float):
        """
        Send a delayed response in a background thread to avoid blocking the consumer.
        """
        time.sleep(delay)
        
        response = MyTimePacket(
            request_id=request_id,
            request_timestamp=request_timestamp,
            received_at=received_at,
            response_delay=delay,
        )
        self.logger.debug(f"my_time RESPONSE to {source} id={request_id} resp={response.id} (delayed {delay}s)")
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
            local_send_ts = self.pending_requests.get(packet.request_id)

        if lock_wait_duration > 0.001:
            self.logger.warning(f"pending_requests_lock acquisition took {lock_wait_duration:.6f}s")
        else:
            self.logger.debug(f"pending_requests_lock acquisition took {lock_wait_duration:.6f}s")
        self.logger.debug("Releasing pending_requests_lock")

        self.logger.debug(f"my_time from {packet.source} id={packet.id} "
                          f"(their time={packet.time}, request_id={packet.request_id} ({'known' if local_send_ts else 'unknown'}))")

        if local_send_ts is None:
            self.logger.debug(f"my_time UNKNOWN for unknown/expired request_id={packet.request_id} from {packet.source}")
            return None

        result = calculate_time_delta(
            local_send_ts=local_send_ts,
            remote_receive_ts=packet.received_at,
            remote_send_ts=packet.timestamp,
            local_receive_ts=local_receive_ts,
            response_delay=packet.response_delay,
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

            # Add new measurement to sliding window
            recent = list(stats.recent_measurements)  # Copy the list
            recent.append((result.clock_delta, result.rtt))
            
            # Keep only the most recent N measurements
            if len(recent) > self.measurements_window_size:
                recent = recent[-self.measurements_window_size:]

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

            # Cumulative moving average (unfiltered)
            mean_clock_delta = stats.mean_clock_delta + (result.clock_delta - stats.mean_clock_delta) / sync_count
            mean_rtt = stats.mean_rtt + (result.rtt - stats.mean_rtt) / sync_count

            # RTT-based filtering: find measurement with minimum RTT
            sorted_by_rtt = sorted(recent, key=lambda x: x[1])  # Sort by RTT
            best_measurement = sorted_by_rtt[0]
            best_clock_delta = best_measurement[0]
            best_rtt = best_measurement[1]

            # Calculate filtered mean from lowest-RTT measurements
            filter_count = min(self.filtered_measurements_count, len(sorted_by_rtt))
            filtered_measurements = sorted_by_rtt[:filter_count]
            filtered_mean_clock_delta = sum(m[0] for m in filtered_measurements) / len(filtered_measurements)

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
                best_clock_delta=best_clock_delta,
                best_rtt=best_rtt,
                filtered_mean_clock_delta=filtered_mean_clock_delta,
                recent_measurements=recent,
            )

            self.logger.debug(
                f"Neighbour {source} sync_stats: "
                f"count={sync_count}  "
                f"delta=[min:{min_clock_delta:+.6f}, avg:{mean_clock_delta:+.6f}, max:{max_clock_delta:+.6f}]  "
                f"rtt=[min:{min_rtt:.6f}, avg:{mean_rtt:.6f}, max:{max_rtt:.6f}]  "
                f"filtered=[best:{best_clock_delta:+.6f}@{best_rtt:.6f}s, mean:{filtered_mean_clock_delta:+.6f}]"
            )

    def get_time_deltas(self) -> list[TimeDeltaResult]:
        """Return a copy of the collected time delta results."""
        with self.time_deltas_lock:
            return list(self.time_deltas)

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
    logging.getLogger("pyp8s").setLevel(logging.WARNING)
    logging.getLogger("ExchangeThread").setLevel(logging.WARNING)

    log_level: str = config("LOG_LEVEL", default="INFO", cast=str)  # type: ignore[assignment]
    logging.root.handlers = []
    
    handlers = [logging.StreamHandler()]
    logfile = config("LOGFILE", default="", cast=str)
    if logfile:
        handlers.append(logging.FileHandler(logfile))
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        # level=logging.DEBUG,
        format="%(asctime)s level=%(levelname)s t=%(threadName)s func=%(name)s.%(funcName)s %(message)s",
        handlers=handlers
    )
    

    tdsvc = TimeDeltaService()

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("Shutting down TimeDelta Service")
