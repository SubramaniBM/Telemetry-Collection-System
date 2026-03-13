/*
 * Telemetry Collection and Aggregation Server
 * 
 * A high-performance UDP server that receives telemetry data from
 * multiple distributed clients, tracks packet sequences, detects
 * losses, and aggregates metrics with periodic reporting.
 *
 * Protocol: 21-byte binary packets
 *   [client_id:4][seq_num:4][timestamp:8][metric_type:1][metric_value:4]
 *
 * Compile: gcc -o server.exe server.c -lws2_32  (Windows)
 *          gcc -o server server.c                (Linux/Mac)
 * Usage:   ./server [port]   (default port: 8888)
 */

#ifdef _WIN32
    #define _WINSOCK_DEPRECATED_NO_WARNINGS
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")
    typedef int socklen_t;
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <unistd.h>
    #include <fcntl.h>
    #define SOCKET int
    #define INVALID_SOCKET -1
    #define SOCKET_ERROR -1
    #define closesocket close
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <time.h>
#include <float.h>
#include <math.h>
#include <stdint.h>

/* ─── Configuration ─────────────────────────────────────────────── */
#define DEFAULT_PORT        8888
#define MAX_CLIENTS         256
#define PACKET_SIZE         21
#define REPORT_INTERVAL_SEC 5
#define METRIC_TYPES        4

/* ─── Metric type names ─────────────────────────────────────────── */
static const char *METRIC_NAMES[METRIC_TYPES] = {
    "CPU (%)", "Memory (%)", "Disk (%)", "Network (Mbps)"
};

/* ─── Per-metric statistics ─────────────────────────────────────── */
typedef struct {
    double   sum;
    double   min_val;
    double   max_val;
    uint32_t count;
} MetricStats;

/* ─── Per-client tracking structure ─────────────────────────────── */
typedef struct {
    int      active;               /* Has this slot been used?       */
    uint32_t client_id;            /* Actual client ID               */
    uint32_t expected_seq;         /* Next expected sequence number   */
    uint32_t packets_received;     /* Total packets received          */
    uint32_t packets_lost;         /* Total detected lost packets     */
    double   first_timestamp;      /* Timestamp of first packet       */
    double   last_timestamp;       /* Timestamp of most recent packet */
    MetricStats metrics[METRIC_TYPES]; /* Per-metric aggregation      */
} ClientState;

/* ─── Globals ───────────────────────────────────────────────────── */
static volatile int g_running = 1;
static ClientState  g_clients[MAX_CLIENTS];
static uint32_t     g_total_packets   = 0;
static uint32_t     g_total_lost      = 0;
static time_t       g_last_report;
static time_t       g_server_start;

/* ─── Signal handler for graceful shutdown ──────────────────────── */
static void handle_sigint(int sig) {
    (void)sig;
    g_running = 0;
}

/* ─── Find or allocate a client slot ────────────────────────────── */
static int find_client_slot(uint32_t client_id) {
    int hash = client_id % MAX_CLIENTS;
    int start = hash;
    
    /* Linear probing */
    do {
        if (!g_clients[hash].active) {
            /* Empty slot — initialize for new client */
            memset(&g_clients[hash], 0, sizeof(ClientState));
            g_clients[hash].active    = 1;
            g_clients[hash].client_id = client_id;
            g_clients[hash].expected_seq = 0;
            for (int m = 0; m < METRIC_TYPES; m++) {
                g_clients[hash].metrics[m].min_val = DBL_MAX;
                g_clients[hash].metrics[m].max_val = -DBL_MAX;
            }
            return hash;
        }
        if (g_clients[hash].client_id == client_id) {
            return hash;
        }
        hash = (hash + 1) % MAX_CLIENTS;
    } while (hash != start);
    
    return -1; /* Table full */
}

/* ─── Print a separator line ────────────────────────────────────── */
static void print_separator(void) {
    printf("═══════════════════════════════════════════════════════════════\n");
}

/* ─── Print periodic report ─────────────────────────────────────── */
static void print_report(int is_final) {
    time_t now = time(NULL);
    double elapsed = difftime(now, g_server_start);
    
    printf("\n");
    print_separator();
    if (is_final)
        printf("  FINAL TELEMETRY REPORT\n");
    else
        printf("  PERIODIC TELEMETRY REPORT  (%.0fs elapsed)\n", elapsed);
    print_separator();
    
    int active_clients = 0;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (!g_clients[i].active) continue;
        active_clients++;
        
        ClientState *c = &g_clients[i];
        double duration = c->last_timestamp - c->first_timestamp;
        double rate = (duration > 0.0) ? c->packets_received / duration : 0.0;
        double loss_pct = 0.0;
        uint32_t total_expected = c->packets_received + c->packets_lost;
        if (total_expected > 0)
            loss_pct = 100.0 * c->packets_lost / total_expected;
        
        printf("\n  ┌─ Client %u\n", c->client_id);
        printf("  │  Packets received : %u\n", c->packets_received);
        printf("  │  Packets lost     : %u\n", c->packets_lost);
        printf("  │  Loss rate        : %.2f%%\n", loss_pct);
        printf("  │  Ingestion rate   : %.1f pkts/sec\n", rate);
        printf("  │\n");
        
        for (int m = 0; m < METRIC_TYPES; m++) {
            if (c->metrics[m].count == 0) continue;
            double avg = c->metrics[m].sum / c->metrics[m].count;
            printf("  │  %-16s : avg=%.2f  min=%.2f  max=%.2f  (n=%u)\n",
                   METRIC_NAMES[m], avg, c->metrics[m].min_val,
                   c->metrics[m].max_val, c->metrics[m].count);
        }
        printf("  └─\n");
    }
    
    printf("\n  GLOBAL SUMMARY\n");
    printf("  ─────────────────────────────────────\n");
    printf("  Active clients     : %d\n", active_clients);
    printf("  Total packets recv : %u\n", g_total_packets);
    printf("  Total packets lost : %u\n", g_total_lost);
    if (g_total_packets + g_total_lost > 0)
        printf("  Aggregate loss %%   : %.2f%%\n",
               100.0 * g_total_lost / (g_total_packets + g_total_lost));
    if (elapsed > 0)
        printf("  Overall rate       : %.1f pkts/sec\n", g_total_packets / elapsed);
    print_separator();
    printf("\n");
}

/* ─── Parse and process one packet ──────────────────────────────── */
static void process_packet(const unsigned char *buf, int len) {
    if (len < PACKET_SIZE) {
        fprintf(stderr, "[WARN] Received undersized packet (%d bytes), ignoring.\n", len);
        return;
    }
    
    /* Unpack fields (little-endian assumed, matching Python struct '<') */
    uint32_t client_id, seq_num;
    double   timestamp;
    uint8_t  metric_type;
    float    metric_value;
    
    memcpy(&client_id,    buf + 0,  4);
    memcpy(&seq_num,      buf + 4,  4);
    memcpy(&timestamp,    buf + 8,  8);
    memcpy(&metric_type,  buf + 16, 1);
    memcpy(&metric_value, buf + 17, 4);
    
    if (metric_type >= METRIC_TYPES) {
        fprintf(stderr, "[WARN] Invalid metric_type %u from client %u, ignoring.\n",
                metric_type, client_id);
        return;
    }
    
    int slot = find_client_slot(client_id);
    if (slot < 0) {
        fprintf(stderr, "[WARN] Client table full, dropping packet from client %u.\n",
                client_id);
        return;
    }
    
    ClientState *c = &g_clients[slot];
    
    /* Sequence tracking and loss detection */
    if (c->packets_received == 0) {
        /* First packet from this client */
        c->expected_seq    = seq_num + 1;
        c->first_timestamp = timestamp;
    } else {
        if (seq_num > c->expected_seq) {
            /* Gap detected — packets were lost */
            uint32_t lost = seq_num - c->expected_seq;
            c->packets_lost += lost;
            g_total_lost    += lost;
        }
        c->expected_seq = seq_num + 1;
    }
    
    /* Update counters */
    c->packets_received++;
    c->last_timestamp = timestamp;
    g_total_packets++;
    
    /* Aggregate metric */
    MetricStats *ms = &c->metrics[metric_type];
    ms->sum += metric_value;
    ms->count++;
    if (metric_value < ms->min_val) ms->min_val = metric_value;
    if (metric_value > ms->max_val) ms->max_val = metric_value;
}

/* ─── Main ──────────────────────────────────────────────────────── */
int main(int argc, char *argv[]) {
    int port = DEFAULT_PORT;
    if (argc > 1) {
        port = atoi(argv[1]);
        if (port <= 0 || port > 65535) {
            fprintf(stderr, "Invalid port: %s\n", argv[1]);
            return 1;
        }
    }
    
#ifdef _WIN32
    /* Initialize Winsock */
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
        fprintf(stderr, "WSAStartup failed: %d\n", WSAGetLastError());
        return 1;
    }
#endif
    
    /* Register signal handler */
    signal(SIGINT, handle_sigint);
    
    /* Create UDP socket */
    SOCKET sockfd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (sockfd == INVALID_SOCKET) {
        fprintf(stderr, "Failed to create socket.\n");
#ifdef _WIN32
        WSACleanup();
#endif
        return 1;
    }
    
    /* Allow address reuse */
    int optval = 1;
    setsockopt(sockfd, SOL_SOCKET, SO_REUSEADDR, (const char *)&optval, sizeof(optval));
    
    /* Increase receive buffer for high-rate ingestion */
    int rcvbuf = 4 * 1024 * 1024;  /* 4 MB */
    setsockopt(sockfd, SOL_SOCKET, SO_RCVBUF, (const char *)&rcvbuf, sizeof(rcvbuf));
    
    /* Bind */
    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family      = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_ANY);
    server_addr.sin_port        = htons((unsigned short)port);
    
    if (bind(sockfd, (struct sockaddr *)&server_addr, sizeof(server_addr)) == SOCKET_ERROR) {
        fprintf(stderr, "Bind failed on port %d.\n", port);
        closesocket(sockfd);
#ifdef _WIN32
        WSACleanup();
#endif
        return 1;
    }
    
    /* Set non-blocking mode for periodic reporting */
#ifdef _WIN32
    u_long mode = 1;
    ioctlsocket(sockfd, FIONBIO, &mode);
#else
    {
        int flags = fcntl(sockfd, F_GETFL, 0);
        fcntl(sockfd, F_SETFL, flags | O_NONBLOCK);
    }
#endif
    
    /* Initialize client table */
    memset(g_clients, 0, sizeof(g_clients));
    g_server_start = time(NULL);
    g_last_report  = g_server_start;
    
    printf("\n");
    print_separator();
    printf("  TELEMETRY COLLECTION SERVER\n");
    printf("  Listening on 0.0.0.0:%d (UDP)\n", port);
    printf("  Max clients: %d | Report interval: %ds\n", MAX_CLIENTS, REPORT_INTERVAL_SEC);
    printf("  Press Ctrl+C to stop and print final report.\n");
    print_separator();
    printf("\n");
    
    /* ─── Main ingestion loop ───────────────────────────────────── */
    unsigned char buf[256];
    struct sockaddr_in client_addr;
    socklen_t addr_len;
    
    while (g_running) {
        addr_len = sizeof(client_addr);
        int n = recvfrom(sockfd, (char *)buf, sizeof(buf), 0,
                         (struct sockaddr *)&client_addr, &addr_len);
        
        if (n > 0) {
            process_packet(buf, n);
        } else {
            /* No data available (non-blocking). Brief sleep to avoid CPU spin. */
#ifdef _WIN32
            Sleep(1);  /* 1 ms */
#else
            usleep(1000);
#endif
        }
        
        /* Periodic report check */
        time_t now = time(NULL);
        if (difftime(now, g_last_report) >= REPORT_INTERVAL_SEC) {
            print_report(0);
            g_last_report = now;
        }
    }
    
    /* ─── Final report on shutdown ──────────────────────────────── */
    printf("\n[INFO] Shutting down...\n");
    print_report(1);
    
    closesocket(sockfd);
#ifdef _WIN32
    WSACleanup();
#endif
    
    return 0;
}
