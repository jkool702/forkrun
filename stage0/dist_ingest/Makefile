CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -pthread
LDFLAGS ?= -shared -pthread

# CK-1: mbind/set_mempolicy/get_mempolicy now go through the Linux syscall
# interface (SYS_mbind/SYS_set_mempolicy/SYS_get_mempolicy with
# __NR_* fallbacks) — the libnuma-dev package is NOT required to build.
# libnuma is still linked when present for best-effort fallbacks.
NUMA_LIBS := $(shell pkg-config --libs numa 2>/dev/null || true)

all: ../libdist_ingest.so

../libdist_ingest.so: dist_ingest.c dist_ingest.h
	$(CC) $(CFLAGS) -o $@ dist_ingest.c $(LDFLAGS) $(NUMA_LIBS)

clean:
	rm -f ../libdist_ingest.so

.PHONY: all clean
