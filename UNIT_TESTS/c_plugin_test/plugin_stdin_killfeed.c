#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <signal.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"
int forkrun_use_ctx = 2;
static void kill_feeder_child(void) {
    pid_t me = getpid();
    DIR *d = opendir("/proc");
    if (!d) return;
    struct dirent *e;
    while ((e = readdir(d)) != NULL) {
        pid_t pid = (pid_t)atoi(e->d_name);
        if (pid <= 1 || pid == me) continue;
        char path[64];
        snprintf(path, sizeof(path), "/proc/%d/stat", (int)pid);
        FILE *f = fopen(path, "r");
        if (!f) continue;
        char buf[1024];
        size_t n = fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
        if (n == 0) continue;
        buf[n] = '\0';
        char *rp = strrchr(buf, ')');
        if (!rp) continue;
        int ppid = 0;
        if (sscanf(rp + 1, " %*c %d", &ppid) != 1) continue;
        if (ppid == (int)me) {
            if (kill(pid, SIGKILL) == 0)
                fprintf(stderr, "INJECT ok\n");
        }
    }
    closedir(d);
}
int plugin_stdin_killfeed(int argc, char **argv, const struct forkrun_ctx *ctx) {
    (void)argc; (void)argv;
    if (ctx->num_kills == 0) {
        kill_feeder_child();
    } else {
        fprintf(stderr, "RETRY batch=%lu kills=%u\n",
                (unsigned long)ctx->batch_index, ctx->num_kills);
    }
    size_t want = (size_t)ctx->batch_byte_length;
    size_t got = 0;
    char buf[65536];
    while (got < want) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) return 1;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
        got += (size_t)n;
    }
    return 0;
}
