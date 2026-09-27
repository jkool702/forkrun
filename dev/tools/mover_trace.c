/* W-MOVER syscall tracer: log positional ops on forkrun memfds.
 * Interposes libc IO; logs only when the fd target is a memfd.
 * Env: MOVER_TRACE=1 enables; MOVER_TRACE_FILE=path (required).
 * Async-careful: raw write() to a pre-opened log fd, no stdio,
 * no malloc on the hot path (single caller PC via builtin). */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

static int g_on = -1;
static int g_log = -1;
static unsigned long g_dev = 0;
static unsigned long g_ino = 0;
static int g_maps_done = 0;
static unsigned long g_libbase = 0;
static int g_enhanced = 0;
#ifndef EVFD_ARR_OFF
#define EVFD_ARR_OFF 0
#endif
#ifndef NNODES_OFF
#define NNODES_OFF 0
#endif

static ssize_t (*r_read)(int, void *, size_t) = 0;
static ssize_t (*r_write)(int, const void *, size_t) = 0;
static off_t (*r_lseek)(int, off_t, int) = 0;
static ssize_t (*r_pread)(int, void *, size_t, off_t) = 0;
static ssize_t (*r_pwrite)(int, const void *, size_t, off_t) = 0;
static ssize_t (*r_sendfile)(int, int, off_t *, size_t) = 0;
static ssize_t (*r_splice)(int, loff_t *, int, loff_t *, size_t,
                            unsigned) = 0;
static ssize_t (*r_cfr)(int, loff_t *, int, loff_t *, size_t,
                         unsigned) = 0;
static int (*r_memfd)(const char *, unsigned) = 0;

/* Dump own mapping bases once per process image (fork inherits the
 * flag + the slide; exec resets both and re-dumps). Lets post-hoc
 * addr2line resolve caller PCs despite ASLR. */
static void dump_maps(void) {
    int mfd;
    char buf[4096];
    ssize_t r;
    size_t carry = 0;
    if (g_maps_done)
        return;
    g_maps_done = 1;
    if (!r_read)
        return;
    mfd = open("/proc/self/maps", O_RDONLY);
    if (mfd < 0)
        return;
    while ((r = r_read(mfd, buf + carry, sizeof(buf) - 1 - carry)) > 0) {
        size_t total = carry + (size_t)r, start = 0, i;
        buf[total] = 0;
        for (i = 0; i < total; i++) {
            if (buf[i] == '\n') {
                buf[i] = 0;
                /* keep libforkrun + python binary r-xp lines only */
                int keep = 0, k;
                const char *a = "libforkrun", *b = "bin/python";
                for (k = 0; buf[start + k] && a[k]; k++)
                    ;
                /* substring search, no strstr (keep it lean) */
                {
                    size_t ln = i - start, q;
                    size_t al = 0;
                    while (a[al])
                        al++;
                    size_t bl = 0;
                    while (b[bl])
                        bl++;
                    for (q = start; q + al <= i && !keep; q++) {
                        size_t t;
                        for (t = 0; t < al; t++)
                            if (buf[q + t] != a[t])
                                break;
                        if (t == al)
                            keep = 1;
                    }
                    for (q = start; q + bl <= i && !keep; q++) {
                        size_t t;
                        for (t = 0; t < bl; t++)
                            if (buf[q + t] != b[t])
                                break;
                        if (t == bl)
                            keep = 1;
                    }
                    (void)ln;
                }
                if (keep) {
                    /* capture libforkrun r-xp offset-0 base for
                     * post-hoc PC resolution + array reads */
                    {
                        size_t q = start, dash = 0, sp = 0;
                        unsigned long base = 0;
                        int is_rx = 0, is_zoff = 0, is_fr = 0, k3;
                        const char *fr = "libforkrun";
                        size_t fl = 10, t3;
                        for (t3 = start; t3 + fl <= i && !is_fr; t3++) {
                            size_t u;
                            for (u = 0; u < fl; u++)
                                if (buf[t3 + u] != fr[u])
                                    break;
                            if (u == fl)
                                is_fr = 1;
                        }
                        if (!is_fr)
                            goto skipbase;
                        for (k3 = (int)start; k3 < (int)i; k3++) {
                            if (buf[k3] == '-' && !dash)
                                dash = (size_t)k3;
                            if (buf[k3] == ' ' && !sp)
                                sp = (size_t)k3;
                        }
                        /* start addr hex */
                        {
                            size_t k4;
                            for (k4 = start; k4 < dash; k4++) {
                                char c = buf[k4];
                                int v = (c >= '0' && c <= '9') ? c - '0' :
                                        (c >= 'a' && c <= 'f')
                                        ? c - 'a' + 10 : -1;
                                if (v < 0)
                                    break;
                                base = (base << 4) | (unsigned)v;
                            }
                        }
                        /* perms field sits after the first space:
                         * "<start>-<end> r-xp <offset> ...". */
                        {
                            size_t k4 = sp + 1;
                            if (k4 + 3 < (size_t)i &&
                                buf[k4] == 'r' && buf[k4 + 1] == '-' &&
                                buf[k4 + 2] == 'x' && buf[k4 + 3] == 'p')
                                is_rx = 1;
                            /* offset follows perms + space */
                            k4 += 4;
                            while (k4 < (size_t)i && buf[k4] == ' ')
                                k4++;
                            if (k4 + 8 <= (size_t)i) {
                                size_t k5;
                                is_zoff = 1;
                                for (k5 = 0; k5 < 8; k5++)
                                    if (buf[k4 + k5] != '0')
                                        is_zoff = 0;
                            }
                        }
                        if (is_rx && is_zoff && g_libbase == 0)
                            g_libbase = base;
                    }
                skipbase:;
                    char hdr[64];
                    int hn = 0, k2;
                    long pid = getpid();
                    const char *h = "MAPS p=";
                    for (k2 = 0; h[k2]; k2++)
                        hdr[hn++] = h[k2];
                    /* pid decimal */
                    char pb[24];
                    int pn = 0;
                    if (pid == 0)
                        pb[pn++] = '0';
                    else {
                        char rb[24];
                        int rn = 0;
                        while (pid > 0 && rn < 23) {
                            rb[rn++] = '0' + (pid % 10);
                            pid /= 10;
                        }
                        while (rn > 0)
                            pb[pn++] = rb[--rn];
                    }
                    for (k2 = 0; k2 < pn; k2++)
                        hdr[hn++] = pb[k2];
                    hdr[hn++] = ' ';
                    (void)!write(g_log, hdr, (size_t)hn);
                    (void)!write(g_log, buf + start,
                                 (size_t)(i - start));
                    (void)!write(g_log, "\n", 1);
                }
                start = i + 1;
            }
        }
        carry = total - start;
        /* move leftover partial line to front */
        {
            size_t k;
            for (k = 0; k < carry; k++)
                buf[k] = buf[start + k];
        }
        if (carry >= sizeof(buf) - 1)
            break;
    }
    close(mfd);
}
/* Re-validate g_log (fork children scrub it; fd reuse would
 * otherwise hijack the number). Reopens on mismatch. */
static void log_check(void) {
    struct stat st;
    const char *f;
    if (g_on != 1 || g_log < 0)
        return;
    if (fstat(g_log, &st) == 0 && (unsigned long)st.st_dev == g_dev &&
        (unsigned long)st.st_ino == g_ino)
        return;
    f = getenv("MOVER_TRACE_FILE");
    if (!f)
        return;
    int nfd = open(f, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (nfd < 0)
        return;
    if (fstat(nfd, &st) == 0) {
        g_log = nfd;
        g_dev = (unsigned long)st.st_dev;
        g_ino = (unsigned long)st.st_ino;
    } else {
        close(nfd);
    }
}

static void init_once(void) {
    if (g_on != -1)
        return;
    const char *e = getenv("MOVER_TRACE");
    const char *f = getenv("MOVER_TRACE_FILE");
    struct stat st;
    g_on = 0;
    if (!e || e[0] != '1' || !f)
        return;
    g_log = open(f, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
    if (g_log < 0)
        return;
    if (fstat(g_log, &st) != 0) {
        close(g_log);
        g_log = -1;
        return;
    }
    g_dev = (unsigned long)st.st_dev;
    g_ino = (unsigned long)st.st_ino;
    r_read = dlsym(RTLD_NEXT, "read");
    r_write = dlsym(RTLD_NEXT, "write");
    r_lseek = dlsym(RTLD_NEXT, "lseek");
    r_pread = dlsym(RTLD_NEXT, "pread");
    r_pwrite = dlsym(RTLD_NEXT, "pwrite");
    r_sendfile = dlsym(RTLD_NEXT, "sendfile");
    r_splice = dlsym(RTLD_NEXT, "splice");
    r_cfr = dlsym(RTLD_NEXT, "copy_file_range");
    r_memfd = dlsym(RTLD_NEXT, "memfd_create");
    g_on = 1;
}

/* Returns 1 + fills name when fd is a memfd. No malloc. */
static int memfd_name(int fd, char *out, size_t outsz) {
    char path[64];
    char link[256];
    int n, i, j;
    if (g_on != 1)
        return 0;
    n = 0;
    /* build /proc/self/fd/N without snprintf (avoid stdio) */
    const char *pre = "/proc/self/fd/";
    for (i = 0; pre[i] && n < 60; i++)
        path[n++] = pre[i];
    char num[16];
    int nn = 0, tmp = fd, started = 0;
    if (tmp == 0)
        num[nn++] = '0';
    else {
        char rev[16];
        int rn = 0;
        while (tmp > 0 && rn < 15) {
            rev[rn++] = '0' + (tmp % 10);
            tmp /= 10;
        }
        while (rn > 0)
            num[nn++] = rev[--rn];
        started = 1;
        (void)started;
    }
    for (i = 0; i < nn && n < 60; i++)
        path[n++] = num[i];
    path[n] = 0;
    ssize_t lr = readlink(path, link, sizeof(link) - 1);
    if (lr <= 0)
        return 0;
    link[lr] = 0;
    /* match "/memfd:" prefix */
    const char *want = "/memfd:";
    for (i = 0; want[i]; i++)
        if (link[i] != want[i])
            return 0;
    /* copy name after prefix */
    for (j = 0, i = 7; link[i] && (size_t)j + 1 < outsz; i++, j++)
        out[j] = link[i];
    out[j] = 0;
    return 1;
}

static void emit(const char *op, int fd, const char *detail,
                 long ret, void *ra) {
    char name[128];
    char buf[512];
    struct timespec ts;
    int i, n = 0;
    if (!memfd_name(fd, name, sizeof(name)))
        return;
    dump_maps();
    log_check();
    if (g_log < 0)
        return;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    /* pid op fd name detail ret ra tsec.tnsec — hand-rolled format */
    long vals[8];
    vals[0] = getpid();
    vals[1] = fd;
    vals[2] = ret;
    vals[3] = (long)ra;
    vals[4] = ts.tv_sec;
    vals[5] = ts.tv_nsec;
    /* op */
    for (i = 0; op[i] && n < 500; i++)
        buf[n++] = op[i];
    buf[n++] = ' ';
    /* ppid + comm for role identification */
    {
        long pp = getppid();
        char cb[24];
        int cn = 0, k2;
        int cfd = open("/proc/self/comm", O_RDONLY);
        const char *kp = "pp=";
        for (k2 = 0; kp[k2]; k2++)
            buf[n++] = kp[k2];
        if (pp == 0)
            cb[cn++] = '0';
        else {
            char rb[24];
            int rn = 0;
            while (pp > 0 && rn < 23) {
                rb[rn++] = '0' + (pp % 10);
                pp /= 10;
            }
            while (rn > 0)
                cb[cn++] = rb[--rn];
        }
        for (k2 = 0; k2 < cn && n < 490; k2++)
            buf[n++] = cb[k2];
        buf[n++] = ' ';
        buf[n++] = 'c';
        buf[n++] = 'm';
        buf[n++] = '=';
        if (cfd >= 0) {
            ssize_t cr = r_read(cfd, cb, sizeof(cb) - 1);
            close(cfd);
            if (cr > 0) {
                if (cb[cr - 1] == '\n')
                    cr--;
                for (k2 = 0; k2 < cr && n < 495; k2++)
                    buf[n++] = (cb[k2] == ' ' ? '_' : cb[k2]);
            }
        }
        buf[n++] = ' ';
    }
    /* name */
    for (i = 0; name[i] && n < 500; i++)
        buf[n++] = name[i];
    buf[n++] = ' ';
    for (i = 0; detail[i] && n < 500; i++)
        buf[n++] = detail[i];
    buf[n++] = ' ';
    /* numbers in hex for compactness */
    static const char *hexd = "0123456789abcdef";
    for (int v = 0; v < 6; v++) {
        unsigned long x = (unsigned long)vals[v];
        char tmp[20];
        int tn = 0, k;
        buf[n++] = (v == 0) ? 'p' : ' ';
        if (v == 1)
            buf[n++] = 'f', buf[n++] = 'd';
        if (v == 2)
            buf[n++] = 'r', buf[n++] = 'e', buf[n++] = 't';
        if (v == 3)
            buf[n++] = 'r', buf[n++] = 'a';
        if (v == 4)
            buf[n++] = 't', buf[n++] = 's';
        if (v == 5)
            buf[n++] = 't', buf[n++] = 'n';
        buf[n++] = '=';
        if (v == 2 && vals[v] < 0) {
            buf[n++] = '-';
            x = (unsigned long)(-(vals[v] + 1)) + 1;
        }
        if (x == 0)
            tmp[tn++] = '0';
        else
            while (x > 0 && tn < 19) {
                tmp[tn++] = hexd[x & 0xf];
                x >>= 4;
            }
        for (k = tn - 1; k >= 0 && n < 505; k--)
            buf[n++] = tmp[k];
    }
    buf[n++] = '\n';
    (void)!write(g_log, buf, (size_t)n);
}

/* detail builders write into a small stack buf */
#define DET_SZ 96
static void det_lseek(char *d, off_t off, int wh) {
    int n = 0, i = 0;
    const char *w = (wh == 0) ? "SET" : (wh == 1) ? "CUR" :
                    (wh == 2) ? "END" : "?";
    d[n++] = 'o';
    d[n++] = 'f';
    d[n++] = 'f';
    d[n++] = '=';
    unsigned long x = (unsigned long)(off < 0 ? -off : off);
    char tmp[20];
    int tn = 0;
    if (off < 0)
        d[n++] = '-';
    if (x == 0)
        tmp[tn++] = '0';
    else
        while (x > 0 && tn < 19) {
            tmp[tn++] = "0123456789abcdef"[x & 0xf];
            x >>= 4;
        }
    for (i = tn - 1; i >= 0 && n < DET_SZ - 8; i--)
        d[n++] = tmp[i];
    d[n++] = ' ';
    d[n++] = 'w';
    d[n++] = 'h';
    d[n++] = '=';
    for (i = 0; w[i] && n < DET_SZ - 1; i++)
        d[n++] = w[i];
    d[n++] = 0;
}

static void det_count(char *d, const char *k, unsigned long v,
                      const char *k2, long v2, int has2) {
    int n = 0, i = 0;
    for (i = 0; k[i] && n < DET_SZ - 1; i++)
        d[n++] = k[i];
    d[n++] = '=';
    char tmp[20];
    int tn = 0;
    if (v == 0)
        tmp[tn++] = '0';
    else
        while (v > 0 && tn < 19) {
            tmp[tn++] = "0123456789abcdef"[v & 0xf];
            v >>= 4;
        }
    for (i = tn - 1; i >= 0 && n < DET_SZ - 1; i--)
        d[n++] = tmp[i];
    if (has2) {
        d[n++] = ' ';
        for (i = 0; k2[i] && n < DET_SZ - 1; i++)
            d[n++] = k2[i];
        d[n++] = '=';
        d[n++] = (v2 == 0) ? '0' : '1';
    }
    d[n++] = 0;
}

off_t lseek(int fd, off_t off, int wh) {
    void *ra;
    char d[DET_SZ];
    off_t r;
    init_once();
    if (g_on != 1)
        return r_lseek ? r_lseek(fd, off, wh) : (off_t)-1;
    __builtin_frame_address(0);
    ra = __builtin_return_address(0);
    r = r_lseek(fd, off, wh);
    det_lseek(d, off, wh);
    emit("lseek", fd, d, (long)r, ra);
    return r;
}

off_t lseek64(int fd, off_t off, int wh) {
    void *ra;
    char d[DET_SZ];
    off_t r;
    init_once();
    if (g_on != 1)
        return r_lseek(fd, off, wh);
    ra = __builtin_return_address(0);
    r = r_lseek(fd, off, wh);
    det_lseek(d, off, wh);
    emit("lseek64", fd, d, (long)r, ra);
    return r;
}

/* Log evfd_data_arr contents + link targets for a successful
 * 8-byte ingress read (bounded: first 25 per process). Self-checks;
 * unverified reads skip silently. Proves slot-vs-reality per event. */
static void log_array_state(int fd) {
    int mfd, i;
    int nn = 0;
    unsigned long arr = 0;
    ssize_t n;
    char ln[64];
    if (g_enhanced >= 25 || g_libbase == 0 || EVFD_ARR_OFF == 0 ||
        NNODES_OFF == 0 || !r_pread)
        return;
    mfd = open("/proc/self/mem", O_RDONLY);
    if (mfd < 0)
        return;
    n = r_pread(mfd, &nn, 4, (off_t)(g_libbase + NNODES_OFF));
    if (n != 4 || nn < 1 || nn > 512) {
        close(mfd);
        return;
    }
    {
        unsigned long tmp = 0;
        n = r_pread(mfd, &tmp, 8,
                    (off_t)(g_libbase + EVFD_ARR_OFF));
        if (n != 8 || tmp == 0) {
            close(mfd);
            return;
        }
        arr = tmp;
    }
    g_enhanced++;
    /* header */
    {
        const char *h = "ARRSTATE ";
        (void)!write(g_log, h, 9);
    }
    for (i = 0; i < nn && i < 8; i++) {
        int v = -99;
        n = r_pread(mfd, &v, 4, (off_t)(arr + 4 * (unsigned)i));
        if (n != 4)
            break;
        {
            /* workers/ fds: readlink target */
            char path[64], link[160], ob[220];
            int pn = 0, k, on = 0;
            const char *pre = "/proc/self/fd/";
            for (k = 0; pre[k]; k++)
                path[pn++] = pre[k];
            /* v decimal (may be negative) */
            {
                char nb[16];
                int q = 0, neg = 0;
                long vv = v;
                if (vv < 0) {
                    neg = 1;
                    vv = -vv;
                }
                if (vv == 0)
                    nb[q++] = '0';
                else {
                    char rb[16];
                    int rn = 0;
                    while (vv > 0 && rn < 15) {
                        rb[rn++] = '0' + (vv % 10);
                        vv /= 10;
                    }
                    while (rn > 0)
                        nb[q++] = rb[--rn];
                }
                if (neg && q < 15) {
                    int t;
                    for (t = q; t > 0; t--)
                        nb[t] = nb[t - 1];
                    nb[0] = '-';
                    q++;
                }
                for (k = 0; k < q && pn < 60; k++)
                    path[pn++] = nb[k];
            }
            path[pn] = 0;
            ssize_t lr = readlink(path, link, sizeof(link) - 1);
            if (lr > 0)
                link[lr] = 0;
            else {
                link[0] = 'E';
                link[1] = 'R';
                link[2] = 'R';
                link[3] = 0;
                lr = 3;
            }
            /* ob = "slot[i]=v link\n" */
            {
                const char *s1 = "slot", *s2 = "=";
                int qq = i, dg[8], dn = 0, t;
                (void)s2;
                for (k = 0; s1[k]; k++)
                    ob[on++] = s1[k];
                if (qq == 0)
                    dg[dn++] = 0;
                else {
                    int rr[8], rn2 = 0;
                    while (qq > 0 && rn2 < 7) {
                        rr[rn2++] = qq % 10;
                        qq /= 10;
                    }
                    while (rn2 > 0)
                        dg[dn++] = rr[--rn2];
                }
                for (t = 0; t < dn && on < 200; t++)
                    ob[on++] = '0' + dg[t];
                ob[on++] = ':';
                for (k = 0; k < (int)lr && on < 215; k++)
                    ob[on++] = link[k] == '\n' ? '_' : link[k];
                ob[on++] = '\n';
            }
            (void)!write(g_log, ob, (size_t)on);
            (void)fd;
            (void)ln;
        }
    }
    close(mfd);
}

ssize_t read(int fd, void *buf, size_t n) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_read(fd, buf, n);
    ra = __builtin_return_address(0);
    r = r_read(fd, buf, n);
    det_count(d, "n", (unsigned long)n, 0, 0, 0);
    emit("read", fd, d, (long)r, ra);
    if (n == 8 && r == 8) {
        /* array-state capture only for the ingress memfd (other
         * memfds burn no cap budget) */
        char inm[128];
        if (memfd_name(fd, inm, sizeof(inm))) {
            const char *ig = "forkrun_ingress";
            int mi = 0;
            while (ig[mi] && inm[mi] == ig[mi])
                mi++;
            if (ig[mi] == 0)
                log_array_state(fd);
        }
    }
    return r;
}

ssize_t write(int fd, const void *buf, size_t n) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_write(fd, buf, n);
    if (fd == g_log)
        return r_write(fd, buf, n);
    ra = __builtin_return_address(0);
    r = r_write(fd, buf, n);
    det_count(d, "n", (unsigned long)n, 0, 0, 0);
    emit("write", fd, d, (long)r, ra);
    return r;
}

ssize_t pread(int fd, void *buf, size_t n, off_t off) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_pread(fd, buf, n, off);
    ra = __builtin_return_address(0);
    r = r_pread(fd, buf, n, off);
    det_count(d, "n", (unsigned long)n, 0, 0, 0);
    emit("pread", fd, d, (long)r, ra);
    return r;
}

ssize_t pwrite(int fd, const void *buf, size_t n, off_t off) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_pwrite(fd, buf, n, off);
    ra = __builtin_return_address(0);
    r = r_pwrite(fd, buf, n, off);
    det_count(d, "n", (unsigned long)n, 0, 0, 0);
    emit("pwrite", fd, d, (long)r, ra);
    return r;
}

ssize_t sendfile(int out, int in, off_t *off, size_t n) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_sendfile(out, in, off, n);
    ra = __builtin_return_address(0);
    r = r_sendfile(out, in, off, n);
    det_count(d, "n", (unsigned long)n, "offnull", off ? 1 : 0, 1);
    /* log under the memfd side (in first, then out) */
    emit("sendfile-in", in, d, (long)r, ra);
    emit("sendfile-out", out, d, (long)r, ra);
    return r;
}

ssize_t splice(int fi, loff_t *oi, int fo, loff_t *oo, size_t n,
               unsigned fl) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_splice(fi, oi, fo, oo, n, fl);
    (void)fl;
    ra = __builtin_return_address(0);
    r = r_splice(fi, oi, fo, oo, n, fl);
    det_count(d, "n", (unsigned long)n, "offnull", oi ? 1 : 0, 1);
    emit("splice-in", fi, d, (long)r, ra);
    emit("splice-out", fo, d, (long)r, ra);
    return r;
}

ssize_t copy_file_range(int fi, loff_t *oi, int fo, loff_t *oo,
                        size_t n, unsigned fl) {
    void *ra;
    char d[DET_SZ];
    ssize_t r;
    init_once();
    if (g_on != 1)
        return r_cfr(fi, oi, fo, oo, n, fl);
    ra = __builtin_return_address(0);
    r = r_cfr(fi, oi, fo, oo, n, fl);
    det_count(d, "n", (unsigned long)n, "offnull", oi ? 1 : 0, 1);
    emit("cfr-in", fi, d, (long)r, ra);
    emit("cfr-out", fo, d, (long)r, ra);
    return r;
}

int memfd_create(const char *name, unsigned flags) {
    void *ra;
    int r;
    init_once();
    if (g_on != 1)
        return r_memfd(name, flags);
    ra = __builtin_return_address(0);
    r = r_memfd(name, flags);
    /* log creation directly (fd fresh, readlink works already) */
    if (r >= 0) {
        char d[DET_SZ];
        int i, n = 0;
        const char *k = "new=";
        for (i = 0; k[i]; i++)
            d[n++] = k[i];
        for (i = 0; name[i] && n < DET_SZ - 1; i++)
            d[n++] = name[i];
        d[n++] = 0;
        emit("memfd_create", r, d, (long)r, ra);
    }
    return r;
}
