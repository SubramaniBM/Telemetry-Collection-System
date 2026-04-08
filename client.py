#!/usr/bin/env python3
"""
Telemetry Client
================
Continuously sends UDP telemetry packets to the collection server.

Protocol: 21-byte binary packets (little-endian)
  [client_id:u32][seq_num:u32][timestamp:f64][metric_type:u8][metric_value:f32]

Usage:
  python client.py --server-ip 127.0.0.1 --server-port 8888 --client-id 1 --rate 100 --duration 10
"""

import argparse
import random
import socket
import struct
import sys
import time
import logging

# Packet format: little-endian uint32, uint32, double, uint8, float = 21 bytes
PACKET_FORMAT = '<IIdBf'
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)

# Metric types
METRIC_CPU     = 0   # 0–100 %
METRIC_MEMORY  = 1   # 0–100 %
METRIC_DISK    = 2   # 0–100 %
METRIC_NETWORK = 3   # 0–1000 Mbps
METRIC_TYPES   = 4

# Realistic value generators for each metric type
METRIC_GENERATORS = {
    METRIC_CPU:     lambda: random.gauss(45, 20),        # avg ~45%, std 20
    METRIC_MEMORY:  lambda: random.gauss(60, 15),        # avg ~60%, std 15
    METRIC_DISK:    lambda: random.gauss(50, 10),        # avg ~50%, std 10
    METRIC_NETWORK: lambda: random.gauss(200, 100),      # avg ~200 Mbps, std 100
}

# Clamp ranges per metric type
METRIC_RANGES = {
    METRIC_CPU:     (0.0, 100.0),
    METRIC_MEMORY:  (0.0, 100.0),
    METRIC_DISK:    (0.0, 100.0),
    METRIC_NETWORK: (0.0, 1000.0),
}


def setup_logger(client_id):
    logger = logging.getLogger(f"Client_{client_id}")
    logger.setLevel(logging.INFO)
    
    # File handler
    fh = logging.FileHandler(f"client_{client_id}.log")
    fh.setLevel(logging.INFO)
    
    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('[%(asctime)s] %(name)s [%(levelname)s] %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def generate_metric_value(metric_type: int) -> float:
    """Generate a realistic metric value for the given type."""
    raw = METRIC_GENERATORS[metric_type]()
    lo, hi = METRIC_RANGES[metric_type]
    return max(lo, min(hi, raw))


def build_packet(client_id: int, seq_num: int, metric_type: int, metric_value: float) -> bytes:
    """Pack a telemetry packet into the binary protocol format."""
    timestamp = time.time()
    return struct.pack(PACKET_FORMAT, client_id, seq_num, timestamp, metric_type, metric_value)


def run_client(server_ip: str, server_port: int, client_id: int,
               rate: int, duration: float, simulate_loss: float):
    """
    Run the telemetry client.
    """
    logger = setup_logger(client_id)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (server_ip, server_port)
    interval = 1.0 / rate if rate > 0 else 0.01

    seq_num = 0
    packets_dropped = 0
    start_time = time.time()
    
    logger.info(f"Sending telemetry to {server_ip}:{server_port}")
    logger.info(f"Rate: {rate} pkts/sec | Duration: {duration}s | Simulated Loss: {simulate_loss}%")
    logger.info(f"Packet size: {PACKET_SIZE} bytes")

    try:
        while True:
            loop_start = time.time()
            
            # Check duration
            elapsed = loop_start - start_time
            if duration > 0 and elapsed >= duration:
                break
            
            # Choose a random metric type and generate a value
            metric_type = random.randint(0, METRIC_TYPES - 1)
            metric_value = generate_metric_value(metric_type)
            
            # Artificial Packet Loss Simulation
            if simulate_loss > 0 and (random.random() * 100) < simulate_loss:
                # We skip sending the packet entirely, but we still consumed the seq_num
                packets_dropped += 1
                seq_num += 1
            else:
                # Build and send packet normally
                packet = build_packet(client_id, seq_num, metric_type, metric_value)
                sock.sendto(packet, dest)
                seq_num += 1
            
            # Progress indicator every 1000 packets
            if seq_num > 0 and seq_num % 1000 == 0:
                logger.info(f"Processed {seq_num} packets ({elapsed:.1f}s elapsed, {packets_dropped} deliberately dropped)")
            
            # Pace sending
            send_time = time.time() - loop_start
            sleep_time = interval - send_time
            if sleep_time > 0:
                time.sleep(sleep_time)
                
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        total_time = time.time() - start_time
        actual_rate = (seq_num - packets_dropped) / total_time if total_time > 0 else 0
        
        logger.info(f"========== Summary ==========")
        logger.info(f"Total sequence numbers consumed : {seq_num}")
        logger.info(f"Actual packets sent to wire     : {seq_num - packets_dropped}")
        logger.info(f"Packets artificially dropped    : {packets_dropped}")
        logger.info(f"Duration                        : {total_time:.2f}s")
        logger.info(f"Actual wire send rate           : {actual_rate:.1f} pkts/sec")
        logger.info(f"Data sent                       : {(seq_num - packets_dropped) * PACKET_SIZE:,} bytes")
        logger.info(f"=============================")
        
        sock.close()
    
    return seq_num


def main():
    parser = argparse.ArgumentParser(
        description='Telemetry Client — sends UDP telemetry data to the collection server')
    parser.add_argument('--server-ip', type=str, default='127.0.0.1',
                        help='Server IP address (default: 127.0.0.1)')
    parser.add_argument('--server-port', type=int, default=8888,
                        help='Server UDP port (default: 8888)')
    parser.add_argument('--client-id', type=int, default=1,
                        help='Unique client identifier (default: 1)')
    parser.add_argument('--rate', type=int, default=100,
                        help='Packets per second (default: 100)')
    parser.add_argument('--duration', type=float, default=10.0,
                        help='Duration in seconds, 0 for infinite (default: 10)')
    parser.add_argument('--simulate-loss', type=float, default=0.0,
                        help='Percentage of packets to intentionally drop to test loss detector (e.g. 5.0)')
    
    args = parser.parse_args()
    
    if args.client_id < 0:
        print("Error: client-id must be non-negative.", file=sys.stderr)
        sys.exit(1)
    if args.rate <= 0:
        print("Error: rate must be positive.", file=sys.stderr)
        sys.exit(1)
    if not (0.0 <= args.simulate_loss <= 100.0):
        print("Error: simulate-loss must be between 0.0 and 100.0", file=sys.stderr)
        sys.exit(1)
    
    run_client(args.server_ip, args.server_port, args.client_id,
               args.rate, args.duration, args.simulate_loss)


if __name__ == '__main__':
    main()
