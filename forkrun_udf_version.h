#ifndef FORKRUN_UDF_VERSION_H
#define FORKRUN_UDF_VERSION_H

/* The build stamp the cleanroom launcher checks before it will
 * initialise an interpreter with a UDF helper.
 *
 * WHY THIS IS A STRUCT AND NOT A PY_VERSION_HEX
 *
 * An earlier revision returned PY_VERSION_HEX from the helper and had the
 * caller declare its own version as "--caller-version=MAJOR.MINOR". The
 * launcher then packed the declared pair as major<<16|minor while
 * extracting the helper's as (hex>>16)&0xffff -- which is major<<8|minor.
 * The two sides therefore represented the same concept DIFFERENTLY, and
 * a MATCHING 3.14/3.14 pair compared unequal: every correct call was
 * refused with "version mismatch".
 *
 * The bug failed safe rather than open, which is worse for detection: it
 * looked like a working barrier that happened to reject everything. Two
 * typed integer fields remove the packing convention entirely -- there is
 * nothing left to pack differently.
 *
 * Deliberately an out-parameter rather than a by-value struct return:
 * struct-return ABI is platform-defined, and an out-parameter keeps this
 * header correct on any target without both sides agreeing about it. */

struct fr_udf_version {
    int major;
    int minor;
};

/* Symbol exported by the UDF helper. Fills *out and returns.
 * A helper that does not export it is REFUSED, not assumed compatible. */
#define FR_UDF_BUILT_VERSION_SYMBOL "fr_udf_built_version"
typedef void (*fr_udf_built_version_fn)(struct fr_udf_version *out);

#endif /* FORKRUN_UDF_VERSION_H */
