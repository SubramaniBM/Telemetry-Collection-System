# Telemetry Collection and Aggregation System

A UDP-based distributed telemetry system fully implemented in Python. Multiple clients continuously send telemetry data to a high-performance multithreaded server. The server tracks packet sequences, detects volumetric losses natively, logs all telemetry permanently via an SQLite database, and computes deep host machine/network metrics on the fly. 

## Features
- **Multithreading** — Producer-Consumer threaded architecture to isolate ingestion and database saving.
- **Database Storage** — Records permanently synced to local `telemetry.db`.
- **Packet Loss Simulation** — Built-in client arguments to artificially drop packets to test algorithmic loss tracking.
- **Deep Metrics & Latency Profiling** — Accurately tracks one-way micro-latency and the active host's CPU footprint via `psutil`.
- **Structured Logging** — Everything routes via the `logging` framework simultaneously to console and isolated `.log` files.

## Architecture

```
┌─────────────┐           ┌───────────────────────────┐
│  Client 1   │──── UDP──►│                           │
│  (Python)   │           │ Telemetry Server (Python) │
├─────────────┤           │                           │
│  Client 2   │──── UDP──►│  • Queue-based Ingestion  │
│  (Python)   │           │  • Sequence Tracking      │
├─────────────┤           │  • Loss Detection         │
│  Client N   │──── UDP──►│  • Latency Calculation    │
│  (Python)   │           │  • Threaded DB Writer     │
└─────────────┘           └───────────────────────────┘
```

## Protocol

Each telemetry packet is a **21-byte binary structure** (little-endian):

| Field         | Type   | Size  | Description                         |
|---------------|--------|-------|-------------------------------------|
| `client_id`   | uint32 | 4 B   | Unique client identifier            |
| `sequence_num`| uint32 | 4 B   | Monotonically increasing per client |
| `timestamp`   | double | 8 B   | Unix epoch timestamp (seconds)      |
| `metric_type` | uint8  | 1 B   | 0=CPU, 1=Memory, 2=Disk, 3=Network |
| `metric_value`| float  | 4 B   | The telemetry metric value          |

## Files

| File           | Language | Description                              |
|----------------|----------|------------------------------------------|
| `server.py`    | Python   | UDP threaded telemetry server            |
| `client.py`    | Python   | Telemetry sender client                  |
| `load_test.py` | Python   | Multi-client scalability/stress test     |
| `Makefile`     | Make     | Convenience commands                     |
| `telemetry.db` | SQLite   | Auto-generated permanent database store  |

## Requirements

### Prerequisites
- **Python 3.6+**

You will need the `psutil` library to accurately compute host system profiling:
```bash
pip install psutil
```

## Usage

### 1. Start the Server

```bash
# Default port 8888
python server.py

# Custom port
python server.py 9000
```

The multithreaded server produces periodic summaries computing rate, aggregate loss, and one-way network latency exactly like so:
```
  +- Client 1
  |  Packets received : 462
  |  Packets lost     : 20
  |  Loss rate        : 4.14%
  |  Ingestion rate   : 92.4 pkts/sec
  |  Avg Latency      : 0.23 ms
  |
  |  CPU (%)          : avg=48.46  min=0.00  max=92.87  (n=126)
  +-
```
Press **Ctrl+C** to trigger a graceful flush, waiting for queues to empty before recording final arrays to the SQLite database.

### 2. Run a Single Client

```bash
python client.py --server-ip 127.0.0.1 --server-port 8888 --client-id 1 --rate 100 --duration 10 --simulate-loss 5
```

| Argument          | Default     | Description                                   |
|-------------------|-------------|-----------------------------------------------|
| `--server-ip`     | `127.0.0.1` | Server IP address                             |
| `--server-port`   | `8888`      | Server UDP port                               |
| `--client-id`     | `1`         | Unique client identifier                      |
| `--rate`          | `100`       | Packets per second                            |
| `--duration`      | `10`        | Sending duration (seconds), 0 = infinite      |
| `--simulate-loss` | `0.0`       | Artificially skips transmission loop per % limit |

### 3. Run the Load Test

```bash
python load_test.py --num-clients 10 --rate-per-client 100 --duration 10
```

Produces an independent overarching report combining host system efficiency with volumetric packet totals. 

| Argument             | Default     | Description                       |
|----------------------|-------------|-----------------------------------|
| `--num-clients`      | `5`         | Number of concurrent clients      |
| `--rate-per-client`  | `100`       | Packets per second per client     |
| `--duration`         | `10`        | Test duration in seconds          |
| `--simulate-loss`    | `0.0`       | Percentage packet drop rate       |
