#!/bin/bash

fr_enable() {
. <(curl https://raw.githubusercontent.com/jkool702/forkrun/forkrun_testing_async-io_2/ring_loadables/frun.bash)

enable
}

fr_test() {

ring_pipe fd_r fd_w

(

exec {fd_r}<&-
seq 10 >&$fd_w
sleep 2
seq 20 >&$fd_w
sleep 3
exec {fd_w}>&-
) &

(

exec {fd_r}<&-
sleep 1
seq 30 >&$fd_w
sleep 4
seq 50 >&$fd_w
sleep 5
exec {fd_w}>&-
) &

(

exec {fd_r}<&-
seq 10 >&$fd_w
sleep 2
seq 20 >&$fd_w
sleep 3
exec {fd_w}>&-
) &
exec  {fd_w}<&-


{
(
time cat <&$fd_r >&$fd2 2>&$fd2
) &
} {fd2}>&2

exec  {fd_r}<&-

wait
}

fr_enable
fr_test
