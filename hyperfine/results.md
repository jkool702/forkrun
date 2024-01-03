The results from running the hyperfine-based speedtest (`forkrun.speedtest.hyperfine.bash`) and some observations regarding the results are shown below. This benchmark computes 11 different checksums on various-sie batches of small files. Batches of 10 files, 100 files, 1000 files 10000 files, 100000 files and ~521000 files were tested. Parallelization was tested/timed using:   `forkrun --`  ,   `xargs -P $(nproc) -d $'\n' --`   and   `parallel -m --`  .

## OBSERVATIONS:

**BASE "NO-LOAD" TIME**: ~ 2ms for `xargs`; ~22 ms for `forkrun`; and ~163 ms for `parallel` --> `xargs` is fastest in cases where this is a significant part of the total runtime (i.e., problems that finish running very fast, say, for total run times of under 80 ms for `forkrun` and under 500 ms for `parallel`)

**FORKRUN vs XARGS**: `xargs` is faster for problems that take ~50-70 ms or less (due to lower "no-load" time. `forkrun` is faster for all problems that take longer than ~50-70 ms (which is most of the problems you'd actually want to parallelize). For medium-sized problems `forkrun` is typically around 75% faster. For larger problems (i.e., >>100k inputs) `forkrun` is typically around 25% faster. This suggests that `forkrun` is better at "ramping up to full speed" (i.e., its dynamic batch size logic gets up to the maximum batch size faster).\*\*

**FORKRUN vs PARALLEL**: In all cases forkrun was faster than parallel. Its best (relative) performance was for medium-sized problems (~10000 inputs), where its speed was comparable to `xargs` (and on occasion slightly faster even), but `forkrun` was still ~75% faster. For larger problems (cases where stdin had 100,000+ inputs), parallel's time is almost linearly dependent on the number of inputs and the checksum being used has minimal effect on the time taken, indicating that its maximum throughput is only about 1/10th of `forkrun`/`xargs` for larger problems with many inputs (each of which runs very quickly).

\*\*This is because forkrun tries to estimate how many "cached in a tmpfile but not yet processed" lines from stdin are available, divides by the number of worker coprocs and sets that (or the pre-set maximum, whichever is lower) as the batch size. The process that caches stdin to a tmpfile is forked off a good bit before the coproc workers are forked, so when all of stdin is available immediately the batch size goes up to maximum almost instantly. xargs, on the other hand, AFAIK, just gradually ramps up the batch size until it hits some pre-set maximum without considering how many unprocessed lines from stdin are available.

## RESULTS OF HYPERFINE BENCHMARK COMPARING FORKRUN TO XARGS AND PARALLEL  

```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=10 ------------------------------------------------------------------------|| 

(algorithm)     (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0221667247    0.0018750129    0.1630903451    xargs is 1082.% faster than forkrun (11.822x)   forkrun is 635.7% faster than parallel (7.3574x)
sha256sum       0.0222077711    0.0019181561    0.1629461111    xargs is 1057.% faster than forkrun (11.577x)   forkrun is 633.7% faster than parallel (7.3373x)
sha512sum       0.0222074076    0.0019584463    0.1629756567    xargs is 1033.% faster than forkrun (11.339x)   forkrun is 633.8% faster than parallel (7.3387x)
sha224sum       0.0222283172    0.0019137923    0.1629487807    xargs is 1061.% faster than forkrun (11.614x)   forkrun is 633.0% faster than parallel (7.3306x)
sha384sum       0.0221844371    0.0019296681    0.1628500374    xargs is 1049.% faster than forkrun (11.496x)   forkrun is 634.0% faster than parallel (7.3407x)
md5sum          0.0221686970    0.0018695627    0.1630133621    xargs is 1085.% faster than forkrun (11.857x)   forkrun is 635.3% faster than parallel (7.3533x)
sum -s          0.0217999997    0.0014598752    0.1632813774    xargs is 1393.% faster than forkrun (14.932x)   forkrun is 648.9% faster than parallel (7.4899x)
sum -r          0.0218931983    0.0014866485    0.1630489127    xargs is 1372.% faster than forkrun (14.726x)   forkrun is 644.7% faster than parallel (7.4474x)
cksum           0.0222643711    0.0018542016    0.1634326655    xargs is 1100.% faster than forkrun (12.007x)   forkrun is 634.0% faster than parallel (7.3405x)
b2sum           0.0218908087    0.0015843474    0.1626443482    xargs is 1281.% faster than forkrun (13.816x)   forkrun is 642.9% faster than parallel (7.4298x)
cksum -a sm3    0.0223199789    0.0019613777    0.1641205825    xargs is 1037.% faster than forkrun (11.379x)   forkrun is 635.3% faster than parallel (7.3530x)

OVERALL         .24333171192    .01981108930    1.7943521798    xargs is 1128.% faster than forkrun (12.282x)   forkrun is 637.4% faster than parallel (7.3740x)




||----------------------------------------------------------------- NUM_CHECKSUMS=100 -----------------------------------------------------------------------|| 

(algorithm)     (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0236063838    0.0032121754    0.1946000551    xargs is 634.9% faster than forkrun (7.3490x)   forkrun is 724.3% faster than parallel (8.2435x)
sha256sum       0.0237318664    0.0036711432    0.1948226050    xargs is 546.4% faster than forkrun (6.4644x)   forkrun is 720.9% faster than parallel (8.2093x)
sha512sum       0.0237410334    0.0040142447    0.1948108999    xargs is 491.4% faster than forkrun (5.9141x)   forkrun is 720.5% faster than parallel (8.2056x)
sha224sum       0.0236955990    0.0036124260    0.1949263404    xargs is 555.9% faster than forkrun (6.5594x)   forkrun is 722.6% faster than parallel (8.2262x)
sha384sum       0.0237501755    0.0037770810    0.1948383579    xargs is 528.7% faster than forkrun (6.2879x)   forkrun is 720.3% faster than parallel (8.2036x)
md5sum          0.0235624059    0.0032311641    0.1946859117    xargs is 629.2% faster than forkrun (7.2922x)   forkrun is 726.2% faster than parallel (8.2625x)
sum -s          0.0227479824    0.0024039088    0.1950978508    xargs is 846.2% faster than forkrun (9.4629x)   forkrun is 757.6% faster than parallel (8.5764x)
sum -r          0.0228154072    0.0026705416    0.1947380948    xargs is 754.3% faster than forkrun (8.5433x)   forkrun is 753.5% faster than parallel (8.5353x)
cksum           0.0235367491    0.0027115275    0.1947627362    xargs is 768.0% faster than forkrun (8.6802x)   forkrun is 727.4% faster than parallel (8.2748x)
b2sum           0.0230250437    0.0035562619    0.1939956931    xargs is 547.4% faster than forkrun (6.4745x)   forkrun is 742.5% faster than parallel (8.4254x)
cksum -a sm3    0.0238663818    0.0041171368    0.1965976060    xargs is 479.6% faster than forkrun (5.7968x)   forkrun is 723.7% faster than parallel (8.2374x)

OVERALL         .25807902874    .03697761169    2.1438761514    xargs is 597.9% faster than forkrun (6.9793x)   forkrun is 730.7% faster than parallel (8.3070x)




||----------------------------------------------------------------- NUM_CHECKSUMS=1000 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.0447829312    0.0367322309    0.2632289219    xargs is 21.91% faster than forkrun (1.2191x)   forkrun is 487.7% faster than parallel (5.8778x)
sha256sum       0.0647563532    0.0630272988    0.2817073755    xargs is 2.743% faster than forkrun (1.0274x)   forkrun is 335.0% faster than parallel (4.3502x)
sha512sum       0.0536621067    0.0534120224    0.2706735149    xargs is .4682% faster than forkrun (1.0046x)   forkrun is 404.4% faster than parallel (5.0440x)
sha224sum       0.0637885819    0.0623672503    0.2816683651    xargs is 2.278% faster than forkrun (1.0227x)   forkrun is 341.5% faster than parallel (4.4156x)
sha384sum       0.0529855717    0.0508655843    0.2707261615    xargs is 4.167% faster than forkrun (1.0416x)   forkrun is 410.9% faster than parallel (5.1094x)
md5sum          0.0517946585    0.0448830329    0.2697468577    xargs is 15.39% faster than forkrun (1.1539x)   forkrun is 420.8% faster than parallel (5.2080x)
sum -s          0.0281302711    0.0162159577    0.2510356668    xargs is 73.47% faster than forkrun (1.7347x)   forkrun is 792.4% faster than parallel (8.9240x)
sum -r          0.0486180130    0.0432906465    0.2702369043    xargs is 12.30% faster than forkrun (1.1230x)   forkrun is 455.8% faster than parallel (5.5583x)
cksum           0.0286967624    0.0142509492    0.2483583623    xargs is 101.3% faster than forkrun (2.0136x)   forkrun is 765.4% faster than parallel (8.6545x)
b2sum           0.0456298664    0.0488122635    0.2670418882    forkrun is 6.974% faster than xargs (1.0697x)   forkrun is 485.2% faster than parallel (5.8523x)
cksum -a sm3    0.0951422082    0.1024677217    0.3124894991    forkrun is 7.699% faster than xargs (1.0769x)   forkrun is 228.4% faster than parallel (3.2844x)

OVERALL         .57798732470    .53632495868    2.9869135179    xargs is 7.768% faster than forkrun (1.0776x)   forkrun is 416.7% faster than parallel (5.1677x)




||----------------------------------------------------------------- NUM_CHECKSUMS=10000 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.7068868947    1.2371532120    1.3615521273    forkrun is 75.01% faster than xargs (1.7501x)   forkrun is 92.61% faster than parallel (1.9261x)
sha256sum       1.4254721642    2.5174737736    2.4808952115    forkrun is 76.60% faster than xargs (1.7660x)   forkrun is 74.04% faster than parallel (1.7404x)
sha512sum       0.9867826465    1.7589091023    1.8159882173    forkrun is 78.24% faster than xargs (1.7824x)   forkrun is 84.03% faster than parallel (1.8403x)
sha224sum       1.4230787006    2.5033083044    2.4817792528    forkrun is 75.90% faster than xargs (1.7590x)   forkrun is 74.39% faster than parallel (1.7439x)
sha384sum       0.9869722366    1.7495862818    1.8055435852    forkrun is 77.26% faster than xargs (1.7726x)   forkrun is 82.93% faster than parallel (1.8293x)
md5sum          0.9517106087    1.6826772677    1.7565612520    forkrun is 76.80% faster than xargs (1.7680x)   forkrun is 84.56% faster than parallel (1.8456x)
sum -s          0.1717381569    0.2925260065    0.5516866713    forkrun is 70.33% faster than xargs (1.7033x)   forkrun is 221.2% faster than parallel (3.2123x)
sum -r          0.9733280035    1.7119362551    1.7831547264    forkrun is 75.88% faster than xargs (1.7588x)   forkrun is 83.20% faster than parallel (1.8320x)
cksum           0.1310715757    0.2119448126    0.5510956006    forkrun is 61.70% faster than xargs (1.6170x)   forkrun is 320.4% faster than parallel (4.2045x)
b2sum           0.8708479121    1.5570632172    1.6286356189    forkrun is 78.79% faster than xargs (1.7879x)   forkrun is 87.01% faster than parallel (1.8701x)
cksum -a sm3    2.5808076571    4.5859107501    4.2774210021    forkrun is 77.69% faster than xargs (1.7769x)   forkrun is 65.73% faster than parallel (1.6573x)

OVERALL         11.208696557    19.808488983    20.494313265    forkrun is 76.72% faster than xargs (1.7672x)   forkrun is 82.84% faster than parallel (1.8284x)




||----------------------------------------------------------------- NUM_CHECKSUMS=100000 --------------------------------------------------------------------|| 

(algorithm)     (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         0.8230874306    1.2559810074    3.9540721269    forkrun is 52.59% faster than xargs (1.5259x)   forkrun is 380.3% faster than parallel (4.8039x)
sha256sum       1.6484554502    2.6550891789    4.0367873319    forkrun is 61.06% faster than xargs (1.6106x)   forkrun is 144.8% faster than parallel (2.4488x)
sha512sum       1.1750274711    1.8904443909    4.0000258502    forkrun is 60.88% faster than xargs (1.6088x)   forkrun is 240.4% faster than parallel (3.4041x)
sha224sum       1.6352138492    2.6546941293    4.0488493457    forkrun is 62.34% faster than xargs (1.6234x)   forkrun is 147.6% faster than parallel (2.4760x)
sha384sum       1.1548144916    1.8433252592    4.0058443152    forkrun is 59.62% faster than xargs (1.5962x)   forkrun is 246.8% faster than parallel (3.4688x)
md5sum          1.0083714716    1.6938738980    4.0088253269    forkrun is 67.98% faster than xargs (1.6798x)   forkrun is 297.5% faster than parallel (3.9755x)
sum -s          0.1964396966    0.2954914663    3.9373926711    forkrun is 50.42% faster than xargs (1.5042x)   forkrun is 1904.% faster than parallel (20.043x)
sum -r          1.0079121610    1.7266721227    4.0079479643    forkrun is 71.31% faster than xargs (1.7131x)   forkrun is 297.6% faster than parallel (3.9764x)
cksum           0.1773627671    0.2471011836    3.9402946387    forkrun is 39.31% faster than xargs (1.3931x)   forkrun is 2121.% faster than parallel (22.216x)
b2sum           1.0068455244    1.6141367308    3.9931291681    forkrun is 60.31% faster than xargs (1.6031x)   forkrun is 296.5% faster than parallel (3.9659x)
cksum -a sm3    2.9793014210    4.9038082163    4.2788775805    forkrun is 64.59% faster than xargs (1.6459x)   forkrun is 43.62% faster than parallel (1.4362x)

OVERALL         12.812831734    20.780617583    44.212046319    forkrun is 62.18% faster than xargs (1.6218x)   forkrun is 245.0% faster than parallel (3.4506x)




||----------------------------------------------------------------- NUM_CHECKSUMS=521911 --------------------------------------------------------------------|| 

(algorithm)     (forkrun)       (xargs)         (parallel)      (relative performance vs xargs)                 (relative performance vs parallel)          
------------    ------------    ------------    ------------    --------------------------------------------    -----------------------------------------------
sha1sum         1.6286943159    2.0199643854    20.075420332    forkrun is 24.02% faster than xargs (1.2402x)   forkrun is 1132.% faster than parallel (12.326x)
sha256sum       2.8644944094    3.5045886992    20.311441071    forkrun is 22.34% faster than xargs (1.2234x)   forkrun is 609.0% faster than parallel (7.0907x)
sha512sum       2.2340511511    2.6935622735    20.209039190    forkrun is 20.56% faster than xargs (1.2056x)   forkrun is 804.5% faster than parallel (9.0459x)
sha224sum       2.8613993569    3.4881405630    20.313363307    forkrun is 21.90% faster than xargs (1.2190x)   forkrun is 609.9% faster than parallel (7.0991x)
sha384sum       2.1859892692    2.6624580626    20.175458431    forkrun is 21.79% faster than xargs (1.2179x)   forkrun is 822.9% faster than parallel (9.2294x)
md5sum          1.727604421     2.3530172968    20.110481363    forkrun is 36.20% faster than xargs (1.3620x)   forkrun is 1064.% faster than parallel (11.640x)
sum -s          0.7482615006    1.1313569398    19.882553867    forkrun is 51.19% faster than xargs (1.5119x)   forkrun is 2557.% faster than parallel (26.571x)
sum -r          1.6692639257    2.3338452146    20.144961839    forkrun is 39.81% faster than xargs (1.3981x)   forkrun is 1106.% faster than parallel (12.068x)
cksum           0.7278956696    1.1016801017    19.863852705    forkrun is 51.35% faster than xargs (1.5135x)   forkrun is 2628.% faster than parallel (27.289x)
b2sum           1.9601611987    2.4058454718    20.198290951    forkrun is 22.73% faster than xargs (1.2273x)   forkrun is 930.4% faster than parallel (10.304x)
cksum -a sm3    4.9776278830    6.2101821971    20.868720708    forkrun is 24.76% faster than xargs (1.2476x)   forkrun is 319.2% faster than parallel (4.1925x)

OVERALL         23.585443101    29.904641205    222.15358376    forkrun is 26.79% faster than xargs (1.2679x)   forkrun is 841.9% faster than parallel (9.4190x)
```
