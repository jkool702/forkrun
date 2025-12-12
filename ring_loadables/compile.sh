#!/bin/bash

# Common Flags
CFLAGS="-shared -fPIC -O3 -flto=auto -DNDEBUG -Wall -Wextra -funroll-loops  -ftree-loop-ivcanon   -ftree-loop-im  -ftree-vectorize -fno-strict-aliasing -DSHELL -DHAVE_CONFIG_H"
INCLUDES="-I/usr/include/bash -I/usr/include/bash/include -I/usr/include/bash/builtins"
# 1. Build v2 (Compatibility / Legacy)
echo "Building v2 (SSE4.2)..."
gcc forkrun_ring.c $CFLAGS $INCLUDES -march=x86-64-v2 -o forkrun_ring_v2.so
strip --strip-all forkrun_ring_v2.so
# 2. Build v3 (Standard / AVX2)
echo "Building v3 (AVX2)..."
gcc forkrun_ring.c $CFLAGS $INCLUDES -march=x86-64-v3 -o forkrun_ring_v3.so
strip --strip-all forkrun_ring_v3.so
# 3. Build v4 (Extreme / AVX-512)
echo "Building v4 (AVX-512)..."
gcc forkrun_ring.c $CFLAGS $INCLUDES -march=x86-64-v4 -o forkrun_ring_v4.so
strip --strip-all forkrun_ring_v4.so
echo "Building native (AVX-512)..."
gcc forkrun_ring.c $CFLAGS $INCLUDES -march=native -o forkrun_ring.so
strip --strip-all forkrun_ring.so
echo "Build complete."
ls -lh forkrun_ring*.so
