#!/usr/bin/env python3
# pylint: disable=line-too-long, missing-function-docstring, logging-fstring-interpolation
# pylint: disable=import-error
"""

    TimeDelta Service Exporter (tdsvc_exporter)

    Listens to neighbor_discovery packets on the RabbitMQ exchange and
    displays a formatted table of hosts, their neighbours, and sync stats.

"""

import logging
import os
import signal
import socket
import threading
import time

from pyp8s import MetricsHandler
from decouple import config
from py_rmq_exchange import ExchangeThread

from tdsvc.packets import (
    BasePacket,
    Neighbour,
    NeighborDiscoveryPacket,
    SyncStats,
)

# Setup signal handlers for graceful shutdown
def signal_handler(signum, frame):
    print("\nReceived shutdown signal, stopping exporter...")
    exporter.stop()


class TimeDeltaExporter(threading.Thread):
    """Passively listens to neighbor_discovery messages and prints a stats overview."""

    def __init__(self):
        super().__init__(daemon=True)
        self.logger = logging.getLogger(__name__)
        self._stop_event = threading.Event()

        self.rmq_server_uri = config("RMQ_SERVER_URI", default="amqp://guest:guest@localhost:5672/")
        self.rmq_exchange = config("RMQ_EXCHANGE", default="tdsvc_exchange")
        self.rmq_dlx_exchange = config("RMQ_DLX_EXCHANGE", default="dlx_tdsvc_exchange")

        # host_id -> { neighbour_source -> Neighbour }
        self.hosts: dict[str, dict[str, Neighbour]] = {}

        self.display_interval = config("EXPORTER_DISPLAY_INTERVAL", default=5, cast=int)

        self.logger.info("Setting up exporter consumer")
        self.consumer_params = {
            "exchange": self.rmq_exchange,
            "exchange_type": "direct",
            "routing_keys": ["neighbor_discovery"],
            "on_message_callback": self.consumer_callback,
            "auto_ack": False,
            "exclusive": True,
            "prefetch_count": config("RMQ_PREFETCH_COUNT", default=1, cast=int),
            "queue_declare_arguments": {
                "x-dead-letter-exchange": self.rmq_dlx_exchange,
            },
        }

        self.consumer = ExchangeThread(rmq_server_uri=self.rmq_server_uri)
        self.consumer.setup_consumer(**self.consumer_params)
        self.consumer.start()
        self.logger.info("Exporter consumer started")

    def consumer_callback(self, event):
        channel = event["channel"]
        method = event["method"]
        delivery_tag = method.delivery_tag

        try:
            body_str = event["body"]
            packet = BasePacket.decode_packet(body_str)

            if isinstance(packet, NeighborDiscoveryPacket):
                self.handle_neighbor_discovery(packet)

            channel.basic_ack(delivery_tag)
        except Exception as e:
            self.logger.exception(f"Error processing event: {e}")
            channel.basic_nack(delivery_tag)

    def handle_neighbor_discovery(self, packet: NeighborDiscoveryPacket):
        """Record the sender's neighbour list including sync stats."""
        source = packet.source
        neighbours: dict[str, Neighbour] = {}

        for neighbour_data in packet.neighbours:
            neighbour = Neighbour.from_dict(neighbour_data)
    
            # Use filtered (best) clock delta for metrics - more accurate than raw mean
            MetricsHandler.set("tdsvc_delta_filtered", neighbour.sync_stats.filtered_mean_clock_delta, source=source, neighbour=neighbour.source, neighbour_up=neighbour.up)
            MetricsHandler.set("tdsvc_delta_best", neighbour.sync_stats.best_clock_delta, source=source, neighbour=neighbour.source, neighbour_up=neighbour.up)
            MetricsHandler.set("tdsvc_delta_raw", neighbour.sync_stats.last_clock_delta, source=source, neighbour=neighbour.source, neighbour_up=neighbour.up)
            MetricsHandler.set("tdsvc_rtt", neighbour.sync_stats.last_rtt, source=source, neighbour=neighbour.source, neighbour_up=neighbour.up)
            MetricsHandler.set("tdsvc_rtt_best", neighbour.sync_stats.best_rtt, source=source, neighbour=neighbour.source, neighbour_up=neighbour.up)
            MetricsHandler.set("tdsvc_syncs", neighbour.sync_stats.sync_count, source=source, neighbour=neighbour.source, neighbour_up=neighbour.up)
            MetricsHandler.set("tdsvc_neighbour", neighbour.up, source=source)

            if neighbour.source:
                neighbours[neighbour.source] = neighbour

        self.hosts[source] = neighbours
        self.logger.debug(f"Updated host {source}: {len(neighbours)} neighbours")

    def render_stats(self):
        """Render a formatted table of all known hosts and their neighbours' sync stats."""
        if not self.hosts:
            return "\n[ No hosts discovered yet ]\n"

        # Build complete output
        output = []
        
        # Clear screen
        output.append("\033[2J\033[H")

        now = time.time()
        ts = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(now))
        output.append(f"=== TimeDelta Exporter  |  {ts} ===\n\n")

        for host, neighbours in sorted(self.hosts.items()):
            output.append(f"  Host: {host}\n")

            if not neighbours:
                output.append(f"    (no neighbours)\n\n")
                continue

            # Table header
            header = (
                f"    {'Neighbour':<20s}  "
                f"{'Dead':>4s}  "
                f"{'Syncs':>5s}  "
                f"{'Δ (best)':>14s}  "
                f"{'Δ (filt)':>14s}  "
                f"{'Δ (raw)':>14s}  "
                f"{'RTT (last)':>12s}  "
                f"{'RTT (best)':>12s}"
            )
            output.append(header + "\n")
            output.append(f"    {'─' * (len(header) - 4)}\n")

            for n_source, neighbour in sorted(neighbours.items()):
                s = neighbour.sync_stats
                dead_str = "DEAD" if neighbour.dead else "ok"

                if s.sync_count > 0:
                    row = (
                        f"    {n_source:<20s}  "
                        f"{dead_str:>4s}  "
                        f"{s.sync_count:>5d}  "
                        f"{s.best_clock_delta:>+14.6f}  "
                        f"{s.filtered_mean_clock_delta:>+14.6f}  "
                        f"{s.last_clock_delta:>+14.6f}  "
                        f"{s.last_rtt:>12.6f}  "
                        f"{s.best_rtt:>12.6f}"
                    )
                else:
                    row = (
                        f"    {n_source:<20s}  "
                        f"{dead_str:>4s}  "
                        f"{'–':>5s}  "
                        f"{'–':>14s}  "
                        f"{'–':>14s}  "
                        f"{'–':>14s}  "
                        f"{'–':>12s}  "
                        f"{'–':>12s}"
                    )
                output.append(row + "\n")

            output.append("\n")

        output.append(f"  ({len(self.hosts)} host(s) reporting)\n")
        
        # Print all at once
        return "".join(output)

    def stop(self):
        """Signal the thread to stop."""
        self.logger.info("Stopping exporter...")
        self._stop_event.set()
        if hasattr(self, 'consumer'):
            self.consumer.stop()

    def run(self):
        """Main loop: periodically display the stats table."""
        self.logger.info(f"Exporter running (display every {self.display_interval}s)")
        while not self._stop_event.is_set():
            self.logger.debug("Existing")
            self._stop_event.wait(self.display_interval)


if __name__ == "__main__":
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("ExchangeThread").setLevel(logging.WARNING)

    log_level: str = config("LOG_LEVEL", default="INFO", cast=str)  # type: ignore[assignment]
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    
    METRICS_PORT = config("METRICS_PORT", default=18211, cast=int)
    METRICS_HOST = config("METRICS_HOST", default="0.0.0.0", cast=str)

    exporter = TimeDeltaExporter()
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start metrics server and set callback
    MetricsHandler.set_page("/tdsvc_exporter", callback=exporter.render_stats)
    MetricsHandler.serve(listen_address=METRICS_HOST, listen_port=METRICS_PORT)
    
    # Start exporter thread
    exporter.start()
    
    # Wait for thread to finish
    try:
        exporter.join()
    except KeyboardInterrupt:
        exporter.stop()
        exporter.join()
    
    logging.warning("Exporter shut down.")
