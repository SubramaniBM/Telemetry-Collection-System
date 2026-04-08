#!/usr/bin/env python3
"""
Telemetry Collection and Aggregation Server

A high-performance UDP server that receives telemetry data from
multiple distributed clients, tracks packet sequences, detects
losses, aggregates metrics with periodic reporting.

New Improvements:
- Multithreaded (Producer-Consumer architecture)
- Permanent Database Storage (SQLite)
- Structured Logging
- Latency Metrics
"""

import socket
import struct
import sys
import time
import signal
import select
import threading
import queue
import sqlite3
import logging
import os

# Configuration
DEFAULT_PORT = 8888
PACKET_FORMAT = '<IIdBf'
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)
REPORT_INTERVAL_SEC = 5
METRIC_TYPES = 4
DB_FILE = "telemetry.db"

METRIC_NAMES = [
    "CPU (%)", "Memory (%)", "Disk (%)", "Network (Mbps)"
]

g_running = True

# Thread-safe queue for incoming packets via UDP
packet_queue = queue.Queue()

# Setup Structured Logging
def setup_logger():
    logger = logging.getLogger("TelemetryServer")
    logger.setLevel(logging.INFO)
    
    fh = logging.FileHandler("server.log")
    fh.setLevel(logging.INFO)
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter('[%(asctime)s] %(name)s [%(levelname)s] %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger

logger = setup_logger()

# Setup Database
def setup_database():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            sequence_num INTEGER,
            timestamp REAL,
            server_timestamp REAL,
            metric_type INTEGER,
            metric_value REAL
        )
    ''')
    conn.commit()
    return conn

def handle_sigint(sig, frame):
    global g_running
    g_running = False
    logger.info("SIGINT received. Shutting down cleanly...")

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
        self.latency_sum = 0.0
        self.lock = threading.Lock() # Provide thread safety for this client

def print_report(clients_map, server_start_time, total_packets, total_lost):
    now = time.time()
    elapsed = now - server_start_time
    
    logger.info("===============================================================")
    logger.info(f"  PERIODIC TELEMETRY REPORT  ({int(elapsed)}s elapsed)")
    logger.info("===============================================================")
    
    active_clients = len(clients_map)
    for client_id, c in list(clients_map.items()):
        with c.lock: # Lock thread state while building report
            duration = c.last_timestamp - c.first_timestamp
            rate = c.packets_received / duration if duration > 0.0 else 0.0
            
            total_expected = c.packets_received + c.packets_lost
            loss_pct = (100.0 * c.packets_lost / total_expected) if total_expected > 0 else 0.0
            
            avg_latency = (c.latency_sum / c.packets_received * 1000) if c.packets_received > 0 else 0.0 # ms

            logger.info(f"  +- Client {client_id}")
            logger.info(f"  |  Packets received : {c.packets_received}")
            logger.info(f"  |  Packets lost     : {c.packets_lost}")
            logger.info(f"  |  Loss rate        : {loss_pct:.2f}%")
            logger.info(f"  |  Ingestion rate   : {rate:.1f} pkts/sec")
            logger.info(f"  |  Avg Latency      : {avg_latency:.2f} ms")
            logger.info("  |")
            
            for m in range(METRIC_TYPES):
                ms = c.metrics[m]
                if ms.count == 0:
                    continue
                avg = ms.sum / ms.count
                logger.info(f"  |  {METRIC_NAMES[m]:<16} : avg={avg:.2f}  min={ms.min_val:.2f}  max={ms.max_val:.2f}  (n={ms.count})")
            logger.info("  +-")
        
    logger.info("  GLOBAL SUMMARY")
    logger.info("  -------------------------------------")
    logger.info(f"  Active clients     : {active_clients}")
    logger.info(f"  Total packets recv : {total_packets}")
    logger.info(f"  Total packets lost : {total_lost}")
    
    global_total = total_packets + total_lost
    if global_total > 0:
        agg_loss = 100.0 * total_lost / global_total
        logger.info(f"  Aggregate loss %   : {agg_loss:.2f}%")
    
    if elapsed > 0:
        overall_rate = total_packets / elapsed
        logger.info(f"  Overall rate       : {overall_rate:.1f} pkts/sec")
    
    logger.info("===============================================================")

# Globals for report
global_total_packets = 0
global_total_lost = 0
clients_map = {}
clients_map_lock = threading.Lock()

def db_writer_thread(db_queue):
    """ Dedicated thread purely for writing telemetry to SQLite permanently """
    conn = setup_database()
    cursor = conn.cursor()
    batch = []
    
    while True:
        try:
            # Block waiting for items
            item = db_queue.get(timeout=1.0)
            if item is None:
                break # Shutdown signal
            batch.append(item)
            
            # Flush batch if large enough to avoid locking the DB continuously
            if len(batch) >= 1000:
                cursor.executemany('''
                    INSERT INTO telemetry (client_id, sequence_num, timestamp, server_timestamp, metric_type, metric_value)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', batch)
                conn.commit()
                batch.clear()
        except queue.Empty:
            # On timeout, if batch has content, flush it
            if batch:
                cursor.executemany('''
                    INSERT INTO telemetry (client_id, sequence_num, timestamp, server_timestamp, metric_type, metric_value)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', batch)
                conn.commit()
                batch.clear()
                
    # Final flush on exit
    if batch:
        cursor.executemany('''
            INSERT INTO telemetry (client_id, sequence_num, timestamp, server_timestamp, metric_type, metric_value)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', batch)
        conn.commit()
    conn.close()


def worker_thread(worker_id, db_queue):
    """ Thread that takes packets from memory queue and updates metrics """
    global global_total_packets, global_total_lost
    
    while g_running or not packet_queue.empty():
        try:
            data, server_timestamp = packet_queue.get(timeout=0.2)
            
            # 1. Unpack immediately
            client_id, seq_num, timestamp, metric_type, metric_value = struct.unpack(PACKET_FORMAT, data[:21])
            latency = server_timestamp - timestamp
            
            # Send to DB Writer thread
            db_queue.put((client_id, seq_num, timestamp, server_timestamp, metric_type, metric_value))
            
            if metric_type >= METRIC_TYPES:
                logger.warning(f"Invalid metric_type {metric_type} from client {client_id}, ignoring.")
                packet_queue.task_done()
                continue
            
            # 2. Get or create ClientState
            with clients_map_lock:
                if client_id not in clients_map:
                    clients_map[client_id] = ClientState(client_id)
                c = clients_map[client_id]
            
            # 3. Update state thread-safely
            with c.lock:
                if c.packets_received == 0:
                    c.expected_seq = seq_num + 1
                    c.first_timestamp = timestamp
                else:
                    if seq_num > c.expected_seq:
                        # Packet loss or skip detected
                        lost = seq_num - c.expected_seq
                        c.packets_lost += lost
                        # global stat update (minimal lock time)
                        # We won't strictly lock globals if perfect accuracy in print out isn't deeply critical, 
                        # but for correctness we can use clients_map_lock 
                        global_total_lost += lost
                    c.expected_seq = seq_num + 1
                    
                c.packets_received += 1
                c.last_timestamp = timestamp
                c.latency_sum += latency
                
                ms = c.metrics[metric_type]
                ms.sum += metric_value
                ms.count += 1
                if metric_value < ms.min_val:
                    ms.min_val = metric_value
                if metric_value > ms.max_val:
                    ms.max_val = metric_value
                    
            # Increment global rx
            global_total_packets += 1
            
            packet_queue.task_done()
            
        except queue.Empty:
            continue

def main():
    global g_running
    
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            logger.error(f"Invalid port: {sys.argv[1]}")
            sys.exit(1)
            
    signal.signal(signal.SIGINT, handle_sigint)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass
        
    try:
        sock.bind(('0.0.0.0', port))
    except Exception as e:
        logger.error(f"Bind failed on port {port}: {e}")
        sys.exit(1)
        
    sock.setblocking(False)
    
    # Start Database Writer Thread
    db_queue = queue.Queue()
    db_thread = threading.Thread(target=db_writer_thread, args=(db_queue,))
    db_thread.start()
    
    # Start Worker Pool (3 threads)
    num_workers = 3
    workers = []
    for i in range(num_workers):
        t = threading.Thread(target=worker_thread, args=(i, db_queue))
        t.start()
        workers.append(t)
    
    server_start_time = time.time()
    last_report_time = server_start_time
    
    logger.info("===============================================================")
    logger.info("  TELEMETRY COLLECTION SERVER (Python)")
    logger.info(f"  Listening on 0.0.0.0:{port} (UDP)")
    logger.info(f"  Report interval: {REPORT_INTERVAL_SEC}s")
    logger.info(f"  Workers: {num_workers} threads | DB: {DB_FILE}")
    logger.info("  Press Ctrl+C to stop and save.")
    logger.info("===============================================================")
    
    while g_running:
        try:
            r, _, _ = select.select([sock], [], [], 0.05)
            if sock in r:
                data, addr = sock.recvfrom(65536)
                if len(data) >= PACKET_SIZE:
                    # Push to queue for threads instead of processing main thread
                    packet_queue.put((data, time.time()))
                        
        except BlockingIOError:
            pass
        except OSError as e:
            if not g_running:
                break
                
        now = time.time()
        if now - last_report_time >= REPORT_INTERVAL_SEC:
            print_report(clients_map, server_start_time, global_total_packets, global_total_lost)
            last_report_time = now
            
    # Shutdown sequence
    logger.info("Waiting for queue to flush...")
    packet_queue.join()  # block until all enqueued packets are processed
    db_queue.put(None)   # Signal DB thread to terminate
    
    logger.info("Joining worker threads...")
    for t in workers:
        t.join()
    db_thread.join()
        
    logger.info("Final Report:")
    print_report(clients_map, server_start_time, global_total_packets, global_total_lost)
    sock.close()
    logger.info("Shutdown complete.")

if __name__ == "__main__":
    main()
