# Telemetry Collection and Aggregation System

A UDP-based distributed telemetry system where multiple Python clients continuously send telemetry data to a high-performance C server. The server tracks packet sequences, detects losses, aggregates metrics, and produces periodic reports.

## Architecture

```
┌─────────────┐           ┌──────────────────────────┐
│  Client 1   │──── UDP──►│                          │
│  (Python)   │           │   Telemetry Server (C)   │
├─────────────┤           │                          │
│  Client 2   │──── UDP──►│  • Packet Ingestion      │
│  (Python)   │           │  • Sequence Tracking     │
├─────────────┤           │  • Loss Detection        │
│  Client N   │──── UDP──►│  • Metric Aggregation    │
│  (Python)   │           │  • Periodic Reporting    │
└─────────────┘           └──────────────────────────┘
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
| `server.c`     | C        | UDP telemetry collection server          |
| `client.py`    | Python   | Telemetry sender client                  |
| `load_test.py` | Python   | Multi-client scalability/stress test     |
| `Makefile`     | Make     | Build system for the server              |

## Building

### Prerequisites
- **GCC** (MinGW on Windows, or any C compiler)
- **Python 3.6+**

### Compile the server

```bash
# Using Make
make

# Or manually on Windows
gcc -Wall -Wextra -O2 -o server.exe server.c -lws2_32

# On Linux/Mac
gcc -Wall -Wextra -O2 -o server server.c
```

## Usage

### 1. Start the Server

```bash
# Default port 8888
./server.exe

# Custom port
./server.exe 9000
```

The server will print a periodic report every 5 seconds showing:
- Per-client: packets received, lost, loss rate, ingestion rate
- Per-client per-metric: average, min, max values
- Global: total packets, aggregate loss rate

Press **Ctrl+C** to stop and print the final summary.

### 2. Run a Single Client

```bash
python client.py --server-ip 127.0.0.1 --server-port 8888 --client-id 1 --rate 100 --duration 10
```

| Argument        | Default     | Description                                   |
|-----------------|-------------|-----------------------------------------------|
| `--server-ip`   | `127.0.0.1` | Server IP address                             |
| `--server-port` | `8888`      | Server UDP port                               |
| `--client-id`   | `1`         | Unique client identifier                      |
| `--rate`        | `100`       | Packets per second                            |
| `--duration`    | `10`        | Sending duration (seconds), 0 = infinite      |

### 3. Run the Load Test

```bash
python load_test.py --num-clients 10 --rate-per-client 100 --duration 10
```

| Argument             | Default     | Description                       |
|----------------------|-------------|-----------------------------------|
| `--num-clients`      | `5`         | Number of concurrent clients      |
| `--rate-per-client`  | `100`       | Packets per second per client     |
| `--duration`         | `10`        | Test duration in seconds          |
| `--server-ip`        | `127.0.0.1` | Server IP                         |
| `--server-port`      | `8888`      | Server port                       |

## Example Output

### Server Periodic Report
```
═══════════════════════════════════════════════════════════════
  PERIODIC TELEMETRY REPORT  (10s elapsed)
═══════════════════════════════════════════════════════════════

  ┌─ Client 1
  │  Packets received : 998
  │  Packets lost     : 2
  │  Loss rate        : 0.20%
  │  Ingestion rate   : 99.8 pkts/sec
  │
  │  CPU (%)          : avg=44.72  min=1.23  max=89.45  (n=251)
  │  Memory (%)       : avg=59.81  min=22.10  max=95.33  (n=248)
  │  Disk (%)         : avg=50.12  min=28.44  max=72.88  (n=250)
  │  Network (Mbps)   : avg=198.55  min=12.30  max=445.21  (n=249)
  └─

  GLOBAL SUMMARY
  ─────────────────────────────────────
  Active clients     : 1
  Total packets recv : 998
  Total packets lost : 2
  Aggregate loss %   : 0.20%
  Overall rate       : 99.8 pkts/sec
═══════════════════════════════════════════════════════════════
```

## Metric Types

| Type | Name         | Range        | Distribution          |
|------|--------------|--------------|-----------------------|
| 0    | CPU          | 0–100 %      | Gaussian(μ=45, σ=20)  |
| 1    | Memory       | 0–100 %      | Gaussian(μ=60, σ=15)  |
| 2    | Disk         | 0–100 %      | Gaussian(μ=50, σ=10)  |
| 3    | Network      | 0–1000 Mbps  | Gaussian(μ=200, σ=100)|

## Testing Scenarios

1. **Single client, low rate**: `python client.py --rate 10 --duration 30` — verify basic functionality
2. **Single client, high rate**: `python client.py --rate 1000 --duration 10` — measure server capacity
3. **Multi-client scalability**: `python load_test.py --num-clients 20 --rate-per-client 100 --duration 15`
4. **Stress test**: `python load_test.py --num-clients 50 --rate-per-client 200 --duration 10`
