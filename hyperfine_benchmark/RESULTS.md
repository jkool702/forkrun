```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0725585474	0.0720929557	0.0788001077	0.1979509852	forkrun is 9.303% faster than xargs (1.0930x)	forkrun is 174.5% faster than parallel (2.7457x)	
sha256sum   	0.1176360906	0.1167646198	0.1457442108	0.2639306147	forkrun is 24.81% faster than xargs (1.2481x)	forkrun is 126.0% faster than parallel (2.2603x)	
sha512sum   	0.0911017573	0.0900386156	0.1073541361	0.2251327879	forkrun is 19.23% faster than xargs (1.1923x)	forkrun is 150.0% faster than parallel (2.5004x)	
sha224sum   	0.1175866648	0.1166149133	0.1455646789	0.2624057001	forkrun is 24.82% faster than xargs (1.2482x)	forkrun is 125.0% faster than parallel (2.2501x)	
sha384sum   	0.0909394508	0.0900077079	0.1064774848	0.2247994134	forkrun is 18.29% faster than xargs (1.1829x)	forkrun is 149.7% faster than parallel (2.4975x)	
md5sum      	0.0885755041	0.0881463407	0.1019697132	0.2205417194	forkrun is 15.68% faster than xargs (1.1568x)	forkrun is 150.1% faster than parallel (2.5019x)	
sum -s      	0.0377489504	0.0369515333	0.0289429940	0.1746979773	xargs is 27.67% faster than forkrun (1.2767x)	forkrun is 372.7% faster than parallel (4.7277x)	
sum -r      	0.0899070054	0.0885255944	0.1030114130	0.2227593301	forkrun is 16.36% faster than xargs (1.1636x)	forkrun is 151.6% faster than parallel (2.5163x)	
cksum       	0.0351437667	0.0352322614	0.0246590697	0.1744455326	xargs is 42.51% faster than forkrun (1.4251x)	forkrun is 396.3% faster than parallel (4.9637x)	
b2sum       	0.0831865434	0.0820973445	0.0952235200	0.2136706209	forkrun is 15.98% faster than xargs (1.1598x)	forkrun is 160.2% faster than parallel (2.6026x)	
cksum -a sm3	0.1889330552	0.1875064983	0.2515206285	0.3644831379	forkrun is 33.12% faster than xargs (1.3312x)	forkrun is 92.91% faster than parallel (1.9291x)	

OVERALL     	1.0133173366	1.0039783854	1.1892679571	2.5448178201	forkrun is 18.45% faster than xargs (1.1845x)	forkrun is 153.4% faster than parallel (2.5347x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0657043025	0.0622539853	0.0587040249	0.2225878846	xargs is 11.92% faster than forkrun (1.1192x)	forkrun is 238.7% faster than parallel (3.3877x)	
sha256sum   	0.0963533337	0.0901931893	0.0973709885	0.2296014789	forkrun is 1.056% faster than xargs (1.0105x)	forkrun is 138.2% faster than parallel (2.3829x)	
sha512sum   	0.0796251343	0.0752700382	0.0772503854	0.2230447776	xargs is 3.074% faster than forkrun (1.0307x)	forkrun is 180.1% faster than parallel (2.8011x)	
sha224sum   	0.0953938574	0.0906050505	0.0971342035	0.2292712747	forkrun is 7.206% faster than xargs (1.0720x)	forkrun is 153.0% faster than parallel (2.5304x)	
sha384sum   	0.0792331150	0.0743581341	0.0760410250	0.2242969969	xargs is 4.197% faster than forkrun (1.0419x)	forkrun is 183.0% faster than parallel (2.8308x)	
md5sum      	0.0764554407	0.0721325985	0.0719504217	0.2225285992	xargs is 6.261% faster than forkrun (1.0626x)	forkrun is 191.0% faster than parallel (2.9105x)	
sum -s      	0.0437055571	0.0415440609	0.0303103379	0.2243049652	xargs is 37.06% faster than forkrun (1.3706x)	forkrun is 439.9% faster than parallel (5.3992x)	
sum -r      	0.0765108093	0.0729445631	0.0718773724	0.2227912818	xargs is 1.484% faster than forkrun (1.0148x)	forkrun is 205.4% faster than parallel (3.0542x)	
cksum       	0.0412267145	0.0393255141	0.0268335436	0.2247335066	xargs is 46.55% faster than forkrun (1.4655x)	forkrun is 471.4% faster than parallel (5.7146x)	
b2sum       	0.0747154217	0.0707681028	0.0701579399	0.2224140355	xargs is .8696% faster than forkrun (1.0086x)	forkrun is 214.2% faster than parallel (3.1428x)	
cksum -a sm3	0.1430648979	0.1335950296	0.1570131829	0.2683157350	forkrun is 17.52% faster than xargs (1.1752x)	forkrun is 100.8% faster than parallel (2.0084x)	

OVERALL     	.87198858460	.82299026678	.83464342627	2.5138905363	xargs is 4.474% faster than forkrun (1.0447x)	forkrun is 188.2% faster than parallel (2.8829x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.1867015253	0.1969434563	0.2386977186	0.4715072541	forkrun is 27.84% faster than xargs (1.2784x)	forkrun is 152.5% faster than parallel (2.5254x)	
sha256sum   	0.3322351298	0.3583199901	0.4681176950	0.5537797738	forkrun is 40.89% faster than xargs (1.4089x)	forkrun is 66.68% faster than parallel (1.6668x)	
sha512sum   	0.2467307059	0.2561876953	0.3326483924	0.5018347472	forkrun is 29.84% faster than xargs (1.2984x)	forkrun is 95.88% faster than parallel (1.9588x)	
sha224sum   	0.3325379478	0.3581663335	0.4685610028	0.5520236175	forkrun is 40.90% faster than xargs (1.4090x)	forkrun is 66.00% faster than parallel (1.6600x)	
sha384sum   	0.2457841650	0.2606458978	0.3298648045	0.5025861434	forkrun is 26.55% faster than xargs (1.2655x)	forkrun is 92.82% faster than parallel (1.9282x)	
md5sum      	0.2357228265	0.2354668025	0.3183990356	0.4981314302	forkrun is 35.22% faster than xargs (1.3522x)	forkrun is 111.5% faster than parallel (2.1155x)	
sum -s      	0.0807566526	0.0752002162	0.0683035072	0.4497789642	xargs is 18.23% faster than forkrun (1.1823x)	forkrun is 456.9% faster than parallel (5.5695x)	
sum -r      	0.2385188904	0.2423304082	0.3236779935	0.4994696362	forkrun is 35.70% faster than xargs (1.3570x)	forkrun is 109.4% faster than parallel (2.0940x)	
cksum       	0.0722047824	0.0668172833	0.0547409313	0.4487276400	xargs is 22.06% faster than forkrun (1.2206x)	forkrun is 571.5% faster than parallel (6.7157x)	
b2sum       	0.2219382671	0.2431867819	0.2918487350	0.4871172812	forkrun is 31.49% faster than xargs (1.3149x)	forkrun is 119.4% faster than parallel (2.1948x)	
cksum -a sm3	0.5732426427	0.5976080648	0.8362951948	0.7714800347	forkrun is 45.88% faster than xargs (1.4588x)	forkrun is 34.58% faster than parallel (1.3458x)	

OVERALL     	2.7663735360	2.8908729306	3.7311550111	5.7364365229	forkrun is 34.87% faster than xargs (1.3487x)	forkrun is 107.3% faster than parallel (2.0736x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.3166234583	0.3081969813	0.2892968194	1.3709664832	xargs is 6.533% faster than forkrun (1.0653x)	forkrun is 344.8% faster than parallel (4.4483x)	
sha256sum   	0.5588102563	0.5361554151	0.5634634153	1.4267971958	forkrun is 5.093% faster than xargs (1.0509x)	forkrun is 166.1% faster than parallel (2.6611x)	
sha512sum   	0.4208754423	0.4118677542	0.4241373676	1.3731973373	forkrun is .7750% faster than xargs (1.0077x)	forkrun is 226.2% faster than parallel (3.2627x)	
sha224sum   	0.5501920427	0.5234951369	0.5569853392	1.4289820404	forkrun is 6.397% faster than xargs (1.0639x)	forkrun is 172.9% faster than parallel (2.7296x)	
sha384sum   	0.4157531883	0.3982773591	0.4202099000	1.3734294131	forkrun is 5.506% faster than xargs (1.0550x)	forkrun is 244.8% faster than parallel (3.4484x)	
md5sum      	0.3948152193	0.3225332777	0.3230644961	1.3656759629	forkrun is .1647% faster than xargs (1.0016x)	forkrun is 323.4% faster than parallel (4.2342x)	
sum -s      	0.1450227967	0.1265254470	0.1112041135	1.3396630351	xargs is 30.41% faster than forkrun (1.3041x)	forkrun is 823.7% faster than parallel (9.2376x)	
sum -r      	0.3994018897	0.3210762502	0.3285114489	1.3695607271	xargs is 21.57% faster than forkrun (1.2157x)	forkrun is 242.9% faster than parallel (3.4290x)	
cksum       	0.1309943854	0.1192536441	0.0987002132	1.3302864768	xargs is 32.71% faster than forkrun (1.3271x)	forkrun is 915.5% faster than parallel (10.155x)	
b2sum       	0.379415918 	0.3492759867	0.3717721853	1.3641621178	xargs is 2.056% faster than forkrun (1.0205x)	forkrun is 259.5% faster than parallel (3.5954x)	
cksum -a sm3	0.9215685345	0.9128113504	0.9739906008	1.5556143428	forkrun is 6.702% faster than xargs (1.0670x)	forkrun is 70.42% faster than parallel (1.7042x)	

OVERALL     	4.6334731319	4.3294686032	4.4613358997	15.298335132	forkrun is 3.045% faster than xargs (1.0304x)	forkrun is 253.3% faster than parallel (3.5335x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	1.1691990819	1.1143811324	1.0678331323	5.1917066165	xargs is 4.359% faster than forkrun (1.0435x)	forkrun is 365.8% faster than parallel (4.6588x)	
sha256sum   	2.0756542913	2.1749040468	2.1260143537	5.5108992503	xargs is 2.299% faster than forkrun (1.0229x)	forkrun is 153.3% faster than parallel (2.5338x)	
sha512sum   	1.5682774363	1.5860477947	1.5453862143	5.3672893988	xargs is 2.631% faster than forkrun (1.0263x)	forkrun is 238.4% faster than parallel (3.3840x)	
sha224sum   	2.0726675314	2.1845690247	2.1302818910	5.5215304415	xargs is 2.548% faster than forkrun (1.0254x)	forkrun is 152.7% faster than parallel (2.5275x)	
sha384sum   	1.5533092229	1.5852053605	1.5408653424	5.3432020748	xargs is .8075% faster than forkrun (1.0080x)	forkrun is 243.9% faster than parallel (3.4398x)	
md5sum      	1.4656343381	1.1748666538	1.1325501433	5.2998418160	xargs is 3.736% faster than forkrun (1.0373x)	forkrun is 351.1% faster than parallel (4.5110x)	
sum -s      	0.4941002657	0.3930854348	0.3464444167	4.8966754667	xargs is 13.46% faster than forkrun (1.1346x)	forkrun is 1145.% faster than parallel (12.457x)	
sum -r      	1.4812141555	1.1980802051	1.1455858101	5.2912711698	xargs is 29.29% faster than forkrun (1.2929x)	forkrun is 257.2% faster than parallel (3.5722x)	
cksum       	0.4389497101	0.3772458474	0.3323412783	4.8892325534	xargs is 32.07% faster than forkrun (1.3207x)	forkrun is 1013.% faster than parallel (11.138x)	
b2sum       	1.4064487610	1.3383431377	1.3022433907	5.2526404905	xargs is 8.001% faster than forkrun (1.0800x)	forkrun is 273.4% faster than parallel (3.7346x)	
cksum -a sm3	3.5168986116	3.9799941909	3.9605970642	5.9331419742	forkrun is 12.61% faster than xargs (1.1261x)	forkrun is 68.70% faster than parallel (1.6870x)	

OVERALL     	17.242353406	17.106722829	16.630143037	58.497431252	xargs is 2.865% faster than forkrun (1.0286x)	forkrun is 241.9% faster than parallel (3.4195x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.6989329360	3.1175157159	2.9904085499	12.434668815	forkrun is 10.79% faster than xargs (1.1079x)	forkrun is 360.7% faster than parallel (4.6072x)	
sha256sum   	5.1956187172	6.2479048200	5.9725777802	13.392190694	forkrun is 14.95% faster than xargs (1.1495x)	forkrun is 157.7% faster than parallel (2.5775x)	
sha512sum   	3.9128132755	4.4216966319	4.2344596606	13.013352871	forkrun is 8.220% faster than xargs (1.0822x)	forkrun is 232.5% faster than parallel (3.3258x)	
sha224sum   	5.3326558179	6.1593330569	5.9391213842	12.798612435	forkrun is 11.37% faster than xargs (1.1137x)	forkrun is 140.0% faster than parallel (2.4000x)	
sha384sum   	3.6970332571	4.3892427704	4.1878367560	12.546256798	forkrun is 13.27% faster than xargs (1.1327x)	forkrun is 239.3% faster than parallel (3.3936x)	
md5sum      	3.4040184367	3.5744967019	3.5274427026	12.665717266	forkrun is 3.625% faster than xargs (1.0362x)	forkrun is 272.0% faster than parallel (3.7208x)	
sum -s      	0.9508656814	0.8673272787	0.8216162715	11.499220428	xargs is 5.563% faster than forkrun (1.0556x)	forkrun is 1225.% faster than parallel (13.258x)	
sum -r      	3.4640789743	3.7169466691	3.6217599301	12.683057313	forkrun is 4.551% faster than xargs (1.0455x)	forkrun is 266.1% faster than parallel (3.6613x)	
cksum       	0.8317092173	0.7979606116	0.7386253343	11.501837499	xargs is 12.60% faster than forkrun (1.1260x)	forkrun is 1282.% faster than parallel (13.829x)	
b2sum       	3.3318977637	3.7699765853	3.6460292450	12.563921917	forkrun is 9.428% faster than xargs (1.0942x)	forkrun is 277.0% faster than parallel (3.7708x)	
cksum -a sm3	9.6956941663	11.295862557	10.914177753	14.661217500	forkrun is 12.56% faster than xargs (1.1256x)	forkrun is 51.21% faster than parallel (1.5121x)	

OVERALL     	42.515318244	48.358263399	46.594055368	139.76005354	forkrun is 9.593% faster than xargs (1.0959x)	forkrun is 228.7% faster than parallel (3.2872x)	



||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0730199223	0.0727325295	0.0788387873	0.1988198324	forkrun is 8.395% faster than xargs (1.0839x)	forkrun is 173.3% faster than parallel (2.7335x)	
sha256sum   	0.1179166227	0.1169469997	0.1453253860	0.2626935533	forkrun is 24.26% faster than xargs (1.2426x)	forkrun is 124.6% faster than parallel (2.2462x)	
sha512sum   	0.0915410373	0.0906715532	0.1070320217	0.2250823706	forkrun is 18.04% faster than xargs (1.1804x)	forkrun is 148.2% faster than parallel (2.4823x)	
sha224sum   	0.1178659428	0.1171349397	0.1448116400	0.2622763718	forkrun is 23.62% faster than xargs (1.2362x)	forkrun is 123.9% faster than parallel (2.2390x)	
sha384sum   	0.0910789308	0.0906048122	0.1062689514	0.2246542407	forkrun is 17.28% faster than xargs (1.1728x)	forkrun is 147.9% faster than parallel (2.4794x)	
md5sum      	0.0889779443	0.0886569425	0.1020857566	0.2207526761	forkrun is 14.73% faster than xargs (1.1473x)	forkrun is 148.0% faster than parallel (2.4809x)	
sum -s      	0.0383028472	0.0374748416	0.0290174489	0.1744665618	xargs is 29.14% faster than forkrun (1.2914x)	forkrun is 365.5% faster than parallel (4.6555x)	
sum -r      	0.0902066171	0.0891769129	0.1026726891	0.2219749153	forkrun is 15.13% faster than xargs (1.1513x)	forkrun is 148.9% faster than parallel (2.4891x)	
cksum       	0.0356710583	0.0357798832	0.0246473490	0.1750061148	xargs is 44.72% faster than forkrun (1.4472x)	forkrun is 390.6% faster than parallel (4.9061x)	
b2sum       	0.0837608943	0.0826988883	0.0950816697	0.2136881152	forkrun is 14.97% faster than xargs (1.1497x)	forkrun is 158.3% faster than parallel (2.5839x)	
cksum -a sm3	0.1893021058	0.187183433 	0.2507128390	0.3638964215	forkrun is 33.93% faster than xargs (1.3393x)	forkrun is 94.40% faster than parallel (1.9440x)	

OVERALL     	1.0176439232	1.0090617364	1.1864945392	2.5433111740	forkrun is 17.58% faster than xargs (1.1758x)	forkrun is 152.0% faster than parallel (2.5204x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0662833063	0.0632760842	0.0589545516	0.2233398189	xargs is 7.330% faster than forkrun (1.0733x)	forkrun is 252.9% faster than parallel (3.5296x)	
sha256sum   	0.0962282377	0.0912562797	0.0975668064	0.2292273993	forkrun is 1.391% faster than xargs (1.0139x)	forkrun is 138.2% faster than parallel (2.3821x)	
sha512sum   	0.0803544374	0.0763954230	0.0775014432	0.2230776096	forkrun is 1.447% faster than xargs (1.0144x)	forkrun is 192.0% faster than parallel (2.9200x)	
sha224sum   	0.0958628331	0.0928108339	0.0971468941	0.2288413843	forkrun is 4.671% faster than xargs (1.0467x)	forkrun is 146.5% faster than parallel (2.4656x)	
sha384sum   	0.0796613462	0.0761768973	0.0761303493	0.2239518882	xargs is .0611% faster than forkrun (1.0006x)	forkrun is 193.9% faster than parallel (2.9398x)	
md5sum      	0.0765774026	0.0729711427	0.0718783625	0.2232125049	xargs is 1.520% faster than forkrun (1.0152x)	forkrun is 205.8% faster than parallel (3.0589x)	
sum -s      	0.0443525703	0.0419162273	0.0306106948	0.2229298717	xargs is 36.93% faster than forkrun (1.3693x)	forkrun is 431.8% faster than parallel (5.3184x)	
sum -r      	0.0773298758	0.0738068019	0.0721446199	0.2229923810	xargs is 2.303% faster than forkrun (1.0230x)	forkrun is 202.1% faster than parallel (3.0212x)	
cksum       	0.0418869405	0.0400361401	0.0271546843	0.2246220423	xargs is 54.25% faster than forkrun (1.5425x)	forkrun is 436.2% faster than parallel (5.3625x)	
b2sum       	0.0753970370	0.0712649086	0.0705835032	0.2241491358	xargs is .9653% faster than forkrun (1.0096x)	forkrun is 214.5% faster than parallel (3.1452x)	
cksum -a sm3	0.1426924009	0.1359349092	0.1576450212	0.2682661666	forkrun is 10.47% faster than xargs (1.1047x)	forkrun is 88.00% faster than parallel (1.8800x)	

OVERALL     	.87662638830	.83584564836	.83731693081	2.5146102031	forkrun is .1760% faster than xargs (1.0017x)	forkrun is 200.8% faster than parallel (3.0084x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.1871980125	0.1953725310	0.2390935907	0.4701749967	forkrun is 27.72% faster than xargs (1.2772x)	forkrun is 151.1% faster than parallel (2.5116x)	
sha256sum   	0.3317699046	0.3520922017	0.4670034138	0.5531233670	forkrun is 32.63% faster than xargs (1.3263x)	forkrun is 57.09% faster than parallel (1.5709x)	
sha512sum   	0.2473241606	0.2522944473	0.3327262876	0.5018026308	forkrun is 34.53% faster than xargs (1.3453x)	forkrun is 102.8% faster than parallel (2.0289x)	
sha224sum   	0.3315550050	0.3369232047	0.4678773355	0.5524455734	forkrun is 38.86% faster than xargs (1.3886x)	forkrun is 63.96% faster than parallel (1.6396x)	
sha384sum   	0.2460660748	0.2573758285	0.3304029292	0.5013195159	forkrun is 28.37% faster than xargs (1.2837x)	forkrun is 94.78% faster than parallel (1.9478x)	
md5sum      	0.2364556890	0.2343003864	0.3186284278	0.4982938065	forkrun is 35.99% faster than xargs (1.3599x)	forkrun is 112.6% faster than parallel (2.1267x)	
sum -s      	0.0813045957	0.0762675089	0.0686092018	0.4530062286	xargs is 11.16% faster than forkrun (1.1116x)	forkrun is 493.9% faster than parallel (5.9397x)	
sum -r      	0.2389671540	0.2430036246	0.3235382090	0.5000614204	forkrun is 35.39% faster than xargs (1.3539x)	forkrun is 109.2% faster than parallel (2.0925x)	
cksum       	0.0722174997	0.0672379463	0.0548361801	0.4499172810	xargs is 22.61% faster than forkrun (1.2261x)	forkrun is 569.1% faster than parallel (6.6914x)	
b2sum       	0.2221200837	0.2292743105	0.2920705184	0.4881344436	forkrun is 31.49% faster than xargs (1.3149x)	forkrun is 119.7% faster than parallel (2.1976x)	
cksum -a sm3	0.5713973304	0.5955244115	0.8322267957	0.7712735605	forkrun is 45.64% faster than xargs (1.4564x)	forkrun is 34.98% faster than parallel (1.3498x)	

OVERALL     	2.7663755105	2.8396664017	3.7270128900	5.7395528247	forkrun is 34.72% faster than xargs (1.3472x)	forkrun is 107.4% faster than parallel (2.0747x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.3190217430	0.3039686247	0.2904862578	1.3643758421	xargs is 4.641% faster than forkrun (1.0464x)	forkrun is 348.8% faster than parallel (4.4885x)	
sha256sum   	0.5506981352	0.5322602172	0.5641757839	1.4389663410	forkrun is 5.996% faster than xargs (1.0599x)	forkrun is 170.3% faster than parallel (2.7035x)	
sha512sum   	0.4225085182	0.4078621635	0.4197106016	1.3804327243	xargs is .6666% faster than forkrun (1.0066x)	forkrun is 226.7% faster than parallel (3.2672x)	
sha224sum   	0.5507408828	0.5301800463	0.5550237665	1.4306294011	forkrun is .7776% faster than xargs (1.0077x)	forkrun is 159.7% faster than parallel (2.5976x)	
sha384sum   	0.4173711939	0.4066688335	0.4053551171	1.3766898245	xargs is .3240% faster than forkrun (1.0032x)	forkrun is 238.5% faster than parallel (3.3852x)	
md5sum      	0.3969684337	0.3179732961	0.3229690443	1.3663008127	xargs is 22.91% faster than forkrun (1.2291x)	forkrun is 244.1% faster than parallel (3.4418x)	
sum -s      	0.1456421527	0.1287036576	0.1137885420	1.344100345 	xargs is 13.10% faster than forkrun (1.1310x)	forkrun is 944.3% faster than parallel (10.443x)	
sum -r      	0.3991115828	0.3269649010	0.3282313896	1.3756332228	xargs is 21.59% faster than forkrun (1.2159x)	forkrun is 244.6% faster than parallel (3.4467x)	
cksum       	0.1323509487	0.1196498197	0.0998527926	1.3353636497	xargs is 19.82% faster than forkrun (1.1982x)	forkrun is 1016.% faster than parallel (11.160x)	
b2sum       	0.3789085622	0.3560124901	0.3727992993	1.3703080622	xargs is 1.638% faster than forkrun (1.0163x)	forkrun is 261.6% faster than parallel (3.6164x)	
cksum -a sm3	0.9261403395	0.9026937788	0.9715127202	1.5708652400	forkrun is 7.623% faster than xargs (1.0762x)	forkrun is 74.01% faster than parallel (1.7401x)	

OVERALL     	4.6394624932	4.3329378289	4.4439053153	15.353665465	forkrun is 2.561% faster than xargs (1.0256x)	forkrun is 254.3% faster than parallel (3.5434x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	1.1716636143	1.1227816611	1.0716480678	5.2214036719	xargs is 9.332% faster than forkrun (1.0933x)	forkrun is 345.6% faster than parallel (4.4564x)	
sha256sum   	2.0793851362	2.1770797022	2.1064591426	5.5558967093	forkrun is 1.302% faster than xargs (1.0130x)	forkrun is 167.1% faster than parallel (2.6718x)	
sha512sum   	1.5744941511	1.5757496834	1.5239974325	5.3766309957	xargs is 3.395% faster than forkrun (1.0339x)	forkrun is 241.2% faster than parallel (3.4121x)	
sha224sum   	2.0739516322	2.1589828112	2.1116602555	5.5990196695	forkrun is 1.818% faster than xargs (1.0181x)	forkrun is 169.9% faster than parallel (2.6996x)	
sha384sum   	1.5566692385	1.5706978077	1.5290514212	5.3729022785	xargs is 1.806% faster than forkrun (1.0180x)	forkrun is 245.1% faster than parallel (3.4515x)	
md5sum      	1.4668794246	1.1723651055	1.1365918910	5.3246280195	xargs is 29.05% faster than forkrun (1.2905x)	forkrun is 262.9% faster than parallel (3.6299x)	
sum -s      	0.4980720323	0.3922736551	0.3521903143	4.9202543987	xargs is 11.38% faster than forkrun (1.1138x)	forkrun is 1154.% faster than parallel (12.542x)	
sum -r      	1.4861125105	1.2016379660	1.1555746630	5.3789883243	xargs is 3.986% faster than forkrun (1.0398x)	forkrun is 347.6% faster than parallel (4.4763x)	
cksum       	0.4427048144	0.3781248726	0.3373868298	4.9451578096	xargs is 12.07% faster than forkrun (1.1207x)	forkrun is 1207.% faster than parallel (13.078x)	
b2sum       	1.4134935179	1.3489518396	1.3045277342	5.4539864911	xargs is 3.405% faster than forkrun (1.0340x)	forkrun is 304.3% faster than parallel (4.0431x)	
cksum -a sm3	3.5246299047	4.004003121 	3.9460530153	5.9123989889	forkrun is 11.95% faster than xargs (1.1195x)	forkrun is 67.74% faster than parallel (1.6774x)	

OVERALL     	17.288055977	17.102648225	16.575140767	59.061267357	xargs is 3.182% faster than forkrun (1.0318x)	forkrun is 245.3% faster than parallel (3.4533x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.6497735473	3.1213456798	2.9833969183	12.486515358	forkrun is 12.59% faster than xargs (1.1259x)	forkrun is 371.2% faster than parallel (4.7122x)	
sha256sum   	5.4643695951	6.1982650898	5.9606813089	12.700176593	forkrun is 9.082% faster than xargs (1.0908x)	forkrun is 132.4% faster than parallel (2.3241x)	
sha512sum   	3.6959487322	4.4118286994	4.2385404680	12.593050225	forkrun is 14.68% faster than xargs (1.1468x)	forkrun is 240.7% faster than parallel (3.4072x)	
sha224sum   	5.2574896882	6.1934049415	5.9074818364	12.767211230	forkrun is 12.36% faster than xargs (1.1236x)	forkrun is 142.8% faster than parallel (2.4283x)	
sha384sum   	3.7434766256	4.3843723871	4.2503598377	12.642655356	forkrun is 13.54% faster than xargs (1.1354x)	forkrun is 237.7% faster than parallel (3.3772x)	
md5sum      	3.3010062543	3.5892329738	3.5287642209	12.623138410	forkrun is 6.899% faster than xargs (1.0689x)	forkrun is 282.4% faster than parallel (3.8240x)	
sum -s      	0.9469379107	0.8801419148	0.8354571413	11.549625763	xargs is 5.348% faster than forkrun (1.0534x)	forkrun is 1212.% faster than parallel (13.122x)	
sum -r      	3.4662771444	3.6659014289	3.6111428259	12.640306087	xargs is 1.516% faster than forkrun (1.0151x)	forkrun is 244.8% faster than parallel (3.4480x)	
cksum       	0.8296444603	0.7918990211	0.7384492966	11.539809791	xargs is 7.238% faster than forkrun (1.0723x)	forkrun is 1357.% faster than parallel (14.572x)	
b2sum       	3.3645041315	3.7847914805	3.6533223304	12.777252783	xargs is 3.598% faster than forkrun (1.0359x)	forkrun is 237.5% faster than parallel (3.3759x)	
cksum -a sm3	10.088311143	11.291428700	10.895411649	14.681539787	forkrun is 8.000% faster than xargs (1.0800x)	forkrun is 45.53% faster than parallel (1.4553x)	

OVERALL     	42.807739233	48.312612317	46.603007834	139.00128138	forkrun is 8.865% faster than xargs (1.0886x)	forkrun is 224.7% faster than parallel (3.2471x)	



||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0730518678	0.0726516056	0.0792227436	0.1982759592	forkrun is 9.044% faster than xargs (1.0904x)	forkrun is 172.9% faster than parallel (2.7291x)	
sha256sum   	0.1181867048	0.1167904776	0.1463040885	0.2626038960	forkrun is 23.79% faster than xargs (1.2379x)	forkrun is 122.1% faster than parallel (2.2219x)	
sha512sum   	0.0915359840	0.0908748963	0.1076036246	0.2252557624	forkrun is 18.40% faster than xargs (1.1840x)	forkrun is 147.8% faster than parallel (2.4787x)	
sha224sum   	0.1179767674	0.1172630170	0.1460100702	0.2632914574	forkrun is 24.51% faster than xargs (1.2451x)	forkrun is 124.5% faster than parallel (2.2453x)	
sha384sum   	0.0913766370	0.0906554735	0.1069279112	0.2256200863	forkrun is 17.94% faster than xargs (1.1794x)	forkrun is 148.8% faster than parallel (2.4887x)	
md5sum      	0.0890722645	0.0885602411	0.1025294036	0.2208817104	forkrun is 15.77% faster than xargs (1.1577x)	forkrun is 149.4% faster than parallel (2.4941x)	
sum -s      	0.0384651880	0.0377418936	0.0295401546	0.1744338733	xargs is 27.76% faster than forkrun (1.2776x)	forkrun is 362.1% faster than parallel (4.6217x)	
sum -r      	0.0904119870	0.0890912982	0.1036866706	0.2222509364	forkrun is 16.38% faster than xargs (1.1638x)	forkrun is 149.4% faster than parallel (2.4946x)	
cksum       	0.0359033759	0.0358492843	0.0252940136	0.1749671145	xargs is 41.94% faster than forkrun (1.4194x)	forkrun is 387.3% faster than parallel (4.8732x)	
b2sum       	0.0837604766	0.0824591534	0.0956487950	0.2141598351	forkrun is 15.99% faster than xargs (1.1599x)	forkrun is 159.7% faster than parallel (2.5971x)	
cksum -a sm3	0.189431657 	0.1872982812	0.2525056671	0.364440035 	forkrun is 33.29% faster than xargs (1.3329x)	forkrun is 92.38% faster than parallel (1.9238x)	

OVERALL     	1.0191729105	1.0092356224	1.1952731432	2.5461806665	forkrun is 18.43% faster than xargs (1.1843x)	forkrun is 152.2% faster than parallel (2.5228x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0668608090	0.0636300662	0.0596535882	0.2235040673	xargs is 6.665% faster than forkrun (1.0666x)	forkrun is 251.2% faster than parallel (3.5125x)	
sha256sum   	0.0971956319	0.0920190336	0.0983732376	0.2294493408	forkrun is 6.905% faster than xargs (1.0690x)	forkrun is 149.3% faster than parallel (2.4934x)	
sha512sum   	0.0809913311	0.0764260806	0.0785435763	0.2232483140	forkrun is 2.770% faster than xargs (1.0277x)	forkrun is 192.1% faster than parallel (2.9211x)	
sha224sum   	0.0967508951	0.0918358612	0.0980551429	0.2296537546	forkrun is 6.772% faster than xargs (1.0677x)	forkrun is 150.0% faster than parallel (2.5006x)	
sha384sum   	0.0802556491	0.0759840288	0.0769347817	0.2235948712	forkrun is 1.251% faster than xargs (1.0125x)	forkrun is 194.2% faster than parallel (2.9426x)	
md5sum      	0.0773295460	0.0737700811	0.0726324909	0.2234840200	xargs is 1.566% faster than forkrun (1.0156x)	forkrun is 202.9% faster than parallel (3.0294x)	
sum -s      	0.0447589359	0.0424078085	0.0313619292	0.2242520554	xargs is 35.22% faster than forkrun (1.3522x)	forkrun is 428.7% faster than parallel (5.2879x)	
sum -r      	0.0779810405	0.0741920094	0.0729668465	0.2241976680	xargs is 1.679% faster than forkrun (1.0167x)	forkrun is 202.1% faster than parallel (3.0218x)	
cksum       	0.0424533731	0.0403091835	0.0278372356	0.2248445139	xargs is 44.80% faster than forkrun (1.4480x)	forkrun is 457.7% faster than parallel (5.5779x)	
b2sum       	0.0757823090	0.0726048154	0.0713034696	0.2231194351	xargs is 1.825% faster than forkrun (1.0182x)	forkrun is 207.3% faster than parallel (3.0730x)	
cksum -a sm3	0.1435031647	0.1352685762	0.1589066921	0.2686105604	forkrun is 17.47% faster than xargs (1.1747x)	forkrun is 98.57% faster than parallel (1.9857x)	

OVERALL     	.88386268596	.83844754498	.84656899126	2.5179586012	forkrun is .9686% faster than xargs (1.0096x)	forkrun is 200.3% faster than parallel (3.0031x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.1910319961	0.1909195783	0.2395306548	0.4714221781	forkrun is 25.46% faster than xargs (1.2546x)	forkrun is 146.9% faster than parallel (2.4692x)	
sha256sum   	0.3370719316	0.3448775575	0.4680917054	0.5522485803	forkrun is 38.86% faster than xargs (1.3886x)	forkrun is 63.83% faster than parallel (1.6383x)	
sha512sum   	0.2508875918	0.2605494236	0.3328528435	0.5029657219	forkrun is 32.67% faster than xargs (1.3267x)	forkrun is 100.4% faster than parallel (2.0047x)	
sha224sum   	0.3350600118	0.3525144029	0.4675220634	0.5508751864	forkrun is 32.62% faster than xargs (1.3262x)	forkrun is 56.27% faster than parallel (1.5627x)	
sha384sum   	0.2470085671	0.2591043240	0.3318206753	0.5029230613	forkrun is 34.33% faster than xargs (1.3433x)	forkrun is 103.6% faster than parallel (2.0360x)	
md5sum      	0.2378259019	0.2393538803	0.3202736101	0.4966865614	forkrun is 34.66% faster than xargs (1.3466x)	forkrun is 108.8% faster than parallel (2.0884x)	
sum -s      	0.0820879900	0.0771501767	0.0693680136	0.4500522355	xargs is 11.21% faster than forkrun (1.1121x)	forkrun is 483.3% faster than parallel (5.8334x)	
sum -r      	0.2423923928	0.2444231931	0.326022839 	0.498913233 	forkrun is 34.50% faster than xargs (1.3450x)	forkrun is 105.8% faster than parallel (2.0582x)	
cksum       	0.0735200285	0.0687001795	0.0557053413	0.4497154037	xargs is 23.32% faster than forkrun (1.2332x)	forkrun is 554.6% faster than parallel (6.5460x)	
b2sum       	0.2249825099	0.2299975550	0.2933231795	0.4875778905	forkrun is 30.37% faster than xargs (1.3037x)	forkrun is 116.7% faster than parallel (2.1671x)	
cksum -a sm3	0.5730721526	0.5736709561	0.8359746316	0.7715416324	forkrun is 45.87% faster than xargs (1.4587x)	forkrun is 34.63% faster than parallel (1.3463x)	

OVERALL     	2.7949410745	2.8412612275	3.7404855579	5.7349216849	forkrun is 33.83% faster than xargs (1.3383x)	forkrun is 105.1% faster than parallel (2.0518x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.3315472704	0.3098758872	0.2948799957	1.3761097766	xargs is 5.085% faster than forkrun (1.0508x)	forkrun is 344.0% faster than parallel (4.4408x)	
sha256sum   	0.5705455540	0.546376473 	0.5520997747	1.434775142 	forkrun is 1.047% faster than xargs (1.0104x)	forkrun is 162.5% faster than parallel (2.6259x)	
sha512sum   	0.4373900432	0.4173965980	0.4124995413	1.3771025894	xargs is 6.034% faster than forkrun (1.0603x)	forkrun is 214.8% faster than parallel (3.1484x)	
sha224sum   	0.56516633  	0.5422310254	0.5638459012	1.4331749806	xargs is .2341% faster than forkrun (1.0023x)	forkrun is 153.5% faster than parallel (2.5358x)	
sha384sum   	0.4320985907	0.4018881601	0.4241962276	1.3821499741	forkrun is 5.550% faster than xargs (1.0555x)	forkrun is 243.9% faster than parallel (3.4391x)	
md5sum      	0.4018703646	0.3250932425	0.3311144942	1.3793404691	forkrun is 1.852% faster than xargs (1.0185x)	forkrun is 324.2% faster than parallel (4.2429x)	
sum -s      	0.1514260072	0.1310092632	0.1143757240	1.3390705802	xargs is 14.54% faster than forkrun (1.1454x)	forkrun is 922.1% faster than parallel (10.221x)	
sum -r      	0.4059789234	0.3288167702	0.3342683949	1.3660338475	forkrun is 1.657% faster than xargs (1.0165x)	forkrun is 315.4% faster than parallel (4.1543x)	
cksum       	0.1376183222	0.1222059192	0.1025875349	1.3396406151	xargs is 19.12% faster than forkrun (1.1912x)	forkrun is 996.2% faster than parallel (10.962x)	
b2sum       	0.3876408274	0.3710101261	0.3677582758	1.3735223842	xargs is .8842% faster than forkrun (1.0088x)	forkrun is 270.2% faster than parallel (3.7021x)	
cksum -a sm3	0.9353710327	0.9247489474	0.9682498708	1.5596118862	forkrun is 4.704% faster than xargs (1.0470x)	forkrun is 68.65% faster than parallel (1.6865x)	

OVERALL     	4.7566532661	4.4206524126	4.4658757354	15.360532245	forkrun is 1.023% faster than xargs (1.0102x)	forkrun is 247.4% faster than parallel (3.4747x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	1.2056974120	1.1333602531	1.0877623781	5.2022942798	xargs is 4.191% faster than forkrun (1.0419x)	forkrun is 359.0% faster than parallel (4.5901x)	
sha256sum   	2.1232045222	2.1856630589	2.1573226186	5.5379055972	forkrun is 1.606% faster than xargs (1.0160x)	forkrun is 160.8% faster than parallel (2.6082x)	
sha512sum   	1.6192330488	1.6053534100	1.5612246114	5.3700376861	xargs is 2.826% faster than forkrun (1.0282x)	forkrun is 234.5% faster than parallel (3.3450x)	
sha224sum   	2.1164048981	2.1908843424	2.1346249812	5.5585556694	forkrun is .8608% faster than xargs (1.0086x)	forkrun is 162.6% faster than parallel (2.6264x)	
sha384sum   	1.6006847373	1.5883122461	1.5491111198	5.3424273220	xargs is 2.530% faster than forkrun (1.0253x)	forkrun is 236.3% faster than parallel (3.3635x)	
md5sum      	1.4909280746	1.1902887666	1.1542709407	5.3183265135	xargs is 29.16% faster than forkrun (1.2916x)	forkrun is 256.7% faster than parallel (3.5671x)	
sum -s      	0.5116285099	0.4056088303	0.3537193156	4.919325751 	xargs is 14.66% faster than forkrun (1.1466x)	forkrun is 1112.% faster than parallel (12.128x)	
sum -r      	1.5094776240	1.2076485366	1.1674740388	5.2965400409	xargs is 3.441% faster than forkrun (1.0344x)	forkrun is 338.5% faster than parallel (4.3858x)	
cksum       	0.4528506094	0.3835686186	0.3477171890	4.9197883140	xargs is 10.31% faster than forkrun (1.1031x)	forkrun is 1182.% faster than parallel (12.826x)	
b2sum       	1.4513691900	1.3662113826	1.3303758488	5.3359084009	xargs is 2.693% faster than forkrun (1.0269x)	forkrun is 290.5% faster than parallel (3.9056x)	
cksum -a sm3	3.5708873235	3.9924629163	3.9562677946	5.9412578627	forkrun is 10.79% faster than xargs (1.1079x)	forkrun is 66.38% faster than parallel (1.6638x)	

OVERALL     	17.652365950	17.249362362	16.799870837	58.742367437	xargs is 2.675% faster than forkrun (1.0267x)	forkrun is 240.5% faster than parallel (3.4054x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.8843384640	3.1479987014	2.9940223690	12.489745648	forkrun is 3.802% faster than xargs (1.0380x)	forkrun is 333.0% faster than parallel (4.3301x)	
sha256sum   	5.6601261454	6.2149173557	6.0004215437	12.770064618	forkrun is 6.012% faster than xargs (1.0601x)	forkrun is 125.6% faster than parallel (2.2561x)	
sha512sum   	3.9773940554	4.4483697571	4.3002161132	12.697794081	forkrun is 8.116% faster than xargs (1.0811x)	forkrun is 219.2% faster than parallel (3.1924x)	
sha224sum   	5.6523621429	6.2165891872	5.9990755805	12.649486261	forkrun is 6.133% faster than xargs (1.0613x)	forkrun is 123.7% faster than parallel (2.2379x)	
sha384sum   	4.0367221610	4.4300985954	4.2925374729	12.705934805	forkrun is 6.337% faster than xargs (1.0633x)	forkrun is 214.7% faster than parallel (3.1475x)	
md5sum      	3.5637802827	3.5937352341	3.5551168281	12.521177536	xargs is .2436% faster than forkrun (1.0024x)	forkrun is 251.3% faster than parallel (3.5134x)	
sum -s      	0.9937906061	0.8918547401	0.8531092863	11.614712179	xargs is 4.541% faster than forkrun (1.0454x)	forkrun is 1202.% faster than parallel (13.023x)	
sum -r      	3.6907495999	3.6831788480	3.6318771806	12.648930436	xargs is 1.412% faster than forkrun (1.0141x)	forkrun is 243.4% faster than parallel (3.4342x)	
cksum       	0.8594042205	0.8105772717	0.7623861305	11.454705475	xargs is 6.321% faster than forkrun (1.0632x)	forkrun is 1313.% faster than parallel (14.131x)	
b2sum       	3.4807875060	3.8212284663	3.6881660173	12.620083305	forkrun is 5.957% faster than xargs (1.0595x)	forkrun is 262.5% faster than parallel (3.6256x)	
cksum -a sm3	10.289389616	11.367691732	10.931462497	14.674622038	forkrun is 6.240% faster than xargs (1.0624x)	forkrun is 42.61% faster than parallel (1.4261x)	

OVERALL     	45.088844801	48.626239890	47.008391020	138.84725638	forkrun is 4.257% faster than xargs (1.0425x)	forkrun is 207.9% faster than parallel (3.0794x)	



||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0731612638	0.0726775423	0.0794611338	0.1982461964	forkrun is 9.333% faster than xargs (1.0933x)	forkrun is 172.7% faster than parallel (2.7277x)	
sha256sum   	0.1179459683	0.1169939798	0.1461393984	0.2631867201	forkrun is 24.91% faster than xargs (1.2491x)	forkrun is 124.9% faster than parallel (2.2495x)	
sha512sum   	0.0913956325	0.0908050620	0.1080361316	0.2256388234	forkrun is 18.97% faster than xargs (1.1897x)	forkrun is 148.4% faster than parallel (2.4848x)	
sha224sum   	0.1189647631	0.1172883690	0.1463416076	0.2632299072	forkrun is 24.77% faster than xargs (1.2477x)	forkrun is 124.4% faster than parallel (2.2442x)	
sha384sum   	0.0913475549	0.0906143978	0.1069994374	0.2250033949	forkrun is 18.08% faster than xargs (1.1808x)	forkrun is 148.3% faster than parallel (2.4830x)	
md5sum      	0.0891808800	0.0886807352	0.1025739297	0.2212802584	forkrun is 15.66% faster than xargs (1.1566x)	forkrun is 149.5% faster than parallel (2.4952x)	
sum -s      	0.0384947728	0.0378473343	0.0297792463	0.1743976518	xargs is 27.09% faster than forkrun (1.2709x)	forkrun is 360.7% faster than parallel (4.6079x)	
sum -r      	0.0903447205	0.0892292183	0.1036825088	0.2223534273	forkrun is 16.19% faster than xargs (1.1619x)	forkrun is 149.1% faster than parallel (2.4919x)	
cksum       	0.0358901856	0.0359324370	0.0253891857	0.1751609853	xargs is 41.36% faster than forkrun (1.4136x)	forkrun is 388.0% faster than parallel (4.8804x)	
b2sum       	0.0838256500	0.0825893029	0.0959748674	0.2143355036	forkrun is 16.20% faster than xargs (1.1620x)	forkrun is 159.5% faster than parallel (2.5951x)	
cksum -a sm3	0.1888712932	0.1874776793	0.2526857401	0.3646074396	forkrun is 34.78% faster than xargs (1.3478x)	forkrun is 94.48% faster than parallel (1.9448x)	

OVERALL     	1.0194226852	1.0101360586	1.1970631873	2.5474403085	forkrun is 18.50% faster than xargs (1.1850x)	forkrun is 152.1% faster than parallel (2.5218x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0669916416	0.0637366031	0.0598828663	0.2240592736	xargs is 6.435% faster than forkrun (1.0643x)	forkrun is 251.5% faster than parallel (3.5153x)	
sha256sum   	0.0971082032	0.0920376487	0.0986222931	0.2301232559	forkrun is 1.559% faster than xargs (1.0155x)	forkrun is 136.9% faster than parallel (2.3697x)	
sha512sum   	0.0811963251	0.0767119792	0.0786005164	0.2234853501	forkrun is 2.461% faster than xargs (1.0246x)	forkrun is 191.3% faster than parallel (2.9133x)	
sha224sum   	0.0975016557	0.0913132715	0.0982159924	0.2299287054	forkrun is 7.559% faster than xargs (1.0755x)	forkrun is 151.8% faster than parallel (2.5180x)	
sha384sum   	0.0803036616	0.0757839431	0.0772228378	0.2248417943	forkrun is 1.898% faster than xargs (1.0189x)	forkrun is 196.6% faster than parallel (2.9668x)	
md5sum      	0.0771956861	0.0733661565	0.0728506643	0.2237301428	xargs is .7076% faster than forkrun (1.0070x)	forkrun is 204.9% faster than parallel (3.0495x)	
sum -s      	0.0449459675	0.0427992029	0.0314801320	0.2241154001	xargs is 35.95% faster than forkrun (1.3595x)	forkrun is 423.6% faster than parallel (5.2364x)	
sum -r      	0.0779623579	0.0741405119	0.0731123631	0.2237509811	xargs is 1.406% faster than forkrun (1.0140x)	forkrun is 201.7% faster than parallel (3.0179x)	
cksum       	0.0425363665	0.0403096503	0.0279443549	0.2250169120	xargs is 52.21% faster than forkrun (1.5221x)	forkrun is 428.9% faster than parallel (5.2899x)	
b2sum       	0.0759264979	0.0720735154	0.0713866298	0.2234462306	xargs is .9622% faster than forkrun (1.0096x)	forkrun is 210.0% faster than parallel (3.1002x)	
cksum -a sm3	0.1436138770	0.1348584169	0.1591227407	0.2688837688	forkrun is 10.79% faster than xargs (1.1079x)	forkrun is 87.22% faster than parallel (1.8722x)	

OVERALL     	.88528224077	.83713090009	.84844139134	2.5213818152	forkrun is 1.351% faster than xargs (1.0135x)	forkrun is 201.1% faster than parallel (3.0119x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.1901449885	0.1899590740	0.2392614786	0.4718108749	forkrun is 25.95% faster than xargs (1.2595x)	forkrun is 148.3% faster than parallel (2.4837x)	
sha256sum   	0.3361066683	0.3532484553	0.4683609859	0.5529047832	forkrun is 39.34% faster than xargs (1.3934x)	forkrun is 64.50% faster than parallel (1.6450x)	
sha512sum   	0.2539669912	0.2572522605	0.3328694221	0.5048905679	forkrun is 29.39% faster than xargs (1.2939x)	forkrun is 96.26% faster than parallel (1.9626x)	
sha224sum   	0.3380836664	0.3518454964	0.4674501604	0.5534842011	forkrun is 38.26% faster than xargs (1.3826x)	forkrun is 63.71% faster than parallel (1.6371x)	
sha384sum   	0.2499058557	0.2538653119	0.3316386063	0.5049208596	forkrun is 32.70% faster than xargs (1.3270x)	forkrun is 102.0% faster than parallel (2.0204x)	
md5sum      	0.2382456489	0.2385695730	0.3198088906	0.4982601248	forkrun is 34.23% faster than xargs (1.3423x)	forkrun is 109.1% faster than parallel (2.0913x)	
sum -s      	0.0826194524	0.0767522962	0.0694583251	0.4513592053	xargs is 10.50% faster than forkrun (1.1050x)	forkrun is 488.0% faster than parallel (5.8807x)	
sum -r      	0.2404648623	0.2433701059	0.3246636909	0.4994838530	forkrun is 33.40% faster than xargs (1.3340x)	forkrun is 105.2% faster than parallel (2.0523x)	
cksum       	0.0733604840	0.0686502414	0.0556333861	0.4502042010	xargs is 23.39% faster than forkrun (1.2339x)	forkrun is 555.7% faster than parallel (6.5579x)	
b2sum       	0.2278993322	0.2263647458	0.2931132753	0.4904553450	forkrun is 28.61% faster than xargs (1.2861x)	forkrun is 115.2% faster than parallel (2.1520x)	
cksum -a sm3	0.5743766226	0.5911563319	0.8363826869	0.7712030518	forkrun is 45.61% faster than xargs (1.4561x)	forkrun is 34.26% faster than parallel (1.3426x)	

OVERALL     	2.8051745729	2.8510338927	3.7386409087	5.7489770681	forkrun is 33.27% faster than xargs (1.3327x)	forkrun is 104.9% faster than parallel (2.0494x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.3250722407	0.3067035100	0.3109897361	1.3784741499	forkrun is 1.397% faster than xargs (1.0139x)	forkrun is 349.4% faster than parallel (4.4944x)	
sha256sum   	0.5664363809	0.5353927894	0.5382303376	1.4461349870	forkrun is .5299% faster than xargs (1.0052x)	forkrun is 170.1% faster than parallel (2.7010x)	
sha512sum   	0.4345544078	0.4271914829	0.4185044538	1.3880456847	xargs is 2.075% faster than forkrun (1.0207x)	forkrun is 224.9% faster than parallel (3.2492x)	
sha224sum   	0.5616820015	0.5279523758	0.5559479555	1.4352032801	xargs is 1.031% faster than forkrun (1.0103x)	forkrun is 155.5% faster than parallel (2.5551x)	
sha384sum   	0.4343584876	0.4101149270	0.4110238033	1.3847170408	forkrun is .2216% faster than xargs (1.0022x)	forkrun is 237.6% faster than parallel (3.3764x)	
md5sum      	0.4038330988	0.3275310031	0.3334954350	1.3723352705	xargs is 21.09% faster than forkrun (1.2109x)	forkrun is 239.8% faster than parallel (3.3982x)	
sum -s      	0.1513145127	0.1305986011	0.1163486814	1.3458414492	xargs is 12.24% faster than forkrun (1.1224x)	forkrun is 930.5% faster than parallel (10.305x)	
sum -r      	0.4076167815	0.3281906760	0.3344449610	1.3717910379	forkrun is 1.905% faster than xargs (1.0190x)	forkrun is 317.9% faster than parallel (4.1798x)	
cksum       	0.1367991905	0.1227366270	0.1048764788	1.3343968874	xargs is 17.02% faster than forkrun (1.1702x)	forkrun is 987.2% faster than parallel (10.872x)	
b2sum       	0.3928224392	0.3596149893	0.3681180573	1.3820127965	forkrun is 2.364% faster than xargs (1.0236x)	forkrun is 284.3% faster than parallel (3.8430x)	
cksum -a sm3	0.9427080607	0.9227854010	0.9721543789	1.5669939696	forkrun is 5.349% faster than xargs (1.0534x)	forkrun is 69.81% faster than parallel (1.6981x)	

OVERALL     	4.7571976023	4.3988123831	4.4641342792	15.405946554	forkrun is 1.484% faster than xargs (1.0148x)	forkrun is 250.2% faster than parallel (3.5022x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	1.2081390100	1.1298657723	1.0927677203	5.2213775475	xargs is 3.394% faster than forkrun (1.0339x)	forkrun is 362.1% faster than parallel (4.6212x)	
sha256sum   	2.1288093727	2.2055645519	2.1260736941	5.5675015318	xargs is .1286% faster than forkrun (1.0012x)	forkrun is 161.5% faster than parallel (2.6153x)	
sha512sum   	1.6204445413	1.5979295691	1.5540226900	5.4010445192	xargs is 2.825% faster than forkrun (1.0282x)	forkrun is 238.0% faster than parallel (3.3800x)	
sha224sum   	2.1236036511	2.1972564096	2.1363121162	5.5780732732	forkrun is .5984% faster than xargs (1.0059x)	forkrun is 162.6% faster than parallel (2.6267x)	
sha384sum   	1.5980579672	1.5816143133	1.5262387993	5.3828930822	xargs is 4.705% faster than forkrun (1.0470x)	forkrun is 236.8% faster than parallel (3.3683x)	
md5sum      	1.4905172053	1.1924378260	1.1482506529	5.3374165641	xargs is 3.848% faster than forkrun (1.0384x)	forkrun is 347.6% faster than parallel (4.4760x)	
sum -s      	0.5135596115	0.4047147536	0.3565196903	4.9259558845	xargs is 13.51% faster than forkrun (1.1351x)	forkrun is 1117.% faster than parallel (12.171x)	
sum -r      	1.5110264779	1.2097741664	1.1709841545	5.3628440157	xargs is 3.312% faster than forkrun (1.0331x)	forkrun is 343.2% faster than parallel (4.4329x)	
cksum       	0.4525677526	0.3836583552	0.3490155784	4.9254489633	xargs is 29.66% faster than forkrun (1.2966x)	forkrun is 988.3% faster than parallel (10.883x)	
b2sum       	1.4513410377	1.3642071861	1.3115884534	5.3349616940	xargs is 10.65% faster than forkrun (1.1065x)	forkrun is 267.5% faster than parallel (3.6758x)	
cksum -a sm3	3.5812350354	4.0112135359	3.9960698332	5.9799603511	forkrun is 11.58% faster than xargs (1.1158x)	forkrun is 66.98% faster than parallel (1.6698x)	

OVERALL     	17.679301663	17.278236439	16.767843383	59.017477427	xargs is 5.435% faster than forkrun (1.0543x)	forkrun is 233.8% faster than parallel (3.3382x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.8309601974	3.1348596751	3.0158309621	12.468960908	forkrun is 6.530% faster than xargs (1.0653x)	forkrun is 340.4% faster than parallel (4.4044x)	
sha256sum   	5.5891415393	6.2265494598	5.9648955419	12.866310598	forkrun is 6.722% faster than xargs (1.0672x)	forkrun is 130.2% faster than parallel (2.3020x)	
sha512sum   	4.0353432110	4.4740216657	4.3003445363	12.709176534	forkrun is 6.567% faster than xargs (1.0656x)	forkrun is 214.9% faster than parallel (3.1494x)	
sha224sum   	5.6642231494	6.2218139375	5.9718326184	12.794395108	forkrun is 5.430% faster than xargs (1.0543x)	forkrun is 125.8% faster than parallel (2.2588x)	
sha384sum   	3.9482545919	4.4287364359	4.2642353406	12.696535459	forkrun is 8.003% faster than xargs (1.0800x)	forkrun is 221.5% faster than parallel (3.2157x)	
md5sum      	3.5724025772	3.589618096 	3.5616742688	12.755032532	xargs is .7845% faster than forkrun (1.0078x)	forkrun is 255.3% faster than parallel (3.5533x)	
sum -s      	0.9763332829	0.8894793827	0.8574476735	11.630226901	xargs is 3.735% faster than forkrun (1.0373x)	forkrun is 1207.% faster than parallel (13.075x)	
sum -r      	3.6829799327	3.7039768774	3.6439649553	12.561477830	xargs is 1.070% faster than forkrun (1.0107x)	forkrun is 241.0% faster than parallel (3.4106x)	
cksum       	0.8524876334	0.8077794064	0.7758177883	11.546945851	xargs is 9.882% faster than forkrun (1.0988x)	forkrun is 1254.% faster than parallel (13.545x)	
b2sum       	3.4682437692	3.8159986363	3.7050106611	12.650904000	forkrun is 6.826% faster than xargs (1.0682x)	forkrun is 264.7% faster than parallel (3.6476x)	
cksum -a sm3	10.046526181	11.393019556	10.945107920	14.694500090	forkrun is 8.944% faster than xargs (1.0894x)	forkrun is 46.26% faster than parallel (1.4626x)	

OVERALL     	44.666896065	48.685853129	47.006162267	139.37446581	forkrun is 5.237% faster than xargs (1.0523x)	forkrun is 212.0% faster than parallel (3.1203x)	



||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0729986337	0.0726438498	0.0786929481	0.1983686281	forkrun is 8.327% faster than xargs (1.0832x)	forkrun is 173.0% faster than parallel (2.7307x)	
sha256sum   	0.1178887940	0.1168175770	0.1450291328	0.2627680607	forkrun is 24.15% faster than xargs (1.2415x)	forkrun is 124.9% faster than parallel (2.2493x)	
sha512sum   	0.0915193727	0.0906166785	0.1069876558	0.2256129898	forkrun is 18.06% faster than xargs (1.1806x)	forkrun is 148.9% faster than parallel (2.4897x)	
sha224sum   	0.1179233142	0.1169606896	0.1452468845	0.2622281089	forkrun is 24.18% faster than xargs (1.2418x)	forkrun is 124.2% faster than parallel (2.2420x)	
sha384sum   	0.0912443234	0.0906186723	0.1063693690	0.2247533273	forkrun is 17.38% faster than xargs (1.1738x)	forkrun is 148.0% faster than parallel (2.4802x)	
md5sum      	0.0890070625	0.0884801455	0.1017645610	0.2206284252	forkrun is 15.01% faster than xargs (1.1501x)	forkrun is 149.3% faster than parallel (2.4935x)	
sum -s      	0.0382960702	0.0375444967	0.0290922474	0.1745926221	xargs is 29.05% faster than forkrun (1.2905x)	forkrun is 365.0% faster than parallel (4.6502x)	
sum -r      	0.0903426233	0.0892278013	0.1029232827	0.2222339852	forkrun is 15.34% faster than xargs (1.1534x)	forkrun is 149.0% faster than parallel (2.4906x)	
cksum       	0.0357433844	0.0357441551	0.0247579751	0.1746654816	xargs is 44.37% faster than forkrun (1.4437x)	forkrun is 388.6% faster than parallel (4.8866x)	
b2sum       	0.0837265595	0.0824956737	0.0950844795	0.2138713645	forkrun is 15.25% faster than xargs (1.1525x)	forkrun is 159.2% faster than parallel (2.5925x)	
cksum -a sm3	0.1889521545	0.1869790231	0.2506024359	0.3654057116	forkrun is 34.02% faster than xargs (1.3402x)	forkrun is 95.42% faster than parallel (1.9542x)	

OVERALL     	1.0176422929	1.0081287630	1.1865509724	2.5451287054	forkrun is 17.69% faster than xargs (1.1769x)	forkrun is 152.4% faster than parallel (2.5246x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0661840565	0.0631868848	0.0588007596	0.2228451395	xargs is 7.459% faster than forkrun (1.0745x)	forkrun is 252.6% faster than parallel (3.5267x)	
sha256sum   	0.0963305259	0.0916022730	0.0975863248	0.2299717529	forkrun is 1.303% faster than xargs (1.0130x)	forkrun is 138.7% faster than parallel (2.3873x)	
sha512sum   	0.0805619400	0.0760836137	0.0775900629	0.2237064444	forkrun is 1.979% faster than xargs (1.0197x)	forkrun is 194.0% faster than parallel (2.9402x)	
sha224sum   	0.0964376041	0.0913128407	0.0970756370	0.2291458685	forkrun is 6.311% faster than xargs (1.0631x)	forkrun is 150.9% faster than parallel (2.5094x)	
sha384sum   	0.0798627401	0.0753604621	0.0762725241	0.2250203377	forkrun is 1.210% faster than xargs (1.0121x)	forkrun is 198.5% faster than parallel (2.9859x)	
md5sum      	0.0767487221	0.0736241318	0.0718950337	0.2238975304	xargs is 2.405% faster than forkrun (1.0240x)	forkrun is 204.1% faster than parallel (3.0410x)	
sum -s      	0.0443827118	0.0418348287	0.0306547620	0.2226764882	xargs is 36.47% faster than forkrun (1.3647x)	forkrun is 432.2% faster than parallel (5.3227x)	
sum -r      	0.0775690764	0.0734637581	0.0722305178	0.2228000943	xargs is 1.707% faster than forkrun (1.0170x)	forkrun is 203.2% faster than parallel (3.0327x)	
cksum       	0.0419115283	0.0398853250	0.0272001378	0.2253928006	xargs is 46.63% faster than forkrun (1.4663x)	forkrun is 465.1% faster than parallel (5.6510x)	
b2sum       	0.0753628955	0.0714527820	0.0704799524	0.2231672891	xargs is 1.380% faster than forkrun (1.0138x)	forkrun is 212.3% faster than parallel (3.1232x)	
cksum -a sm3	0.1431032586	0.1343855719	0.1577156049	0.2682172314	forkrun is 17.36% faster than xargs (1.1736x)	forkrun is 99.58% faster than parallel (1.9958x)	

OVERALL     	.87845505997	.83219247238	.83750131755	2.5168409776	forkrun is .6379% faster than xargs (1.0063x)	forkrun is 202.4% faster than parallel (3.0243x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.1867448324	0.1925256920	0.2380598133	0.4720129827	forkrun is 23.65% faster than xargs (1.2365x)	forkrun is 145.1% faster than parallel (2.4516x)	
sha256sum   	0.3323020804	0.3560673562	0.4670436510	0.5526478979	forkrun is 40.54% faster than xargs (1.4054x)	forkrun is 66.30% faster than parallel (1.6630x)	
sha512sum   	0.2476502682	0.2617813669	0.3317568490	0.5032501588	forkrun is 33.96% faster than xargs (1.3396x)	forkrun is 103.2% faster than parallel (2.0321x)	
sha224sum   	0.3317256776	0.3354305875	0.4668105777	0.5530403535	forkrun is 40.72% faster than xargs (1.4072x)	forkrun is 66.71% faster than parallel (1.6671x)	
sha384sum   	0.2456154572	0.2564123029	0.3300655347	0.5018619060	forkrun is 34.38% faster than xargs (1.3438x)	forkrun is 104.3% faster than parallel (2.0432x)	
md5sum      	0.2364484285	0.2367402501	0.3187148050	0.4993174378	forkrun is 34.79% faster than xargs (1.3479x)	forkrun is 111.1% faster than parallel (2.1117x)	
sum -s      	0.0813095412	0.0757867676	0.0686493961	0.4527389800	xargs is 10.39% faster than forkrun (1.1039x)	forkrun is 497.3% faster than parallel (5.9738x)	
sum -r      	0.2395837506	0.2441211593	0.3246076297	0.5005592273	forkrun is 32.96% faster than xargs (1.3296x)	forkrun is 105.0% faster than parallel (2.0504x)	
cksum       	0.0723668135	0.0673458048	0.0547791618	0.4502455741	xargs is 22.94% faster than forkrun (1.2294x)	forkrun is 568.5% faster than parallel (6.6855x)	
b2sum       	0.2220254651	0.2296233435	0.2920454937	0.4894031238	forkrun is 31.53% faster than xargs (1.3153x)	forkrun is 120.4% faster than parallel (2.2042x)	
cksum -a sm3	0.5719156242	0.6161902771	0.8339167203	0.7736273921	forkrun is 45.81% faster than xargs (1.4581x)	forkrun is 35.26% faster than parallel (1.3526x)	

OVERALL     	2.7676879395	2.8720249084	3.7264496329	5.7487050346	forkrun is 34.64% faster than xargs (1.3464x)	forkrun is 107.7% faster than parallel (2.0770x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.3188421906	0.3115142043	0.2878229015	1.3675934002	xargs is 8.231% faster than forkrun (1.0823x)	forkrun is 339.0% faster than parallel (4.3901x)	
sha256sum   	0.5520720748	0.5269986288	0.5592056403	1.4373499917	forkrun is 6.111% faster than xargs (1.0611x)	forkrun is 172.7% faster than parallel (2.7274x)	
sha512sum   	0.4255231199	0.4094512303	0.4215202694	1.3790833710	xargs is .9496% faster than forkrun (1.0094x)	forkrun is 224.0% faster than parallel (3.2409x)	
sha224sum   	0.5509315116	0.5322249734	0.5597241668	1.4509291245	forkrun is 5.166% faster than xargs (1.0516x)	forkrun is 172.6% faster than parallel (2.7261x)	
sha384sum   	0.4167700093	0.4037181702	0.4077169996	1.3762411358	xargs is 2.220% faster than forkrun (1.0222x)	forkrun is 230.2% faster than parallel (3.3021x)	
md5sum      	0.3968155464	0.3218475585	0.3246737212	1.3788407814	forkrun is .8781% faster than xargs (1.0087x)	forkrun is 328.4% faster than parallel (4.2841x)	
sum -s      	0.1459912927	0.1285336372	0.1119777627	1.3393828703	xargs is 14.78% faster than forkrun (1.1478x)	forkrun is 942.0% faster than parallel (10.420x)	
sum -r      	0.3998616902	0.3247220793	0.3216046409	1.3761511865	xargs is 24.33% faster than forkrun (1.2433x)	forkrun is 244.1% faster than parallel (3.4415x)	
cksum       	0.1325361306	0.1196891365	0.1004428147	1.3338720147	xargs is 19.16% faster than forkrun (1.1916x)	forkrun is 1014.% faster than parallel (11.144x)	
b2sum       	0.3783354928	0.3568925008	0.3588872527	1.3690960464	forkrun is .5589% faster than xargs (1.0055x)	forkrun is 283.6% faster than parallel (3.8361x)	
cksum -a sm3	0.9199953053	0.9042869251	0.9624711546	1.5613788132	forkrun is 6.434% faster than xargs (1.0643x)	forkrun is 72.66% faster than parallel (1.7266x)	

OVERALL     	4.6376743646	4.3398790449	4.4160473249	15.369918736	forkrun is 1.755% faster than xargs (1.0175x)	forkrun is 254.1% faster than parallel (3.5415x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	1.1704894673	1.1107065274	1.0691515146	5.2061041091	xargs is 3.886% faster than forkrun (1.0388x)	forkrun is 368.7% faster than parallel (4.6872x)	
sha256sum   	2.0810340363	2.1616866236	2.1178840759	5.5625584077	forkrun is 1.770% faster than xargs (1.0177x)	forkrun is 167.2% faster than parallel (2.6729x)	
sha512sum   	1.5712303390	1.5798046690	1.5253792051	5.3614981377	xargs is 3.005% faster than forkrun (1.0300x)	forkrun is 241.2% faster than parallel (3.4122x)	
sha224sum   	2.0751290002	2.1641202502	2.1061915334	5.5500684137	forkrun is 1.496% faster than xargs (1.0149x)	forkrun is 167.4% faster than parallel (2.6745x)	
sha384sum   	1.5583065970	1.5692982709	1.5158686253	5.3623526620	xargs is 2.799% faster than forkrun (1.0279x)	forkrun is 244.1% faster than parallel (3.4411x)	
md5sum      	1.4693233844	1.1714122392	1.1320884441	5.3196362203	xargs is 3.473% faster than forkrun (1.0347x)	forkrun is 354.1% faster than parallel (4.5412x)	
sum -s      	0.4978460815	0.3944127100	0.3524637986	4.9250502378	xargs is 11.90% faster than forkrun (1.1190x)	forkrun is 1148.% faster than parallel (12.487x)	
sum -r      	1.4836370908	1.1997874949	1.1520724553	5.3356571619	xargs is 4.141% faster than forkrun (1.0414x)	forkrun is 344.7% faster than parallel (4.4471x)	
cksum       	0.4416305560	0.3767219117	0.3348299146	4.8794891111	xargs is 12.51% faster than forkrun (1.1251x)	forkrun is 1195.% faster than parallel (12.952x)	
b2sum       	1.4090221802	1.3412780263	1.2990854052	5.2827356441	xargs is 3.247% faster than forkrun (1.0324x)	forkrun is 293.8% faster than parallel (3.9385x)	
cksum -a sm3	3.5213136030	3.9984402990	3.9412410380	5.9216898061	xargs is 1.451% faster than forkrun (1.0145x)	forkrun is 48.09% faster than parallel (1.4809x)	

OVERALL     	17.278962336	17.067669022	16.546256010	58.706839911	xargs is 3.151% faster than forkrun (1.0315x)	forkrun is 243.9% faster than parallel (3.4396x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=586011 --------------------------------------------------------------------|| 

(algorithm)	(forkrun -j -)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.7309507643	3.1103351893	2.9844935873	12.41332715 	forkrun is 9.284% faster than xargs (1.0928x)	forkrun is 354.5% faster than parallel (4.5454x)	
sha256sum   	5.3296147975	6.2072761468	5.9253972546	12.732141631	forkrun is 11.17% faster than xargs (1.1117x)	forkrun is 138.8% faster than parallel (2.3889x)	
sha512sum   	3.8004267249	4.4250068973	4.2521185436	12.684383937	forkrun is 11.88% faster than xargs (1.1188x)	forkrun is 233.7% faster than parallel (3.3376x)	
sha224sum   	5.5165028142	6.1900941278	5.9161201206	12.850889940	forkrun is 7.244% faster than xargs (1.0724x)	forkrun is 132.9% faster than parallel (2.3295x)	
sha384sum   	3.9101034133	4.3804403290	4.2047813118	12.609324899	forkrun is 7.536% faster than xargs (1.0753x)	forkrun is 222.4% faster than parallel (3.2248x)	
md5sum      	3.4743035760	3.5756821862	3.5294740487	12.561923601	forkrun is 1.587% faster than xargs (1.0158x)	forkrun is 261.5% faster than parallel (3.6156x)	
sum -s      	0.9420243471	0.8687112248	0.8448194670	11.702274584	xargs is 11.50% faster than forkrun (1.1150x)	forkrun is 1142.% faster than parallel (12.422x)	
sum -r      	3.3638542904	3.6839243243	3.6146365134	12.809750503	forkrun is 7.455% faster than xargs (1.0745x)	forkrun is 280.8% faster than parallel (3.8080x)	
cksum       	0.8385388131	0.808976395 	0.7571104232	11.593888609	xargs is 6.850% faster than forkrun (1.0685x)	forkrun is 1333.% faster than parallel (14.331x)	
b2sum       	3.3800159260	3.8179004181	3.6568128422	12.746551755	forkrun is 8.189% faster than xargs (1.0818x)	forkrun is 277.1% faster than parallel (3.7711x)	
cksum -a sm3	9.4178972840	11.301512421	10.886795613	14.706000345	forkrun is 15.59% faster than xargs (1.1559x)	forkrun is 56.14% faster than parallel (1.5614x)	

OVERALL     	42.704232751	48.369859660	46.572559726	139.41045695	forkrun is 9.058% faster than xargs (1.0905x)	forkrun is 226.4% faster than parallel (3.2645x)	
```
