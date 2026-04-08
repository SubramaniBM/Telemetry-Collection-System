#!/usr/bin/env python3
"""
Telemetry Load Test
===================
Launches multiple telemetry clients concurrently to stress-test the server.
Collects results and prints a combined performance summary. Includes CPU
and memory measurement logic.
"""

import argparse
import subprocess
import sys
import time
import os
import logging
import psutil

def setup_logger():
    logger = logging.getLogger("LoadTester")
    logger.setLevel(logging.INFO)
    fh = logging.FileHandler("load_test.log")
    ch = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(name)s [%(levelname)s] %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

logger = setup_logger()

def run_load_test(num_clients: int, rate_per_client: int, duration: float,
                  server_ip: str, server_port: int, simulate_loss: float):
                  
    logger.info("=" * 60)
    logger.info("  TELEMETRY LOAD TEST WITH PERFORMANCE METRICS")
    logger.info("=" * 60)
    logger.info(f"  Server         : {server_ip}:{server_port}")
    logger.info(f"  Clients        : {num_clients}")
    logger.info(f"  Rate / client  : {rate_per_client} pkts/sec")
    logger.info(f"  Total rate     : {num_clients * rate_per_client} pkts/sec")
    logger.info(f"  Duration       : {duration}s")
    logger.info(f"  Expected pkts  : {int(num_clients * rate_per_client * duration):,}")
    logger.info(f"  Simulated Loss : {simulate_loss}%")
    logger.info("=" * 60)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    client_script = os.path.join(script_dir, "client.py")
    
    if not os.path.exists(client_script):
        logger.error(f"client.py not found at {client_script}")
        sys.exit(1)

    processes = []
    
    # Track host CPU metrics
    process = psutil.Process()
    cpu_start = process.cpu_percent()
    cpu_measurements = []

    logger.info(f"Spawning {num_clients} clients...")
    start_time = time.time()
    
    for i in range(1, num_clients + 1):
        cmd = [
            sys.executable, client_script,
            '--server-ip', server_ip,
            '--server-port', str(server_port),
            '--client-id', str(i),
            '--rate', str(rate_per_client),
            '--duration', str(duration),
            '--simulate-loss', str(simulate_loss)
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append((i, proc))
        logger.info(f"  [OK] Client {i} started (PID: {proc.pid})")
    
    logger.info(f"\nAll {num_clients} clients launched. Collecting CPU metrics while running...\n")

    # Monitor CPU while waiting for duration
    while any(p.poll() is None for _, p in processes):
        cpu_measurements.append(psutil.cpu_percent(interval=0.5))

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
    total_packets_sent = 0
    total_artificially_dropped = 0
    
    logger.info("=" * 60)
    logger.info("  LOAD TEST RESULTS")
    logger.info("=" * 60)
    
    for r in results:
        packets_sent = 0
        dropped = 0
        
        for line in r['stdout'].split('\n'):
            if 'Actual packets sent' in line:
                try: packets_sent = int(line.split(':')[-1].strip())
                except ValueError: pass
            if 'Packets artificially dropped' in line:
                try: dropped = int(line.split(':')[-1].strip())
                except ValueError: pass
        
        total_packets_sent += packets_sent
        total_artificially_dropped += dropped
        
        status = "OK" if r['returncode'] == 0 else "FAIL"
        logger.info(f"  [{status}] Client {r['client_id']:3d}: {packets_sent:>8,} sent, {dropped:>4,} dropped")
        
        if r['stderr'].strip():
            for err_line in r['stderr'].strip().split('\n')[:3]:
                logger.error(f"       {err_line}")
    
    expected_packets = int(num_clients * rate_per_client * duration)
    # The clients are dropping simulate_loss %, so actual wire expected is less
    wire_expected = expected_packets * (1.0 - (simulate_loss/100.0))
    efficiency = (total_packets_sent / wire_expected * 100) if wire_expected > 0 else 0
    
    avg_cpu = sum(cpu_measurements) / len(cpu_measurements) if cpu_measurements else 0.0

    logger.info("  -------------------------------------")
    logger.info(f"  Expected (Wire) Pkts : {int(wire_expected):>10,}")
    logger.info(f"  Total sent to wire   : {total_packets_sent:>10,}")
    logger.info(f"  Intentionally Dropped: {total_artificially_dropped:>10,}")
    logger.info(f"  Send efficiency      : {efficiency:>9.1f}%")
    logger.info(f"  Total test duration  : {total_time:>9.2f}s")
    logger.info(f"  Aggregate send rate  : {total_packets_sent / total_time:>9.1f} pkts/sec")
    logger.info(f"  Avg System CPU Usage : {avg_cpu:>9.1f}%")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Telemetry Load Test')
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
    parser.add_argument('--simulate-loss', type=float, default=0.0,
                        help='Artificial packet loss percentage (0-100)')
    
    args = parser.parse_args()
    
    run_load_test(args.num_clients, args.rate_per_client, args.duration,
                  args.server_ip, args.server_port, args.simulate_loss)


if __name__ == '__main__':
    main()
