#!/bin/bash

# Compiler Flags
# -O3: Max optimization
# -flto=auto: Link Time Optimization
# -fno-semantic-interposition: Optimize internal calls (skip PLT)
# -fno-strict-aliasing: Safety for memory casting
# -fno-math-errno: Don't set errno for math, allows better vectorization
# -ftree-loop-im: Force Loop Invariant Motion (Explicitly enabled)
# -ftree-loop-ivcanon: Force Induction Variable Canonicalization (Explicitly enabled)
# -fPIC: Required for .so
OPT_FLAGS="-O3 -flto=auto  -fno-strict-aliasing -fno-semantic-interposition -fno-math-errno -ftree-loop-im -ftree-loop-ivcanon -fPIC"
#
# Warning Flags
WARN_FLAGS="-DNDEBUG -Wall -Wextra"

# Linker Flags
# -z now: Resolve symbols at startup (prevents jitter during run)
LINK_FLAGS="-Wl,-z,relro"
#"-Wl,-z,now

# Bash Headers
INCLUDES="-I/usr/include/bash -I/usr/include/bash/include -I/usr/include/bash/builtins"
DEFS="-DSHELL -DHAVE_CONFIG_H"

CFLAGS="$OPT_FLAGS $WARN_FLAGS $LINK_FLAGS $INCLUDES $DEFS -shared"

# 1. Build v2 (Compatibility / Legacy / SSE4.2)
echo "Building v2 (x86-64-v2)..."
gcc forkrun_ring.c $CFLAGS -march=x86-64-v2 -o forkrun_ring_v2.so
strip --strip-unneeded forkrun_ring_v2.so

# 2. Build v3 (Standard / AVX2 / BMI2)
echo "Building v3 (x86-64-v3)..."
gcc forkrun_ring.c $CFLAGS -march=x86-64-v3 -o forkrun_ring_v3.so
strip --strip-unneeded forkrun_ring_v3.so

# 3. Build v4 (Extreme / AVX-512)
echo "Building v4 (x86-64-v4)..."
gcc forkrun_ring.c $CFLAGS -march=x86-64-v4 -o forkrun_ring_v4.so
strip --strip-unneeded forkrun_ring_v4.so

# 4. Build Native (Optimized for THIS machine)
# Note: -march=native implies -mtune=native automatically
echo "Building native..."
gcc forkrun_ring.c $CFLAGS -march=native -mtune=native -o forkrun_ring.so
strip --strip-unneeded forkrun_ring.so

echo "Build complete."
ls -l forkrun_ring*.so


