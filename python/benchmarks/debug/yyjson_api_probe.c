/* yyjson API semantics probe (W-PY31 session).
 *
 * Empirically pins down vendored-yyjson behaviors the plugin relies
 * on: duplicate keys (obj_get returns FIRST), trailing garbage
 * (rejected), truncation (rejected), uint64 max (is_uint exact),
 * negatives (is_int). Build: gcc -O2 -I<repo>/python/benchmarks/
 * plugins yyjson_api_probe.c <repo>/python/benchmarks/plugins/
 * yyjson.c -lm
 */
#include <stdio.h>
#include <string.h>
#include "yyjson.h"
int main(void) {
    yyjson_read_err err;
    /* duplicate keys: which wins? */
    const char *dup = "{\"a\":1,\"a\":2}";
    yyjson_doc *d = yyjson_read_opts((char*)dup, strlen(dup), 0, NULL, &err);
    yyjson_val *r = yyjson_doc_get_root(d);
    printf("dup a=%lld\n", (long long)yyjson_get_int(yyjson_obj_get(r, "a")));
    yyjson_doc_free(d);
    /* trailing garbage */
    const char *trail = "{\"a\":1} xyz";
    d = yyjson_read_opts((char*)trail, strlen(trail), 0, NULL, &err);
    printf("trail doc=%p code=%u\n", (void*)d, d ? 0 : err.code);
    if (d) yyjson_doc_free(d);
    /* truncated */
    const char *tr = "{\"a\":1,\"b\":";
    d = yyjson_read_opts((char*)tr, strlen(tr), 0, NULL, &err);
    printf("trunc doc=%p\n", (void*)d);
    if (d) yyjson_doc_free(d);
    /* big uint64 */
    const char *big = "{\"ts\":18446744073709551615}";
    d = yyjson_read_opts((char*)big, strlen(big), 0, NULL, &err);
    r = yyjson_doc_get_root(d);
    yyjson_val *v = yyjson_obj_get(r, "ts");
    printf("big is_uint=%d val=%llu\n", yyjson_is_uint(v), (unsigned long long)yyjson_get_uint(v));
    yyjson_doc_free(d);
    /* negative */
    const char *neg = "{\"ts\":-5}";
    d = yyjson_read_opts((char*)neg, strlen(neg), 0, NULL, &err);
    r = yyjson_doc_get_root(d);
    v = yyjson_obj_get(r, "ts");
    printf("neg is_int=%d val=%lld\n", yyjson_is_int(v), (long long)yyjson_get_int(v));
    yyjson_doc_free(d);
    return 0;
}
