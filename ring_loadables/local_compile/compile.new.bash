#!/bin/bash

(
# Stop on errors during compilation (optional but recommended)
set -e

# --- 1. COMPILER FLAGS ---
OPT_FLAGS="-O3 -flto=auto -fno-strict-aliasing -fno-semantic-interposition -fno-math-errno -ftree-loop-im -ftree-loop-ivcanon -fPIC"
WARN_FLAGS="-DNDEBUG -Wall -Wextra"
LINK_FLAGS="-Wl,-z,relro"
INCLUDES="-I/usr/include/bash -I/usr/include/bash/include -I/usr/include/bash/builtins"

# --- 2. METADATA & VERSIONING ---
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
META_PATH="$(find "${GIT_ROOT}/ring_loadables" "${GIT_ROOT}" -maxdepth 1 -name 'META' -print -quit)"
FR_VERSION="unknown"
if [[ -f "${META_PATH}" ]]; then
    # Extract version, remove whitespace
    FR_VERSION="$(grep -E '^VERSION:' <"$META_PATH" | sed -E 's/^VERSION:[ \t]*//')"
fi

# Base Definitions
# CRITICAL FIX 1: Closed the quote on COMPILER_FLAGS
DEFS=('-DSHELL' '-DHAVE_CONFIG_H')
DEFS+=('-DBUILD_OS=\"'"$(uname -s)"'\"')
DEFS+=('-DGIT_HASH=\"'"$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"'\"')
DEFS+=('-DCOMPILER_FLAGS=\"'"${OPT_FLAGS// /:}:${WARN_FLAGS// /:}:${LINK_FLAGS// /:}"'\"')
DEFS+=('-DFORKRUN_RING_VERSION=\"'"${FR_VERSION}"'\"')

# --- 3. COMPILATION LOOP ---
# We use a loop to handle the specific -march flags and update BUILD_ARCH dynamically
# so 'ring_version -m' reports the actual target arch (v2/v3/v4) not just the host.

declare -A TARGETS=(["x86-64-v2"]="-march=x86-64-v2" ["x86-64-v3"]="-march=x86-64-v3" ["x86-64-v4"]="-march=x86-64-v4" ["native"]="-march=native -mtune=native")

# CRITICAL FIX 2: CFLAGS must be constructed INSIDE the loop or AFTER DEFS are finalized.
# If you define CFLAGS before adding the version to DEFS, the version won't exist in CFLAGS.

for arch_name in "${!TARGETS[@]}"; do
    arch_flags="${TARGETS[$arch_name]}"
    output_name="forkrun_ring.${arch_name}.so"

    echo "Building ${arch_name} (${arch_flags})..."
    
    # Inject specific architecture name into the binary metadata
    ARCH_DEF='-DBUILD_ARCH=\"'"${arch_name}"'\"'

    # Compile
    # We deliberately don't quote $DEFS here to allow word splitting of flags
eval "gcc forkrun_ring.c $OPT_FLAGS $WARN_FLAGS $LINK_FLAGS $INCLUDES ${DEFS[@]} $ARCH_DEF -shared $arch_flags -o $output_name"

    strip --strip-unneeded "$output_name"
done

echo "Builds complete."
ls -l forkrun_ring*.so

# --- 4. BASH WRAPPER INJECTION ---
echo "Injecting into frun.bash..."

# Relax error checking for the parsing logic
set +e

a0=''
a1=''

# Read frun.bash to split it
# NOTE: This logic assumes 'frun.bash' exists in the current directory
{
    IFS=
    # Read until the function definition
    while true; do
        read -r -u $fd_r a
        if [[ "$a" == '_forkrun_file_to_base64() {'* ]]; then
            a1+="${a}"$'\n'
            break
        else
            a0+="${a}"$'\n'
        fi
    done

    # Read the rest until the marker
    while true; do
        read -r -u $fd_r a
        a1+="${a}"$'\n'
        [[ "$a" == '# <@@@@@< _BASE64_START_ >@@@@@> #'* ]] && break
    done    
} {fd_r}<./frun.bash

# Load the helper function into current scope so we can use it
eval "${a1}"

# Clear existing array
unset b64
declare -A b64

# Generate Base64 for all compiled binaries
for f in forkrun_ring.*.so; do
    [[ -f "$f" ]] || continue
    # Extract key: forkrun_ring.x86_64-v3.so -> x86_64-v3
    # Note: Your logic used "x86_64-v3", but standard implies dashes "x86-64-v3". 
    # Adjusting logic to grab everything between "forkrun_ring." and ".so"
    key="${f#forkrun_ring.}"
    key="${key%.so}"
    
    # Map gcc's "x86-64-v3" to bash array key "x86_64-v3" if necessary for the wrapper
    # (Assuming your wrapper expects underscores)
    key="${key//-/_}" 
    # Fix for "native": map native build to host arch (e.g., x86_64)? 
    # Or keep "native" key? Keeping native key based on your loop.
    [[ "$key" == "native" ]] && key="native" 

    echo "Encoding $f as b64[$key]..."
    b64[${key}]="$(_forkrun_file_to_base64 "$f")"
done
  
# Write new file
{
    printf '%s\n%s' "$a0" "$a1"
    declare -p b64
    printf '\n\n_forkrun_bootstrap_setup --force\n\n'
} >./frun.new.bash

chmod +x ./frun.new.bash
echo "Done. Generated frun.new.bash"

)
