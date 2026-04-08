# Telemetry Collection and Aggregation System — Makefile
# Supports both Windows (MinGW/GCC) and Linux/Mac

CC      = gcc
CFLAGS  = -Wall -Wextra -O2
TARGET  = server

# Detect Windows
ifdef OS
    # Windows
    LDFLAGS = -lws2_32
    EXT     = .exe
    RM      = del /Q
else
    # Linux / Mac
    LDFLAGS =
    EXT     =
    RM      = rm -f
endif

.PHONY: all run run-client run-loadtest help

all: 
	@echo "Nothing to compile for Python server. Use 'make run' to start."

run:
	python server.py

run-client:
	python client.py --server-ip 127.0.0.1 --server-port 8888 --client-id 1 --rate 100 --duration 10

run-loadtest:
	python load_test.py --num-clients 5 --rate-per-client 100 --duration 10

help:
	@echo "Targets:"
	@echo "  run           Run the Python server"
	@echo "  run-client    Run a single telemetry client"
	@echo "  run-loadtest  Run the load test with 5 clients"
	@echo "  help          Show this help message"
