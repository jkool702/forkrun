#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include "config.h"
#include "builtins.h"
#include "shell.h"

#define PROC_STAT_FIELDS 44
#define MAX_STAT_LEN 1024

static long parse_stat_field(const char *stat, int field) {
    const char *p = stat;
    int current_field = 1;
    int in_comm = 0;
    
    if(*p == '(') {
        in_comm = 1;
        p++;
    }
    
    while(*p && current_field < field) {
        if(!in_comm) {
            if(*p == ' ') current_field++;
        } else {
            if(*p == ')') {
                in_comm = 0;
                current_field++;  // Account for end of comm field
            }
        }
        p++;
        while(*p == ' ') p++;
    }
    
    return strtol(p, NULL, 10);
}

int get_cpu_usage_builtin(WORD_LIST *list) {
    unsigned long long total = 0;
    WORD_LIST *l;

    for(l = list; l; l = l->next) {
        pid_t pid = atoi(l->word->word);
        char path[32];
        int fd;
        char stat_buf[MAX_STAT_LEN];
        ssize_t nread;
        
        snprintf(path, sizeof(path), "/proc/%d/stat", pid);
        
        if((fd = open(path, O_RDONLY)) == -1)
            continue;
            
        nread = read(fd, stat_buf, sizeof(stat_buf)-1);
        close(fd);
        
        if(nread > 0) {
            stat_buf[nread] = '\0';
            long utime = parse_stat_field(stat_buf, 14);
            long stime = parse_stat_field(stat_buf, 15);
            long cutime = parse_stat_field(stat_buf, 16);
            long cstime = parse_stat_field(stat_buf, 17);
            total += (unsigned long long)utime + stime + cutime + cstime;
        }
    }

    printf("%llu\n", total);
    return EXECUTION_SUCCESS;
}

struct builtin get_cpu_usage_struct = {
    (char *)"get_cpu_usage",
    get_cpu_usage_builtin,
    BUILTIN_ENABLED,
    (char *)"Calculate total CPU ticks for given PIDs",
    (char *)"get_cpu_usage pid1 [pid2 ... pidN]"
};