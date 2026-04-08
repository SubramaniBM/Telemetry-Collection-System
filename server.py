#!/usr/bin/env python3
"""
Telemetry Collection and Aggregation Server

A high-performance UDP server that receives telemetry data from
multiple distributed clients, tracks packet sequences, detects
losses, and aggregates metrics with periodic reporting.

Protocol: 21-byte binary packets
  [client_id:4][seq_num:4][timestamp:8][metric_type:1][metric_value:4]

Usage:
  python server.py [port]   (default port: 8888)
"""

import socket
import struct
import sys
import time
import signal
import select

# Configuration
DEFAULT_PORT = 8888
PACKET_FORMAT = '<IIdBf'
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
REPORT_INTERVAL_SEC = 5
METRIC_TYPES = 4

METRIC_NAMES = [
    "CPU (%)", "Memory (%)", "Disk (%)", "Network (Mbps)"
]

g_running = True

def handle_sigint(sig, frame):
    global g_running
    g_running = False

class MetricStats:
    def __init__(self):
        self.sum = 0.0
        self.min_val = float('inf')
        self.max_val = float('-inf')
        self.count = 0

class ClientState:
    def __init__(self, client_id):
        self.client_id = client_id
        self.expected_seq = 0
        self.packets_received = 0
        self.packets_lost = 0
        self.first_timestamp = 0.0
        self.last_timestamp = 0.0
        self.metrics = [MetricStats() for _ in range(METRIC_TYPES)]

def print_separator():
    print("===============================================================")

def print_report(clients_map, server_start_time, total_packets, total_lost, is_final=False):
    now = time.time()
    elapsed = now - server_start_time
    
    print()
    print_separator()
    if is_final:
        print("  FINAL TELEMETRY REPORT")
    else:
        print(f"  PERIODIC TELEMETRY REPORT  ({int(elapsed)}s elapsed)")
    print_separator()
    
    active_clients = len(clients_map)
    for client_id, c in clients_map.items():
        duration = c.last_timestamp - c.first_timestamp
        rate = c.packets_received / duration if duration > 0.0 else 0.0
        
        total_expected = c.packets_received + c.packets_lost
        loss_pct = (100.0 * c.packets_lost / total_expected) if total_expected > 0 else 0.0
        
        print(f"\n  +- Client {client_id}")
        print(f"  |  Packets received : {c.packets_received}")
        print(f"  |  Packets lost     : {c.packets_lost}")
        print(f"  |  Loss rate        : {loss_pct:.2f}%")
        print(f"  |  Ingestion rate   : {rate:.1f} pkts/sec")
        print("  |")
        
        for m in range(METRIC_TYPES):
            ms = c.metrics[m]
            if ms.count == 0:
                continue
            avg = ms.sum / ms.count
            print(f"  |  {METRIC_NAMES[m]:<16} : avg={avg:.2f}  min={ms.min_val:.2f}  max={ms.max_val:.2f}  (n={ms.count})")
        print("  +-")
        
    print("\n  GLOBAL SUMMARY")
    print("  -------------------------------------")
    print(f"  Active clients     : {active_clients}")
    print(f"  Total packets recv : {total_packets}")
    print(f"  Total packets lost : {total_lost}")
    
    global_total = total_packets + total_lost
    if global_total > 0:
        agg_loss = 100.0 * total_lost / global_total
        print(f"  Aggregate loss %   : {agg_loss:.2f}%")
    
    if elapsed > 0:
        overall_rate = total_packets / elapsed
        print(f"  Overall rate       : {overall_rate:.1f} pkts/sec")
    
    print_separator()
    print()

def main():
    global g_running
    
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            print(f"Invalid port: {sys.argv[1]}", file=sys.stderr)
            sys.exit(1)
            
    signal.signal(signal.SIGINT, handle_sigint)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Allow address reuse
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Try increasing receive buffer for high-rate ingestion
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass # Buffer sizes are OS dependent, might not be allowed in all environments
        
    try:
        sock.bind(('0.0.0.0', port))
    except Exception as e:
        print(f"Bind failed on port {port}: {e}", file=sys.stderr)
        sys.exit(1)
        
    sock.setblocking(False)
    
    clients_map = {}
    total_packets = 0
    total_lost = 0
    server_start_time = time.time()
    last_report_time = server_start_time
    
    print()
    print_separator()
    print("  TELEMETRY COLLECTION SERVER (Python)")
    print(f"  Listening on 0.0.0.0:{port} (UDP)")
    print(f"  Report interval: {REPORT_INTERVAL_SEC}s")
    print("  Press Ctrl+C to stop and print final report.")
    print_separator()
    print()
    
    while g_running:
        try:
            # Use select with a short timeout to prevent busy waiting
            r, _, _ = select.select([sock], [], [], 0.05)
            if sock in r:
                data, addr = sock.recvfrom(65536)
                if len(data) >= PACKET_SIZE:
                    client_id, seq_num, timestamp, metric_type, metric_value = struct.unpack(PACKET_FORMAT, data[:21])
                    
                    if metric_type >= METRIC_TYPES:
                        print(f"[WARN] Invalid metric_type {metric_type} from client {client_id}, ignoring.", file=sys.stderr)
                        continue
                        
                    if client_id not in clients_map:
                        clients_map[client_id] = ClientState(client_id)
                        
                    c = clients_map[client_id]
                    
                    if c.packets_received == 0:
                        c.expected_seq = seq_num + 1
                        c.first_timestamp = timestamp
                    else:
                        if seq_num > c.expected_seq:
                            lost = seq_num - c.expected_seq
                            c.packets_lost += lost
                            total_lost += lost
                        c.expected_seq = seq_num + 1
                        
                    c.packets_received += 1
                    c.last_timestamp = timestamp
                    total_packets += 1
                    
                    ms = c.metrics[metric_type]
                    ms.sum += metric_value
                    ms.count += 1
                    if metric_value < ms.min_val:
                        ms.min_val = metric_value
                    if metric_value > ms.max_val:
                        ms.max_val = metric_value
                        
        except BlockingIOError:
            pass
        except OSError as e:
            # Ignore errors that might happen when closing
            if not g_running:
                break
                
        now = time.time()
        if now - last_report_time >= REPORT_INTERVAL_SEC:
            print_report(clients_map, server_start_time, total_packets, total_lost, is_final=False)
            last_report_time = now
            
    print("\n[INFO] Shutting down...")
    print_report(clients_map, server_start_time, total_packets, total_lost, is_final=True)
    sock.close()

if __name__ == "__main__":
    main()
