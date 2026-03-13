#!/usr/bin/env python3
"""
Telemetry Load Test
===================
Launches multiple telemetry clients concurrently to stress-test the server.
Collects results and prints a combined performance summary.

Usage:
  python load_test.py --num-clients 10 --rate-per-client 100 --duration 10
"""

import argparse
import subprocess
import sys
import time
import os


def run_load_test(num_clients: int, rate_per_client: int, duration: float,
                  server_ip: str, server_port: int):
    """
    Spawn multiple telemetry client processes and monitor them.
    """
    print()
    print("═" * 60)
    print("  TELEMETRY LOAD TEST")
    print("═" * 60)
    print(f"  Server         : {server_ip}:{server_port}")
    print(f"  Clients        : {num_clients}")
    print(f"  Rate / client  : {rate_per_client} pkts/sec")
    print(f"  Total rate     : {num_clients * rate_per_client} pkts/sec")
    print(f"  Duration       : {duration}s")
    print(f"  Expected pkts  : {int(num_clients * rate_per_client * duration):,}")
    print("═" * 60)
    print()

    # Determine the path to client.py relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    client_script = os.path.join(script_dir, "client.py")
    
    if not os.path.exists(client_script):
        print(f"Error: client.py not found at {client_script}", file=sys.stderr)
        sys.exit(1)

    # Spawn client processes
    processes = []
    start_time = time.time()
    
    print(f"[Load Test] Spawning {num_clients} clients...")
    for i in range(1, num_clients + 1):
        cmd = [
            sys.executable, client_script,
            '--server-ip', server_ip,
            '--server-port', str(server_port),
            '--client-id', str(i),
            '--rate', str(rate_per_client),
            '--duration', str(duration),
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append((i, proc))
        print(f"  [✓] Client {i} started (PID: {proc.pid})")
    
    print(f"\n[Load Test] All {num_clients} clients launched. Waiting for completion...\n")

    # Wait for all processes to finish and collect output
    results = []
    for client_id, proc in processes:
        stdout, stderr = proc.communicate()
        results.append({
            'client_id': client_id,
            'returncode': proc.returncode,
            'stdout': stdout.decode('utf-8', errors='replace'),
            'stderr': stderr.decode('utf-8', errors='replace'),
        })

    total_time = time.time() - start_time

    # Parse results and print summary
    total_packets_sent = 0
    
    print()
    print("═" * 60)
    print("  LOAD TEST RESULTS")
    print("═" * 60)
    
    for r in results:
        # Extract "Total packets sent" from client output
        packets = 0
        for line in r['stdout'].split('\n'):
            if 'Total packets sent' in line:
                try:
                    packets = int(line.split(':')[-1].strip())
                except ValueError:
                    pass
        total_packets_sent += packets
        
        status = "✓" if r['returncode'] == 0 else "✗"
        print(f"  [{status}] Client {r['client_id']:3d}: {packets:>8,} packets sent"
              f"  (exit code: {r['returncode']})")
        
        if r['stderr'].strip():
            for err_line in r['stderr'].strip().split('\n')[:3]:
                print(f"       {err_line}")
    
    expected_packets = int(num_clients * rate_per_client * duration)
    efficiency = (total_packets_sent / expected_packets * 100) if expected_packets > 0 else 0
    
    print()
    print("  ─────────────────────────────────────")
    print(f"  Total packets sent   : {total_packets_sent:>10,}")
    print(f"  Expected packets     : {expected_packets:>10,}")
    print(f"  Send efficiency      : {efficiency:>9.1f}%")
    print(f"  Total test duration  : {total_time:>9.2f}s")
    print(f"  Aggregate send rate  : {total_packets_sent / total_time:>9.1f} pkts/sec")
    print("═" * 60)
    print()
    print("  NOTE: Check server output for received packet counts and loss stats.")
    print()

    return total_packets_sent


def main():
    parser = argparse.ArgumentParser(
        description='Telemetry Load Test — spawns multiple clients for stress testing')
    parser.add_argument('--num-clients', type=int, default=5,
                        help='Number of concurrent clients (default: 5)')
    parser.add_argument('--rate-per-client', type=int, default=100,
                        help='Packets per second per client (default: 100)')
    parser.add_argument('--duration', type=float, default=10.0,
                        help='Test duration in seconds (default: 10)')
    parser.add_argument('--server-ip', type=str, default='127.0.0.1',
                        help='Server IP address (default: 127.0.0.1)')
    parser.add_argument('--server-port', type=int, default=8888,
                        help='Server UDP port (default: 8888)')
    
    args = parser.parse_args()
    
    if args.num_clients <= 0:
        print("Error: --num-clients must be positive.", file=sys.stderr)
        sys.exit(1)
    
    run_load_test(args.num_clients, args.rate_per_client, args.duration,
                  args.server_ip, args.server_port)


if __name__ == '__main__':
    main()
