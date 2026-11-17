CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -pthread
LDFLAGS ?= -shared -pthread

# libnuma is optional at runtime in code (best-effort), but link if available.
NUMA_LIBS := $(shell pkg-config --libs numa 2>/dev/null || echo -lnuma)

all: ../libdist_ingest.so

../libdist_ingest.so: dist_ingest.c dist_ingest.h
	$(CC) $(CFLAGS) -o $@ dist_ingest.c $(LDFLAGS) $(NUMA_LIBS)

clean:
	rm -f ../libdist_ingest.so

.PHONY: all clean
