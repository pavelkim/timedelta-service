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
import socket
import time

import pyp8s
from decouple import config
from py_rmq_exchange import ExchangeThread

from tdsvc.packets import (
    BasePacket,
    Neighbour,
    NeighborDiscoveryPacket,
    SyncStats,
)


class TimeDeltaExporter:
    """Passively listens to neighbor_discovery messages and prints a stats overview."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

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
            if neighbour.source:
                neighbours[neighbour.source] = neighbour

        self.hosts[source] = neighbours
        self.logger.debug(f"Updated host {source}: {len(neighbours)} neighbours")

    def display_stats(self):
        """Print a formatted table of all known hosts and their neighbours' sync stats."""
        if not self.hosts:
            print("\n[ No hosts discovered yet ]\n")
            return

        # Clear screen
        print("\033[2J\033[H", end="")

        now = time.time()
        ts = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime(now))
        print(f"=== TimeDelta Exporter  |  {ts} ===\n")

        for host, neighbours in sorted(self.hosts.items()):
            print(f"  Host: {host}")

            if not neighbours:
                print(f"    (no neighbours)\n")
                continue

            # Table header
            header = (
                f"    {'Neighbour':<20s}  "
                f"{'Dead':>4s}  "
                f"{'Syncs':>5s}  "
                f"{'Clock Δ (last)':>16s}  "
                f"{'Clock Δ (mean)':>16s}  "
                f"{'RTT (last)':>12s}  "
                f"{'RTT (mean)':>12s}"
            )
            print(header)
            print(f"    {'─' * (len(header) - 4)}")

            for n_source, neighbour in sorted(neighbours.items()):
                s = neighbour.sync_stats
                dead_str = "DEAD" if neighbour.dead else "ok"

                if s.sync_count > 0:
                    row = (
                        f"    {n_source:<20s}  "
                        f"{dead_str:>4s}  "
                        f"{s.sync_count:>5d}  "
                        f"{s.last_clock_delta:>+16.6f}  "
                        f"{s.mean_clock_delta:>+16.6f}  "
                        f"{s.last_rtt:>12.6f}  "
                        f"{s.mean_rtt:>12.6f}"
                    )
                else:
                    row = (
                        f"    {n_source:<20s}  "
                        f"{dead_str:>4s}  "
                        f"{'–':>5s}  "
                        f"{'–':>16s}  "
                        f"{'–':>16s}  "
                        f"{'–':>12s}  "
                        f"{'–':>12s}"
                    )
                print(row)

            print()

        print(f"  ({len(self.hosts)} host(s) reporting)\n")

    def run(self):
        """Main loop: periodically display the stats table."""
        self.logger.info(f"Exporter running (display every {self.display_interval}s)")
        try:
            while True:
                self.display_stats()
                time.sleep(self.display_interval)
        except KeyboardInterrupt:
            print("\nExporter shutting down.")


if __name__ == "__main__":
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("ExchangeThread").setLevel(logging.WARNING)

    log_level: str = config("LOG_LEVEL", default="INFO", cast=str)  # type: ignore[assignment]
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    exporter = TimeDeltaExporter()
    exporter.run()
