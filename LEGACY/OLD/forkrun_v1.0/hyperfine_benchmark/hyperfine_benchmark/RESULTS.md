OVERALL TOTAL EXECUTION TIME SUMMARY FOR EACH BATCHSIZE

Each of the times below is the average runtime time (in seconds) spend running all 11 checksums through the 5 input/output styles that ran correctly (note: in 1 of the 6 output styles `xargs` failed to run)

```
(num checksums)	(forkrun)     	(xargs)       	(parallel)    	(relative performance vs xargs)             	(relative performance vs parallel)          	
--------------	--------------	--------------	--------------	--------------------------------------------	-----------------------------------------------
10              0.0227788391    0.0046439318    0.1666755474    xargs is 390.5% faster than forkrun (4.9050x)   forkrun is 631.7% faster than parallel (7.3171x)
100             0.0240825549    0.0062289637    0.1985029397    xargs is 286.6% faster than forkrun (3.8662x)   forkrun is 724.2% faster than parallel (8.2426x)
1,000           0.0536750481    0.0521626456    0.2754509418    xargs is 2.899% faster than forkrun (1.0289x)   forkrun is 413.1% faster than parallel (5.1318x)
10,000          1.1015335085    2.3792354521    2.3092663411    forkrun is 115.9% faster than xargs (2.1599x)   forkrun is 109.6% faster than parallel (2.0964x)
100,000         1.3079962265    2.4872700863    4.1637657893    forkrun is 90.15% faster than xargs (1.9015x)   forkrun is 218.3% faster than parallel (3.1833x)
~520,000        2.7853083420    3.1558025588    20.575079126    forkrun is 13.30% faster than xargs (1.1330x)   forkrun is 638.7% faster than parallel (7.3870x)
```

***


INPUT FROM FILE  ----- OUTPUT TO STDOUT

```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=10 ------------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0222377524	0.0045663184	0.1663016086	xargs is 386.9% faster than forkrun (4.8699x)	forkrun is 647.8% faster than parallel (7.4783x)	
sha256sum   	0.0222945047	0.0046286744	0.1664678006	xargs is 381.6% faster than forkrun (4.8166x)	forkrun is 646.6% faster than parallel (7.4667x)	
sha512sum   	0.0222867294	0.0046388208	0.1660264187	xargs is 380.4% faster than forkrun (4.8043x)	forkrun is 644.9% faster than parallel (7.4495x)	
sha224sum   	0.0222631966	0.0046115288	0.1663650185	xargs is 382.7% faster than forkrun (4.8277x)	forkrun is 647.2% faster than parallel (7.4726x)	
sha384sum   	0.0222590017	0.0046319060	0.1660037465	xargs is 380.5% faster than forkrun (4.8055x)	forkrun is 645.7% faster than parallel (7.4578x)	
md5sum      	0.0222054445	0.0045680017	0.1661819254	xargs is 386.1% faster than forkrun (4.8610x)	forkrun is 648.3% faster than parallel (7.4838x)	
sum -s      	0.0218323122	0.0041602313	0.1665106637	xargs is 424.7% faster than forkrun (5.2478x)	forkrun is 662.6% faster than parallel (7.6267x)	
sum -r      	0.0218623687	0.0041749655	0.1660131393	xargs is 423.6% faster than forkrun (5.2365x)	forkrun is 659.3% faster than parallel (7.5935x)	
cksum       	0.0222997889	0.0045516597	0.1661293827	xargs is 389.9% faster than forkrun (4.8992x)	forkrun is 644.9% faster than parallel (7.4498x)	
b2sum       	0.0218900855	0.0042758768	0.1656956862	xargs is 411.9% faster than forkrun (5.1194x)	forkrun is 656.9% faster than parallel (7.5694x)	
cksum -a sm3	0.0222897355	0.0046546382	0.1671309791	xargs is 378.8% faster than forkrun (4.7887x)	forkrun is 649.8% faster than parallel (7.4981x)	

OVERALL     	.24372092063	.04946262216	1.8288263698	xargs is 392.7% faster than forkrun (4.9273x)	forkrun is 650.3% faster than parallel (7.5037x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100 -----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0235533085	0.0058983961	0.1980227966	xargs is 299.3% faster than forkrun (3.9931x)	forkrun is 740.7% faster than parallel (8.4074x)	
sha256sum   	0.0237179527	0.0063589133	0.1979132520	xargs is 272.9% faster than forkrun (3.7298x)	forkrun is 734.4% faster than parallel (8.3444x)	
sha512sum   	0.0237245718	0.0067177800	0.1977014673	xargs is 253.1% faster than forkrun (3.5316x)	forkrun is 733.3% faster than parallel (8.3331x)	
sha224sum   	0.0236643920	0.0063054685	0.1978414182	xargs is 275.2% faster than forkrun (3.7529x)	forkrun is 736.0% faster than parallel (8.3603x)	
sha384sum   	0.0237453105	0.0064657530	0.1976346737	xargs is 267.2% faster than forkrun (3.6724x)	forkrun is 732.3% faster than parallel (8.3231x)	
md5sum      	0.0235828748	0.0059184736	0.1980180813	xargs is 298.4% faster than forkrun (3.9846x)	forkrun is 739.6% faster than parallel (8.3966x)	
sum -s      	0.0227180197	0.0050908248	0.1973043993	xargs is 346.2% faster than forkrun (4.4625x)	forkrun is 768.4% faster than parallel (8.6849x)	
sum -r      	0.0227197390	0.0053681138	0.1977273307	xargs is 323.2% faster than forkrun (4.2323x)	forkrun is 770.2% faster than parallel (8.7028x)	
cksum       	0.0235218328	0.0053936551	0.1976200325	xargs is 336.1% faster than forkrun (4.3610x)	forkrun is 740.1% faster than parallel (8.4015x)	
b2sum       	0.0230455537	0.0062919115	0.1973906836	xargs is 266.2% faster than forkrun (3.6627x)	forkrun is 756.5% faster than parallel (8.5652x)	
cksum -a sm3	0.0237872031	0.0068073339	0.1996979108	xargs is 249.4% faster than forkrun (3.4943x)	forkrun is 739.5% faster than parallel (8.3951x)	

OVERALL     	.25778075910	.06661662403	2.1768720465	xargs is 286.9% faster than forkrun (3.8696x)	forkrun is 744.4% faster than parallel (8.4446x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=1000 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0451461852	0.0396901005	0.2665041519	xargs is 13.74% faster than forkrun (1.1374x)	forkrun is 490.3% faster than parallel (5.9031x)	
sha256sum   	0.0651223678	0.0660473760	0.2848145067	forkrun is 1.420% faster than xargs (1.0142x)	forkrun is 337.3% faster than parallel (4.3735x)	
sha512sum   	0.0538444930	0.0564962683	0.2736632631	forkrun is 4.924% faster than xargs (1.0492x)	forkrun is 408.2% faster than parallel (5.0824x)	
sha224sum   	0.0650039658	0.0653872189	0.2843648062	forkrun is .5895% faster than xargs (1.0058x)	forkrun is 337.4% faster than parallel (4.3745x)	
sha384sum   	0.0535297913	0.0538922841	0.2743005629	forkrun is .6771% faster than xargs (1.0067x)	forkrun is 412.4% faster than parallel (5.1242x)	
md5sum      	0.0520890359	0.0478073081	0.2734568949	xargs is 8.956% faster than forkrun (1.0895x)	forkrun is 424.9% faster than parallel (5.2497x)	
sum -s      	0.0282102095	0.0191471102	0.2541104080	xargs is 47.33% faster than forkrun (1.4733x)	forkrun is 800.7% faster than parallel (9.0077x)	
sum -r      	0.0484847961	0.0462704339	0.2736414361	xargs is 4.785% faster than forkrun (1.0478x)	forkrun is 464.3% faster than parallel (5.6438x)	
cksum       	0.0288720959	0.0171617271	0.2519632564	xargs is 68.23% faster than forkrun (1.6823x)	forkrun is 772.6% faster than parallel (8.7268x)	
b2sum       	0.0460599453	0.0518696914	0.2706297263	forkrun is 12.61% faster than xargs (1.1261x)	forkrun is 487.5% faster than parallel (5.8755x)	
cksum -a sm3	0.0953181611	0.1057605371	0.3178568454	forkrun is 10.95% faster than xargs (1.1095x)	forkrun is 233.4% faster than parallel (3.3346x)	

OVERALL     	.58168104753	.56953005604	3.0253058583	xargs is 2.133% faster than forkrun (1.0213x)	forkrun is 420.0% faster than parallel (5.2009x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=10000 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.7620162722	1.6270878501	1.6613388070	forkrun is 113.5% faster than xargs (2.1352x)	forkrun is 118.0% faster than parallel (2.1801x)	
sha256sum   	1.5333570598	3.3548540126	3.1010565568	forkrun is 118.7% faster than xargs (2.1879x)	forkrun is 102.2% faster than parallel (2.0223x)	
sha512sum   	1.0737960409	2.3090464603	2.2477956260	forkrun is 115.0% faster than xargs (2.1503x)	forkrun is 109.3% faster than parallel (2.0933x)	
sha224sum   	1.5365943395	3.2933599709	3.1105938611	forkrun is 114.3% faster than xargs (2.1432x)	forkrun is 102.4% faster than parallel (2.0243x)	
sha384sum   	1.0718901963	2.3193732105	2.2413819376	forkrun is 116.3% faster than xargs (2.1638x)	forkrun is 109.1% faster than parallel (2.0910x)	
md5sum      	1.0317493644	2.2141021672	2.1746745836	forkrun is 114.5% faster than xargs (2.1459x)	forkrun is 110.7% faster than parallel (2.1077x)	
sum -s      	0.1832966708	0.3764280070	0.6042527905	forkrun is 105.3% faster than xargs (2.0536x)	forkrun is 229.6% faster than parallel (3.2965x)	
sum -r      	1.0470785253	2.2662007536	2.2042221009	forkrun is 116.4% faster than xargs (2.1643x)	forkrun is 110.5% faster than parallel (2.1051x)	
cksum       	0.1397124466	0.2744103117	0.5547933697	forkrun is 96.41% faster than xargs (1.9641x)	forkrun is 297.0% faster than parallel (3.9709x)	
b2sum       	0.9421628113	2.0292200201	2.0057187787	forkrun is 115.3% faster than xargs (2.1537x)	forkrun is 112.8% faster than parallel (2.1288x)	
cksum -a sm3	2.8013964284	6.1459742338	5.4758338461	forkrun is 119.3% faster than xargs (2.1938x)	forkrun is 95.46% faster than parallel (1.9546x)	

OVERALL     	12.123050156	26.210056998	25.381662258	forkrun is 116.2% faster than xargs (2.1620x)	forkrun is 109.3% faster than parallel (2.0936x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100000 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.9202680402	1.7161194349	4.0236248078	forkrun is 86.48% faster than xargs (1.8648x)	forkrun is 337.2% faster than parallel (4.3722x)	
sha256sum   	1.8394063673	3.4934628744	4.0670355961	forkrun is 89.92% faster than xargs (1.8992x)	forkrun is 121.1% faster than parallel (2.2110x)	
sha512sum   	1.3044678595	2.4277218276	4.0303826109	forkrun is 86.10% faster than xargs (1.8610x)	forkrun is 208.9% faster than parallel (3.0896x)	
sha224sum   	1.8592680982	3.5076162535	4.0765211436	forkrun is 88.65% faster than xargs (1.8865x)	forkrun is 119.2% faster than parallel (2.1925x)	
sha384sum   	1.2927022868	2.4434492428	4.0521237459	forkrun is 89.01% faster than xargs (1.8901x)	forkrun is 213.4% faster than parallel (3.1346x)	
md5sum      	1.1002621377	2.2415301207	4.0181362059	forkrun is 103.7% faster than xargs (2.0372x)	forkrun is 265.1% faster than parallel (3.6519x)	
sum -s      	0.2396118404	0.3793680078	3.9648095688	forkrun is 58.32% faster than xargs (1.5832x)	forkrun is 1554.% faster than parallel (16.546x)	
sum -r      	1.0932652734	2.2806431216	4.0297452707	forkrun is 108.6% faster than xargs (2.0860x)	forkrun is 268.5% faster than parallel (3.6859x)	
cksum       	0.2013268040	0.2787265181	3.9833681501	forkrun is 38.44% faster than xargs (1.3844x)	forkrun is 1878.% faster than parallel (19.785x)	
b2sum       	1.1200221683	2.1314555970	4.0283365740	forkrun is 90.30% faster than xargs (1.9030x)	forkrun is 259.6% faster than parallel (3.5966x)	
cksum -a sm3	3.3684675102	6.3683435263	5.4871389848	forkrun is 89.05% faster than xargs (1.8905x)	forkrun is 62.89% faster than parallel (1.6289x)	

OVERALL     	14.339068386	27.268436525	45.761222659	forkrun is 90.16% faster than xargs (1.9016x)	forkrun is 219.1% faster than parallel (3.1913x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=522010 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.0571158239	2.2040375006	20.314837122	forkrun is 7.142% faster than xargs (1.0714x)	forkrun is 887.5% faster than parallel (9.8753x)	
sha256sum   	3.7843270503	4.2813825407	20.872955068	forkrun is 13.13% faster than xargs (1.1313x)	forkrun is 451.5% faster than parallel (5.5156x)	
sha512sum   	2.8519317981	3.0709240414	20.496019605	forkrun is 7.678% faster than xargs (1.0767x)	forkrun is 618.6% faster than parallel (7.1867x)	
sha224sum   	3.7590339801	4.2433865752	20.716018081	forkrun is 12.88% faster than xargs (1.1288x)	forkrun is 451.0% faster than parallel (5.5109x)	
sha384sum   	2.8107642080	3.0258673982	20.460134482	forkrun is 7.652% faster than xargs (1.0765x)	forkrun is 627.9% faster than parallel (7.2792x)	
md5sum      	2.1830456530	2.5326467154	20.394573050	forkrun is 16.01% faster than xargs (1.1601x)	forkrun is 834.2% faster than parallel (9.3422x)	
sum -s      	0.8194437731	1.1447559843	20.170015276	forkrun is 39.69% faster than xargs (1.3969x)	forkrun is 2361.% faster than parallel (24.614x)	
sum -r      	2.1290300618	2.5036896574	20.488248384	forkrun is 17.59% faster than xargs (1.1759x)	forkrun is 862.3% faster than parallel (9.6232x)	
cksum       	0.7580288722	1.1055919695	20.175004593	forkrun is 45.85% faster than xargs (1.4585x)	forkrun is 2561.% faster than parallel (26.615x)	
b2sum       	2.4926684622	2.6870063903	20.507451364	forkrun is 7.796% faster than xargs (1.0779x)	forkrun is 722.7% faster than parallel (8.2271x)	
cksum -a sm3	6.7353801919	7.8341456575	20.987708349	forkrun is 16.31% faster than xargs (1.1631x)	forkrun is 211.6% faster than parallel (3.1160x)	

OVERALL     	30.380769875	34.633434431	225.58296537	forkrun is 13.99% faster than xargs (1.1399x)	forkrun is 642.5% faster than parallel (7.4251x)	
```


***

INPUT FROM PIPE  ----- OUTPUT TO STDOUT


```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=10 ------------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0229730427	0.0047547235	0.1668187259	xargs is 383.1% faster than forkrun (4.8316x)	forkrun is 626.1% faster than parallel (7.2614x)	
sha256sum   	0.0230183538	0.0048051919	0.1667974056	xargs is 379.0% faster than forkrun (4.7903x)	forkrun is 624.6% faster than parallel (7.2462x)	
sha512sum   	0.0229981271	0.0048273882	0.1665456372	xargs is 376.4% faster than forkrun (4.7640x)	forkrun is 624.1% faster than parallel (7.2417x)	
sha224sum   	0.0229912110	0.0047992309	0.1668191199	xargs is 379.0% faster than forkrun (4.7906x)	forkrun is 625.5% faster than parallel (7.2557x)	
sha384sum   	0.0230223302	0.0048144724	0.1668341311	xargs is 378.1% faster than forkrun (4.7819x)	forkrun is 624.6% faster than parallel (7.2466x)	
md5sum      	0.0229918953	0.0047544307	0.1666682184	xargs is 383.5% faster than forkrun (4.8358x)	forkrun is 624.8% faster than parallel (7.2489x)	
sum -s      	0.0226407866	0.0043419812	0.1669355265	xargs is 421.4% faster than forkrun (5.2143x)	forkrun is 637.3% faster than parallel (7.3732x)	
sum -r      	0.0226124523	0.0043571015	0.1668199413	xargs is 418.9% faster than forkrun (5.1897x)	forkrun is 637.7% faster than parallel (7.3773x)	
cksum       	0.0230141699	0.0047269650	0.1664873765	xargs is 386.8% faster than forkrun (4.8686x)	forkrun is 623.4% faster than parallel (7.2341x)	
b2sum       	0.0226211120	0.0044566746	0.1663263153	xargs is 407.5% faster than forkrun (5.0757x)	forkrun is 635.2% faster than parallel (7.3527x)	
cksum -a sm3	0.0230862700	0.0048478455	0.1678346544	xargs is 376.2% faster than forkrun (4.7621x)	forkrun is 626.9% faster than parallel (7.2698x)	

OVERALL     	.25196975151	.05148600608	1.8348870526	xargs is 389.3% faster than forkrun (4.8939x)	forkrun is 628.2% faster than parallel (7.2821x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100 -----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0243211495	0.0060823646	0.1984730484	xargs is 299.8% faster than forkrun (3.9986x)	forkrun is 716.0% faster than parallel (8.1605x)	
sha256sum   	0.0244597743	0.0065578430	0.1987378297	xargs is 272.9% faster than forkrun (3.7298x)	forkrun is 712.5% faster than parallel (8.1250x)	
sha512sum   	0.0245089472	0.0068962498	0.1988230011	xargs is 255.3% faster than forkrun (3.5539x)	forkrun is 711.2% faster than parallel (8.1122x)	
sha224sum   	0.0244715175	0.0064941844	0.1984881743	xargs is 276.8% faster than forkrun (3.7682x)	forkrun is 711.0% faster than parallel (8.1109x)	
sha384sum   	0.0244832408	0.0066565885	0.1987845326	xargs is 267.8% faster than forkrun (3.6780x)	forkrun is 711.9% faster than parallel (8.1192x)	
md5sum      	0.0243290003	0.0061059925	0.1986968655	xargs is 298.4% faster than forkrun (3.9844x)	forkrun is 716.7% faster than parallel (8.1670x)	
sum -s      	0.0235149924	0.0052849767	0.1990507501	xargs is 344.9% faster than forkrun (4.4494x)	forkrun is 746.4% faster than parallel (8.4648x)	
sum -r      	0.0235692449	0.0055540846	0.1983807179	xargs is 324.3% faster than forkrun (4.2435x)	forkrun is 741.6% faster than parallel (8.4169x)	
cksum       	0.0242512669	0.0055819831	0.1984098829	xargs is 334.4% faster than forkrun (4.3445x)	forkrun is 718.1% faster than parallel (8.1814x)	
b2sum       	0.0237712758	0.0064797153	0.1978847743	xargs is 266.8% faster than forkrun (3.6685x)	forkrun is 732.4% faster than parallel (8.3245x)	
cksum -a sm3	0.0246976749	0.0070177611	0.2003879735	xargs is 251.9% faster than forkrun (3.5193x)	forkrun is 711.3% faster than parallel (8.1136x)	

OVERALL     	.26637808487	.06871174411	2.1861175508	xargs is 287.6% faster than forkrun (3.8767x)	forkrun is 720.6% faster than parallel (8.2068x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=1000 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0457228936	0.0398948392	0.2671049395	xargs is 14.60% faster than forkrun (1.1460x)	forkrun is 484.1% faster than parallel (5.8418x)	
sha256sum   	0.0660907037	0.0662485552	0.2853667228	forkrun is .2388% faster than xargs (1.0023x)	forkrun is 331.7% faster than parallel (4.3178x)	
sha512sum   	0.0549399465	0.0566446667	0.2747656012	forkrun is 3.102% faster than xargs (1.0310x)	forkrun is 400.1% faster than parallel (5.0011x)	
sha224sum   	0.0657661591	0.0656940858	0.2858267707	xargs is .1097% faster than forkrun (1.0010x)	forkrun is 334.6% faster than parallel (4.3461x)	
sha384sum   	0.0547736194	0.0541311071	0.2749397107	xargs is 1.186% faster than forkrun (1.0118x)	forkrun is 401.9% faster than parallel (5.0195x)	
md5sum      	0.0528687239	0.0481368739	0.273963166 	xargs is 9.829% faster than forkrun (1.0982x)	forkrun is 418.1% faster than parallel (5.1819x)	
sum -s      	0.0290077762	0.0193777365	0.2540113294	xargs is 49.69% faster than forkrun (1.4969x)	forkrun is 775.6% faster than parallel (8.7566x)	
sum -r      	0.0494525733	0.0464824014	0.2739770579	xargs is 6.389% faster than forkrun (1.0638x)	forkrun is 454.0% faster than parallel (5.5401x)	
cksum       	0.0296535389	0.0173852585	0.2524184813	xargs is 70.56% faster than forkrun (1.7056x)	forkrun is 751.2% faster than parallel (8.5122x)	
b2sum       	0.0469104380	0.0521509948	0.2709629662	forkrun is 11.17% faster than xargs (1.1117x)	forkrun is 477.6% faster than parallel (5.7761x)	
cksum -a sm3	0.0971732757	0.1058590736	0.3171372918	forkrun is 8.938% faster than xargs (1.0893x)	forkrun is 226.3% faster than parallel (3.2636x)	

OVERALL     	.59235964886	.57200559351	3.0304740380	xargs is 3.558% faster than forkrun (1.0355x)	forkrun is 411.5% faster than parallel (5.1159x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=10000 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.7624861964	1.6195050819	1.6631891732	forkrun is 112.3% faster than xargs (2.1239x)	forkrun is 118.1% faster than parallel (2.1812x)	
sha256sum   	1.5372545456	3.2986518631	3.1194161629	forkrun is 114.5% faster than xargs (2.1458x)	forkrun is 102.9% faster than parallel (2.0292x)	
sha512sum   	1.0688103644	2.3111842328	2.2552146571	forkrun is 116.2% faster than xargs (2.1623x)	forkrun is 111.0% faster than parallel (2.1100x)	
sha224sum   	1.5386713966	3.3035039677	3.1045349122	forkrun is 114.6% faster than xargs (2.1469x)	forkrun is 101.7% faster than parallel (2.0176x)	
sha384sum   	1.0712067199	2.3039208710	2.2364389415	forkrun is 115.0% faster than xargs (2.1507x)	forkrun is 108.7% faster than parallel (2.0877x)	
md5sum      	1.0255189009	2.2290864607	2.1886308437	forkrun is 117.3% faster than xargs (2.1736x)	forkrun is 113.4% faster than parallel (2.1341x)	
sum -s      	0.1835417876	0.3752127934	0.6028489297	forkrun is 104.4% faster than xargs (2.0442x)	forkrun is 228.4% faster than parallel (3.2845x)	
sum -r      	1.0473708425	2.2623396624	2.2075062975	forkrun is 116.0% faster than xargs (2.1600x)	forkrun is 110.7% faster than parallel (2.1076x)	
cksum       	0.1413519174	0.2742231768	0.5542920155	forkrun is 94.00% faster than xargs (1.9400x)	forkrun is 292.1% faster than parallel (3.9213x)	
b2sum       	0.9408920712	2.0478216237	2.0158959615	forkrun is 117.6% faster than xargs (2.1764x)	forkrun is 114.2% faster than parallel (2.1425x)	
cksum -a sm3	2.7843363316	6.1733692277	5.4908321856	forkrun is 121.7% faster than xargs (2.2171x)	forkrun is 97.20% faster than parallel (1.9720x)	

OVERALL     	12.101441074	26.198818961	25.438800080	forkrun is 116.4% faster than xargs (2.1649x)	forkrun is 110.2% faster than parallel (2.1021x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100000 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.9180331921	1.7216148815	3.9878623549	forkrun is 87.53% faster than xargs (1.8753x)	forkrun is 334.3% faster than parallel (4.3439x)	
sha256sum   	1.8450190693	3.4802436552	4.1085687235	forkrun is 88.62% faster than xargs (1.8862x)	forkrun is 122.6% faster than parallel (2.2268x)	
sha512sum   	1.3223007028	2.4509078173	4.0553967754	forkrun is 85.35% faster than xargs (1.8535x)	forkrun is 206.6% faster than parallel (3.0669x)	
sha224sum   	1.8592434832	3.4626035674	4.0679871256	forkrun is 86.23% faster than xargs (1.8623x)	forkrun is 118.7% faster than parallel (2.1879x)	
sha384sum   	1.3029478693	2.4482405600	4.0839102418	forkrun is 87.90% faster than xargs (1.8790x)	forkrun is 213.4% faster than parallel (3.1343x)	
md5sum      	1.0935568866	2.2513618074	4.0266534106	forkrun is 105.8% faster than xargs (2.0587x)	forkrun is 268.2% faster than parallel (3.6821x)	
sum -s      	0.2401237053	0.3802703567	3.9851096138	forkrun is 58.36% faster than xargs (1.5836x)	forkrun is 1559.% faster than parallel (16.596x)	
sum -r      	1.0930149927	2.2989727443	4.0391864326	forkrun is 110.3% faster than xargs (2.1033x)	forkrun is 269.5% faster than parallel (3.6954x)	
cksum       	0.2024001496	0.2799796694	3.9812764242	forkrun is 38.32% faster than xargs (1.3832x)	forkrun is 1867.% faster than parallel (19.670x)	
b2sum       	1.1409619528	2.1360794496	4.0317975151	forkrun is 87.21% faster than xargs (1.8721x)	forkrun is 253.3% faster than parallel (3.5336x)	
cksum -a sm3	3.3649730722	6.3470871685	5.4729623503	forkrun is 88.62% faster than xargs (1.8862x)	forkrun is 62.64% faster than parallel (1.6264x)	

OVERALL     	14.382575076	27.257361677	45.840710968	forkrun is 89.51% faster than xargs (1.8951x)	forkrun is 218.7% faster than parallel (3.1872x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=522010 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.0842424387	2.1883220302	20.516518090	forkrun is 4.993% faster than xargs (1.0499x)	forkrun is 884.3% faster than parallel (9.8436x)	
sha256sum   	3.7958112444	4.2580688392	20.805522400	forkrun is 12.17% faster than xargs (1.1217x)	forkrun is 448.1% faster than parallel (5.4811x)	
sha512sum   	2.8814886665	3.0769515445	20.675075905	forkrun is 6.783% faster than xargs (1.0678x)	forkrun is 617.5% faster than parallel (7.1751x)	
sha224sum   	3.7785861648	4.2250256307	20.892822990	forkrun is 11.81% faster than xargs (1.1181x)	forkrun is 452.9% faster than parallel (5.5292x)	
sha384sum   	2.8260537681	3.0181341583	20.583710216	forkrun is 6.796% faster than xargs (1.0679x)	forkrun is 628.3% faster than parallel (7.2835x)	
md5sum      	2.1885709605	2.5295291093	20.477023449	forkrun is 15.57% faster than xargs (1.1557x)	forkrun is 835.6% faster than parallel (9.3563x)	
sum -s      	0.8251793345	1.1462083216	20.149757129	forkrun is 38.90% faster than xargs (1.3890x)	forkrun is 2341.% faster than parallel (24.418x)	
sum -r      	2.1096534477	2.5092561971	20.620898800	forkrun is 18.94% faster than xargs (1.1894x)	forkrun is 877.4% faster than parallel (9.7745x)	
cksum       	0.7566898934	1.1039906649	20.131663705	forkrun is 45.89% faster than xargs (1.4589x)	forkrun is 2560.% faster than parallel (26.604x)	
b2sum       	2.5021767170	2.6500262237	20.576326814	forkrun is 5.908% faster than xargs (1.0590x)	forkrun is 722.3% faster than parallel (8.2233x)	
cksum -a sm3	6.7598876319	7.7512274280	20.957587340	forkrun is 14.66% faster than xargs (1.1466x)	forkrun is 210.0% faster than parallel (3.1002x)	

OVERALL     	30.508340267	34.456740148	226.38690684	forkrun is 12.94% faster than xargs (1.1294x)	forkrun is 642.0% faster than parallel (7.4204x)	
```


***

INPUT FROM FILE  ----- OUTPUT TO PIPE


```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=10 ------------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0229292788	0.0046924363	0.1665696408	xargs is 388.6% faster than forkrun (4.8864x)	forkrun is 626.4% faster than parallel (7.2644x)	
sha256sum   	0.0229742973	0.0047395762	0.1668132902	xargs is 384.7% faster than forkrun (4.8473x)	forkrun is 626.0% faster than parallel (7.2608x)	
sha512sum   	0.0229789876	0.0047687597	0.1664363919	xargs is 381.8% faster than forkrun (4.8186x)	forkrun is 624.2% faster than parallel (7.2429x)	
sha224sum   	0.0229695319	0.0047173203	0.1665830975	xargs is 386.9% faster than forkrun (4.8691x)	forkrun is 625.2% faster than parallel (7.2523x)	
sha384sum   	0.0230215809	0.0047442956	0.1665338846	xargs is 385.2% faster than forkrun (4.8524x)	forkrun is 623.3% faster than parallel (7.2338x)	
md5sum      	0.0229552350	0.0046797884	0.1665035764	xargs is 390.5% faster than forkrun (4.9051x)	forkrun is 625.3% faster than parallel (7.2534x)	
sum -s      	0.0226921698	0.0042731686	0.1665060257	xargs is 431.0% faster than forkrun (5.3103x)	forkrun is 633.7% faster than parallel (7.3375x)	
sum -r      	0.0226549280	0.0043018848	0.1665368774	xargs is 426.6% faster than forkrun (5.2662x)	forkrun is 635.1% faster than parallel (7.3510x)	
cksum       	0.0229740281	0.0046701716	0.1667300189	xargs is 391.9% faster than forkrun (4.9193x)	forkrun is 625.7% faster than parallel (7.2573x)	
b2sum       	0.0226056693	0.0043885315	0.1658945737	xargs is 415.1% faster than forkrun (5.1510x)	forkrun is 633.8% faster than parallel (7.3386x)	
cksum -a sm3	0.0231220632	0.0047855957	0.1675018377	xargs is 383.1% faster than forkrun (4.8315x)	forkrun is 624.4% faster than parallel (7.2442x)	

OVERALL     	.25187777035	.05076152919	1.8326092153	xargs is 396.1% faster than forkrun (4.9619x)	forkrun is 627.5% faster than parallel (7.2757x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100 -----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0243339369	0.0060846061	0.1986035060	xargs is 299.9% faster than forkrun (3.9992x)	forkrun is 716.1% faster than parallel (8.1615x)	
sha256sum   	0.0244599084	0.0065410769	0.1985038450	xargs is 273.9% faster than forkrun (3.7394x)	forkrun is 711.5% faster than parallel (8.1154x)	
sha512sum   	0.0244422583	0.0068797303	0.1985443721	xargs is 255.2% faster than forkrun (3.5527x)	forkrun is 712.2% faster than parallel (8.1229x)	
sha224sum   	0.0244623237	0.0064814898	0.1991228478	xargs is 277.4% faster than forkrun (3.7741x)	forkrun is 713.9% faster than parallel (8.1399x)	
sha384sum   	0.0244553698	0.0066433471	0.1986069325	xargs is 268.1% faster than forkrun (3.6811x)	forkrun is 712.1% faster than parallel (8.1211x)	
md5sum      	0.0243130405	0.0060914560	0.1986853089	xargs is 299.1% faster than forkrun (3.9913x)	forkrun is 717.1% faster than parallel (8.1719x)	
sum -s      	0.0235292529	0.0052606770	0.1984217317	xargs is 347.2% faster than forkrun (4.4726x)	forkrun is 743.2% faster than parallel (8.4329x)	
sum -r      	0.0235798159	0.0055447724	0.1985418041	xargs is 325.2% faster than forkrun (4.2526x)	forkrun is 741.9% faster than parallel (8.4199x)	
cksum       	0.0242580923	0.0055707648	0.1981838249	xargs is 335.4% faster than forkrun (4.3545x)	forkrun is 716.9% faster than parallel (8.1698x)	
b2sum       	0.0238345758	0.0064752279	0.1975779444	xargs is 268.0% faster than forkrun (3.6808x)	forkrun is 728.9% faster than parallel (8.2895x)	
cksum -a sm3	0.0246856534	0.0069912436	0.2000560296	xargs is 253.0% faster than forkrun (3.5309x)	forkrun is 710.4% faster than parallel (8.1041x)	

OVERALL     	.26635422833	.06856439251	2.1848481474	xargs is 288.4% faster than forkrun (3.8847x)	forkrun is 720.2% faster than parallel (8.2027x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=1000 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0462139084	0.0403902777	0.2670734795	xargs is 14.41% faster than forkrun (1.1441x)	forkrun is 477.9% faster than parallel (5.7790x)	
sha256sum   	0.0658880716	0.0667314953	0.2852905603	forkrun is 1.280% faster than xargs (1.0128x)	forkrun is 332.9% faster than parallel (4.3299x)	
sha512sum   	0.0551459911	0.0571528935	0.2746432969	forkrun is 3.639% faster than xargs (1.0363x)	forkrun is 398.0% faster than parallel (4.9802x)	
sha224sum   	0.0658181418	0.0660825522	0.2857276528	forkrun is .4017% faster than xargs (1.0040x)	forkrun is 334.1% faster than parallel (4.3411x)	
sha384sum   	0.0547233892	0.0545932806	0.2743561164	xargs is .2383% faster than forkrun (1.0023x)	forkrun is 401.3% faster than parallel (5.0135x)	
md5sum      	0.0527673461	0.0485608489	0.2738811853	xargs is 8.662% faster than forkrun (1.0866x)	forkrun is 419.0% faster than parallel (5.1903x)	
sum -s      	0.0290571002	0.0198893678	0.2542807655	xargs is 46.09% faster than forkrun (1.4609x)	forkrun is 775.1% faster than parallel (8.7510x)	
sum -r      	0.0494456306	0.0469737655	0.2743087107	xargs is 5.262% faster than forkrun (1.0526x)	forkrun is 454.7% faster than parallel (5.5476x)	
cksum       	0.0296706909	0.0178819799	0.2523294215	xargs is 65.92% faster than forkrun (1.6592x)	forkrun is 750.4% faster than parallel (8.5043x)	
b2sum       	0.0467627360	0.0525421831	0.2708691439	forkrun is 12.35% faster than xargs (1.1235x)	forkrun is 479.2% faster than parallel (5.7924x)	
cksum -a sm3	0.0972913657	0.1062407583	0.3158001299	forkrun is 9.198% faster than xargs (1.0919x)	forkrun is 224.5% faster than parallel (3.2459x)	

OVERALL     	.59278437227	.57703940340	3.0285604631	xargs is 2.728% faster than forkrun (1.0272x)	forkrun is 410.9% faster than parallel (5.1090x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=10000 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.7649563589	1.6253560728	1.6679656952	forkrun is 112.4% faster than xargs (2.1247x)	forkrun is 118.0% faster than parallel (2.1804x)	
sha256sum   	1.5314496526	3.3192834362	3.1252836424	forkrun is 116.7% faster than xargs (2.1674x)	forkrun is 104.0% faster than parallel (2.0407x)	
sha512sum   	1.0690963877	2.3264417311	2.2431628561	forkrun is 117.6% faster than xargs (2.1760x)	forkrun is 109.8% faster than parallel (2.0981x)	
sha224sum   	1.5340270029	3.3352521440	3.1309009196	forkrun is 117.4% faster than xargs (2.1741x)	forkrun is 104.0% faster than parallel (2.0409x)	
sha384sum   	1.0778530264	2.2954346765	2.2385734043	forkrun is 112.9% faster than xargs (2.1296x)	forkrun is 107.6% faster than parallel (2.0768x)	
md5sum      	1.0329583320	2.2268215438	2.1857525732	forkrun is 115.5% faster than xargs (2.1557x)	forkrun is 111.6% faster than parallel (2.1160x)	
sum -s      	0.1858685453	0.3772697206	0.6026116649	forkrun is 102.9% faster than xargs (2.0297x)	forkrun is 224.2% faster than parallel (3.2421x)	
sum -r      	1.0487807199	2.2657737040	2.2163017151	forkrun is 116.0% faster than xargs (2.1603x)	forkrun is 111.3% faster than parallel (2.1132x)	
cksum       	0.1412699149	0.2747798361	0.5550540164	forkrun is 94.50% faster than xargs (1.9450x)	forkrun is 292.9% faster than parallel (3.9290x)	
b2sum       	0.9466178981	2.0466932144	2.0139015326	forkrun is 116.2% faster than xargs (2.1621x)	forkrun is 112.7% faster than parallel (2.1274x)	
cksum -a sm3	2.7965038614	6.1169286586	5.4532073951	forkrun is 118.7% faster than xargs (2.1873x)	forkrun is 95.00% faster than parallel (1.9500x)	

OVERALL     	12.129381700	26.210034738	25.432715415	forkrun is 116.0% faster than xargs (2.1608x)	forkrun is 109.6% faster than parallel (2.0967x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100000 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.9227479418	1.7177944883	4.0091988415	forkrun is 86.16% faster than xargs (1.8616x)	forkrun is 334.4% faster than parallel (4.3448x)	
sha256sum   	1.8324266172	3.4915438737	4.0868635695	forkrun is 90.54% faster than xargs (1.9054x)	forkrun is 123.0% faster than parallel (2.2303x)	
sha512sum   	1.3020629073	2.4697763413	4.0293482395	forkrun is 89.68% faster than xargs (1.8968x)	forkrun is 209.4% faster than parallel (3.0945x)	
sha224sum   	1.8508158727	3.5144779267	4.1077198512	forkrun is 89.88% faster than xargs (1.8988x)	forkrun is 121.9% faster than parallel (2.2194x)	
sha384sum   	1.3143506249	2.4585479328	4.0428192432	forkrun is 87.05% faster than xargs (1.8705x)	forkrun is 207.5% faster than parallel (3.0759x)	
md5sum      	1.1013572566	2.2769853193	4.0511829638	forkrun is 106.7% faster than xargs (2.0674x)	forkrun is 267.8% faster than parallel (3.6783x)	
sum -s      	0.2554140616	0.3814709167	3.9901401496	forkrun is 49.35% faster than xargs (1.4935x)	forkrun is 1462.% faster than parallel (15.622x)	
sum -r      	1.0944244897	2.2933078204	4.0609666014	forkrun is 109.5% faster than xargs (2.0954x)	forkrun is 271.0% faster than parallel (3.7105x)	
cksum       	0.2055764539	0.2814145205	3.9827615345	forkrun is 36.89% faster than xargs (1.3689x)	forkrun is 1837.% faster than parallel (19.373x)	
b2sum       	1.1459432496	2.1345872551	4.0829005542	forkrun is 86.27% faster than xargs (1.8627x)	forkrun is 256.2% faster than parallel (3.5629x)	
cksum -a sm3	3.4058965237	6.4567288859	5.4881287496	forkrun is 89.57% faster than xargs (1.8957x)	forkrun is 61.13% faster than parallel (1.6113x)	

OVERALL     	14.431015999	27.476635281	45.932030298	forkrun is 90.39% faster than xargs (1.9039x)	forkrun is 218.2% faster than parallel (3.1828x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=522010 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.1136272223	2.2215930383	20.425598489	forkrun is 5.108% faster than xargs (1.0510x)	forkrun is 866.3% faster than parallel (9.6637x)	
sha256sum   	3.8247524220	4.3009769740	20.835360247	forkrun is 12.45% faster than xargs (1.1245x)	forkrun is 444.7% faster than parallel (5.4475x)	
sha512sum   	2.9101246413	3.1331726638	20.719683192	forkrun is 7.664% faster than xargs (1.0766x)	forkrun is 611.9% faster than parallel (7.1198x)	
sha224sum   	3.8343963786	4.2723586362	20.831064612	forkrun is 11.42% faster than xargs (1.1142x)	forkrun is 443.2% faster than parallel (5.4326x)	
sha384sum   	2.8771318624	3.0688150158	20.552890569	forkrun is 6.662% faster than xargs (1.0666x)	forkrun is 614.3% faster than parallel (7.1435x)	
md5sum      	2.2219601388	2.5798460929	20.512520100	forkrun is 16.10% faster than xargs (1.1610x)	forkrun is 823.1% faster than parallel (9.2317x)	
sum -s      	0.8361695303	1.1487778019	20.174301693	forkrun is 37.38% faster than xargs (1.3738x)	forkrun is 2312.% faster than parallel (24.127x)	
sum -r      	2.1537532938	2.5285231198	20.509494695	forkrun is 17.40% faster than xargs (1.1740x)	forkrun is 852.2% faster than parallel (9.5226x)	
cksum       	0.7735290011	1.1067143971	20.103364146	forkrun is 43.07% faster than xargs (1.4307x)	forkrun is 2498.% faster than parallel (25.989x)	
b2sum       	2.5437484255	2.7335098856	20.634031907	forkrun is 7.459% faster than xargs (1.0745x)	forkrun is 711.1% faster than parallel (8.1116x)	
cksum -a sm3	6.8171996580	7.8484889203	21.076451093	forkrun is 15.12% faster than xargs (1.1512x)	forkrun is 209.1% faster than parallel (3.0916x)	

OVERALL     	30.906392574	34.942776546	226.37476074	forkrun is 13.06% faster than xargs (1.1306x)	forkrun is 632.4% faster than parallel (7.3245x)	
```


***

INPUT FROM PIPE  ----- OUTPUT TO PIPE


```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=10 ------------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0231499716	0.0047909433	0.1666674406	xargs is 383.2% faster than forkrun (4.8320x)	forkrun is 619.9% faster than parallel (7.1994x)	
sha256sum   	0.0231546809	0.0048400190	0.1670806389	xargs is 378.4% faster than forkrun (4.7840x)	forkrun is 621.5% faster than parallel (7.2158x)	
sha512sum   	0.0231765253	0.0048738338	0.1668510721	xargs is 375.5% faster than forkrun (4.7552x)	forkrun is 619.9% faster than parallel (7.1991x)	
sha224sum   	0.0231554821	0.0048356209	0.1669740612	xargs is 378.8% faster than forkrun (4.7885x)	forkrun is 621.0% faster than parallel (7.2109x)	
sha384sum   	0.0231807938	0.0048589587	0.1670587361	xargs is 377.0% faster than forkrun (4.7707x)	forkrun is 620.6% faster than parallel (7.2067x)	
md5sum      	0.0231530631	0.0047911945	0.1668042064	xargs is 383.2% faster than forkrun (4.8324x)	forkrun is 620.4% faster than parallel (7.2044x)	
sum -s      	0.0227551735	0.0043795605	0.1667375197	xargs is 419.5% faster than forkrun (5.1957x)	forkrun is 632.7% faster than parallel (7.3274x)	
sum -r      	0.0227435645	0.0044021803	0.1670541102	xargs is 416.6% faster than forkrun (5.1664x)	forkrun is 634.5% faster than parallel (7.3451x)	
cksum       	0.0231639715	0.0047774798	0.1668719568	xargs is 384.8% faster than forkrun (4.8485x)	forkrun is 620.3% faster than parallel (7.2039x)	
b2sum       	0.0227626701	0.0044999392	0.1663414921	xargs is 405.8% faster than forkrun (5.0584x)	forkrun is 630.7% faster than parallel (7.3076x)	
cksum -a sm3	0.0231477188	0.0048801963	0.1678300929	xargs is 374.3% faster than forkrun (4.7431x)	forkrun is 625.0% faster than parallel (7.2503x)	

OVERALL     	.25354361588	.05192992671	1.8362713275	xargs is 388.2% faster than forkrun (4.8824x)	forkrun is 624.2% faster than parallel (7.2424x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100 -----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0244846660	0.0061765705	0.1986982076	xargs is 296.4% faster than forkrun (3.9641x)	forkrun is 711.5% faster than parallel (8.1152x)	
sha256sum   	0.0246197234	0.0066374353	0.1984002326	xargs is 270.9% faster than forkrun (3.7092x)	forkrun is 705.8% faster than parallel (8.0585x)	
sha512sum   	0.0246623778	0.0069999134	0.1987319402	xargs is 252.3% faster than forkrun (3.5232x)	forkrun is 705.8% faster than parallel (8.0581x)	
sha224sum   	0.0246183721	0.0065758470	0.1987905543	xargs is 274.3% faster than forkrun (3.7437x)	forkrun is 707.4% faster than parallel (8.0748x)	
sha384sum   	0.0246452454	0.0067504154	0.1986330879	xargs is 265.0% faster than forkrun (3.6509x)	forkrun is 705.9% faster than parallel (8.0596x)	
md5sum      	0.0244910368	0.0062007179	0.1985521579	xargs is 294.9% faster than forkrun (3.9497x)	forkrun is 710.7% faster than parallel (8.1071x)	
sum -s      	0.0236382154	0.0053653361	0.1985966521	xargs is 340.5% faster than forkrun (4.4057x)	forkrun is 740.1% faster than parallel (8.4015x)	
sum -r      	0.0237266020	0.0056415403	0.1983503761	xargs is 320.5% faster than forkrun (4.2056x)	forkrun is 735.9% faster than parallel (8.3598x)	
cksum       	0.0244145969	0.0056863663	0.1986853694	xargs is 329.3% faster than forkrun (4.2935x)	forkrun is 713.7% faster than parallel (8.1379x)	
b2sum       	0.0239936464	0.0065734214	0.1978815769	xargs is 265.0% faster than forkrun (3.6501x)	forkrun is 724.7% faster than parallel (8.2472x)	
cksum -a sm3	0.0247143357	0.0070968473	0.2002376482	xargs is 248.2% faster than forkrun (3.4824x)	forkrun is 710.2% faster than parallel (8.1020x)	

OVERALL     	.26800881855	.06970441144	2.1855578037	xargs is 284.4% faster than forkrun (3.8449x)	forkrun is 715.4% faster than parallel (8.1547x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=1000 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0463380574	0.0405328752	0.2677786017	xargs is 14.32% faster than forkrun (1.1432x)	forkrun is 477.8% faster than parallel (5.7788x)	
sha256sum   	0.0659891776	0.0668568579	0.2858918142	forkrun is 1.314% faster than xargs (1.0131x)	forkrun is 333.2% faster than parallel (4.3324x)	
sha512sum   	0.0553138512	0.0572195494	0.2755010819	forkrun is 3.445% faster than xargs (1.0344x)	forkrun is 398.0% faster than parallel (4.9806x)	
sha224sum   	0.0656461099	0.0661533347	0.2856524050	forkrun is .7726% faster than xargs (1.0077x)	forkrun is 335.1% faster than parallel (4.3513x)	
sha384sum   	0.0549546228	0.0547520458	0.2750490084	xargs is .3699% faster than forkrun (1.0036x)	forkrun is 400.5% faster than parallel (5.0050x)	
md5sum      	0.0529038907	0.0486888989	0.2739038147	xargs is 8.656% faster than forkrun (1.0865x)	forkrun is 417.7% faster than parallel (5.1773x)	
sum -s      	0.0290142411	0.0199756791	0.2542569240	xargs is 45.24% faster than forkrun (1.4524x)	forkrun is 776.3% faster than parallel (8.7631x)	
sum -r      	0.0495555380	0.0471048979	0.2746378897	xargs is 5.202% faster than forkrun (1.0520x)	forkrun is 454.2% faster than parallel (5.5420x)	
cksum       	0.0299344922	0.0179835109	0.2527444839	xargs is 66.45% faster than forkrun (1.6645x)	forkrun is 744.3% faster than parallel (8.4432x)	
b2sum       	0.0468492001	0.0526195957	0.2712135576	forkrun is 12.31% faster than xargs (1.1231x)	forkrun is 478.9% faster than parallel (5.7890x)	
cksum -a sm3	0.0972081874	0.1064036053	0.3169613867	forkrun is 9.459% faster than xargs (1.0945x)	forkrun is 226.0% faster than parallel (3.2606x)	

OVERALL     	.59370736895	.57829085119	3.0335909682	xargs is 2.665% faster than forkrun (1.0266x)	forkrun is 410.9% faster than parallel (5.1095x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=10000 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.7646385667	1.6193085808	1.6758004103	forkrun is 111.7% faster than xargs (2.1177x)	forkrun is 119.1% faster than parallel (2.1916x)	
sha256sum   	1.550133203 	3.3000803833	3.1040116119	forkrun is 112.8% faster than xargs (2.1289x)	forkrun is 100.2% faster than parallel (2.0024x)	
sha512sum   	1.0729604020	2.3112897411	2.2539543551	forkrun is 115.4% faster than xargs (2.1541x)	forkrun is 110.0% faster than parallel (2.1006x)	
sha224sum   	1.5406370298	3.3211256926	3.1184155761	forkrun is 115.5% faster than xargs (2.1556x)	forkrun is 102.4% faster than parallel (2.0241x)	
sha384sum   	1.0699332888	2.2996565860	2.2523285529	forkrun is 114.9% faster than xargs (2.1493x)	forkrun is 110.5% faster than parallel (2.1051x)	
md5sum      	1.0302805220	2.2329097938	2.1751464533	forkrun is 116.7% faster than xargs (2.1672x)	forkrun is 111.1% faster than parallel (2.1112x)	
sum -s      	0.1846734072	0.3773023345	0.6030221202	forkrun is 104.3% faster than xargs (2.0430x)	forkrun is 226.5% faster than parallel (3.2653x)	
sum -r      	1.0522078574	2.2633639501	2.2189007791	forkrun is 115.1% faster than xargs (2.1510x)	forkrun is 110.8% faster than parallel (2.1088x)	
cksum       	0.1419885937	0.2778706873	0.5551123851	forkrun is 95.69% faster than xargs (1.9569x)	forkrun is 290.9% faster than parallel (3.9095x)	
b2sum       	0.9398707613	2.0376327112	2.0164202114	forkrun is 116.7% faster than xargs (2.1679x)	forkrun is 114.5% faster than parallel (2.1454x)	
cksum -a sm3	2.7750275628	6.0712359068	5.4070919289	forkrun is 118.7% faster than xargs (2.1878x)	forkrun is 94.84% faster than parallel (1.9484x)	

OVERALL     	12.122351195	26.111776368	25.380204384	forkrun is 115.4% faster than xargs (2.1540x)	forkrun is 109.3% faster than parallel (2.0936x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100000 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.9300904025	1.7290830839	4.0116437056	forkrun is 85.90% faster than xargs (1.8590x)	forkrun is 331.3% faster than parallel (4.3131x)	
sha256sum   	1.8385318001	3.5342007784	4.0950677920	forkrun is 92.22% faster than xargs (1.9222x)	forkrun is 122.7% faster than parallel (2.2273x)	
sha512sum   	1.3145609037	2.4495008180	4.0415856890	forkrun is 86.33% faster than xargs (1.8633x)	forkrun is 207.4% faster than parallel (3.0744x)	
sha224sum   	1.8498869025	3.5141955984	4.0780127374	forkrun is 89.96% faster than xargs (1.8996x)	forkrun is 120.4% faster than parallel (2.2044x)	
sha384sum   	1.3087944166	2.4636875714	4.0593968671	forkrun is 88.24% faster than xargs (1.8824x)	forkrun is 210.1% faster than parallel (3.1016x)	
md5sum      	1.0894286274	2.2679294629	4.0393905620	forkrun is 108.1% faster than xargs (2.0817x)	forkrun is 270.7% faster than parallel (3.7078x)	
sum -s      	0.2483435051	0.3816688622	3.9631180667	forkrun is 53.68% faster than xargs (1.5368x)	forkrun is 1495.% faster than parallel (15.958x)	
sum -r      	1.0976746027	2.3051848026	4.0637497967	forkrun is 110.0% faster than xargs (2.1000x)	forkrun is 270.2% faster than parallel (3.7021x)	
cksum       	0.2045792351	0.2832402647	3.9659129656	forkrun is 38.45% faster than xargs (1.3845x)	forkrun is 1838.% faster than parallel (19.385x)	
b2sum       	1.1504032201	2.143991904 	4.0343829882	forkrun is 86.36% faster than xargs (1.8636x)	forkrun is 250.6% faster than parallel (3.5069x)	
cksum -a sm3	3.3805416428	6.3974986363	5.4613992519	forkrun is 89.24% faster than xargs (1.8924x)	forkrun is 61.55% faster than parallel (1.6155x)	

OVERALL     	14.412835259	27.470181783	45.813660422	forkrun is 90.59% faster than xargs (1.9059x)	forkrun is 217.8% faster than parallel (3.1786x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=522010 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.0993731502	2.2494771874	20.532374758	forkrun is 7.149% faster than xargs (1.0714x)	forkrun is 878.0% faster than parallel (9.7802x)	
sha256sum   	3.8445185169	4.3025861106	20.905130502	forkrun is 11.91% faster than xargs (1.1191x)	forkrun is 443.7% faster than parallel (5.4376x)	
sha512sum   	2.9110518477	3.1071824391	20.618640259	forkrun is 6.737% faster than xargs (1.0673x)	forkrun is 608.2% faster than parallel (7.0828x)	
sha224sum   	3.8432720579	4.3142903048	20.837276592	forkrun is 12.25% faster than xargs (1.1225x)	forkrun is 442.1% faster than parallel (5.4217x)	
sha384sum   	2.8722250014	3.1110188725	20.824567815	forkrun is 8.313% faster than xargs (1.0831x)	forkrun is 625.0% faster than parallel (7.2503x)	
md5sum      	2.2265907761	2.5522831571	20.664375327	forkrun is 14.62% faster than xargs (1.1462x)	forkrun is 828.0% faster than parallel (9.2807x)	
sum -s      	0.8383575952	1.1446944220	20.259386983	forkrun is 36.54% faster than xargs (1.3654x)	forkrun is 2316.% faster than parallel (24.165x)	
sum -r      	2.1513564481	2.5331195402	20.547426737	forkrun is 17.74% faster than xargs (1.1774x)	forkrun is 855.0% faster than parallel (9.5509x)	
cksum       	0.7719258735	1.1071674914	20.120639746	forkrun is 43.42% faster than xargs (1.4342x)	forkrun is 2506.% faster than parallel (26.065x)	
b2sum       	2.5541632614	2.7161386748	20.539490664	forkrun is 6.341% faster than xargs (1.0634x)	forkrun is 704.1% faster than parallel (8.0415x)	
cksum -a sm3	6.8495313790	7.8092425332	21.242653921	forkrun is 14.01% faster than xargs (1.1401x)	forkrun is 210.1% faster than parallel (3.1013x)	

OVERALL     	30.962365907	34.947200733	227.09196330	forkrun is 12.86% faster than xargs (1.1286x)	forkrun is 633.4% faster than parallel (7.3344x)	
```


***

INPUT FROM FILE  ----- OUTPUT TO REDIRECT

INVALID BENCHMARK - `xargs` failed to run here for some reason


***

INPUT FROM PIPE  ----- OUTPUT TO RDIRECT


```
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=10 ------------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0229739669	0.0047829117	0.1667121467	xargs is 380.3% faster than forkrun (4.8033x)	forkrun is 625.6% faster than parallel (7.2565x)	
sha256sum   	0.0229629300	0.0048174657	0.1667841368	xargs is 376.6% faster than forkrun (4.7665x)	forkrun is 626.3% faster than parallel (7.2631x)	
sha512sum   	0.0230039019	0.0048629379	0.1668965031	xargs is 373.0% faster than forkrun (4.7304x)	forkrun is 625.5% faster than parallel (7.2551x)	
sha224sum   	0.0230124735	0.0048177830	0.1666746614	xargs is 377.6% faster than forkrun (4.7765x)	forkrun is 624.2% faster than parallel (7.2427x)	
sha384sum   	0.0229704356	0.0048354434	0.1666111397	xargs is 375.0% faster than forkrun (4.7504x)	forkrun is 625.3% faster than parallel (7.2532x)	
md5sum      	0.0229524997	0.0047829619	0.1665914304	xargs is 379.8% faster than forkrun (4.7988x)	forkrun is 625.8% faster than parallel (7.2580x)	
sum -s      	0.0226166759	0.0043689352	0.1669000015	xargs is 417.6% faster than forkrun (5.1767x)	forkrun is 637.9% faster than parallel (7.3795x)	
sum -r      	0.0226030793	0.0043999582	0.1667033300	xargs is 413.7% faster than forkrun (5.1371x)	forkrun is 637.5% faster than parallel (7.3752x)	
cksum       	0.0229548347	0.0047548170	0.1666367112	xargs is 382.7% faster than forkrun (4.8277x)	forkrun is 625.9% faster than parallel (7.2593x)	
b2sum       	0.0226156664	0.0044788277	0.1663934564	xargs is 404.9% faster than forkrun (5.0494x)	forkrun is 635.7% faster than parallel (7.3574x)	
cksum -a sm3	0.0230576289	0.0048741265	0.1676576284	xargs is 373.0% faster than forkrun (4.7306x)	forkrun is 627.1% faster than parallel (7.2712x)	

OVERALL     	.25172409351	.05177616875	1.8345611462	xargs is 386.1% faster than forkrun (4.8617x)	forkrun is 628.7% faster than parallel (7.2879x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100 -----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0243071184	0.0061210984	0.1983834816	xargs is 297.1% faster than forkrun (3.9710x)	forkrun is 716.1% faster than parallel (8.1615x)	
sha256sum   	0.0244500683	0.0065819379	0.1986792953	xargs is 271.4% faster than forkrun (3.7147x)	forkrun is 712.5% faster than parallel (8.1259x)	
sha512sum   	0.0244910522	0.0069230227	0.1985503402	xargs is 253.7% faster than forkrun (3.5376x)	forkrun is 710.7% faster than parallel (8.1070x)	
sha224sum   	0.0244420610	0.0065290545	0.1986590908	xargs is 274.3% faster than forkrun (3.7435x)	forkrun is 712.7% faster than parallel (8.1277x)	
sha384sum   	0.0244521802	0.0066726541	0.1984952135	xargs is 266.4% faster than forkrun (3.6645x)	forkrun is 711.7% faster than parallel (8.1176x)	
md5sum      	0.0242752530	0.0061320786	0.1983717063	xargs is 295.8% faster than forkrun (3.9587x)	forkrun is 717.1% faster than parallel (8.1717x)	
sum -s      	0.0234566782	0.0053105442	0.1980558615	xargs is 341.7% faster than forkrun (4.4170x)	forkrun is 744.3% faster than parallel (8.4434x)	
sum -r      	0.0235532272	0.0055810020	0.1984761267	xargs is 322.0% faster than forkrun (4.2202x)	forkrun is 742.6% faster than parallel (8.4267x)	
cksum       	0.0242224538	0.0056150476	0.1987716415	xargs is 331.3% faster than forkrun (4.3138x)	forkrun is 720.6% faster than parallel (8.2060x)	
b2sum       	0.0237432288	0.0064958829	0.1976632180	xargs is 265.5% faster than forkrun (3.6551x)	forkrun is 732.5% faster than parallel (8.3250x)	
cksum -a sm3	0.0246253107	0.0070335105	0.2001601599	xargs is 250.1% faster than forkrun (3.5011x)	forkrun is 712.8% faster than parallel (8.1282x)	

OVERALL     	.26601863236	.06899583397	2.1842661358	xargs is 285.5% faster than forkrun (3.8555x)	forkrun is 721.0% faster than parallel (8.2109x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=1000 ----------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.0461073645	0.0399568261	0.2672615778	xargs is 15.39% faster than forkrun (1.1539x)	forkrun is 479.6% faster than parallel (5.7965x)	
sha256sum   	0.0659313593	0.0662754282	0.2856637062	forkrun is .5218% faster than xargs (1.0052x)	forkrun is 333.2% faster than parallel (4.3327x)	
sha512sum   	0.0550165304	0.0566997544	0.2746013665	forkrun is 3.059% faster than xargs (1.0305x)	forkrun is 399.1% faster than parallel (4.9912x)	
sha224sum   	0.0655209993	0.0656944807	0.2861311017	forkrun is .2647% faster than xargs (1.0026x)	forkrun is 336.7% faster than parallel (4.3670x)	
sha384sum   	0.0542951373	0.0541585838	0.2746922292	xargs is .2521% faster than forkrun (1.0025x)	forkrun is 405.9% faster than parallel (5.0592x)	
md5sum      	0.0527008518	0.0481401282	0.2737039448	xargs is 9.473% faster than forkrun (1.0947x)	forkrun is 419.3% faster than parallel (5.1935x)	
sum -s      	0.0290350916	0.0194358571	0.2547471741	xargs is 49.38% faster than forkrun (1.4938x)	forkrun is 777.3% faster than parallel (8.7737x)	
sum -r      	0.0495297949	0.0464802100	0.2742597503	xargs is 6.561% faster than forkrun (1.0656x)	forkrun is 453.7% faster than parallel (5.5372x)	
cksum       	0.0296185583	0.0174117048	0.2522952626	xargs is 70.10% faster than forkrun (1.7010x)	forkrun is 751.8% faster than parallel (8.5181x)	
b2sum       	0.0467151340	0.0520413293	0.2719141740	forkrun is 11.40% faster than xargs (1.1140x)	forkrun is 482.0% faster than parallel (5.8206x)	
cksum -a sm3	0.0971243868	0.1057853047	0.3166001868	forkrun is 8.917% faster than xargs (1.0891x)	forkrun is 225.9% faster than parallel (3.2597x)	

OVERALL     	.59159520886	.57207960777	3.0318704745	xargs is 3.411% faster than forkrun (1.0341x)	forkrun is 412.4% faster than parallel (5.1249x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=10000 ---------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.7601023664	1.6225222399	1.6637000054	forkrun is 113.4% faster than xargs (2.1346x)	forkrun is 118.8% faster than parallel (2.1887x)	
sha256sum   	1.5368506857	3.2933497337	3.1268444326	forkrun is 114.2% faster than xargs (2.1429x)	forkrun is 103.4% faster than parallel (2.0345x)	
sha512sum   	1.0664186007	2.2992936936	2.2556764122	forkrun is 115.6% faster than xargs (2.1560x)	forkrun is 111.5% faster than parallel (2.1151x)	
sha224sum   	1.5407616048	3.3166442727	3.1128274361	forkrun is 115.2% faster than xargs (2.1526x)	forkrun is 102.0% faster than parallel (2.0203x)	
sha384sum   	1.0679307724	2.2968453682	2.2473859487	forkrun is 115.0% faster than xargs (2.1507x)	forkrun is 110.4% faster than parallel (2.1044x)	
md5sum      	1.0271061275	2.2294518712	2.1717451719	forkrun is 117.0% faster than xargs (2.1706x)	forkrun is 111.4% faster than parallel (2.1144x)	
sum -s      	0.1843796288	0.3738500859	0.6037511472	forkrun is 102.7% faster than xargs (2.0276x)	forkrun is 227.4% faster than parallel (3.2745x)	
sum -r      	1.0516900869	2.2608888056	2.2104098017	forkrun is 114.9% faster than xargs (2.1497x)	forkrun is 110.1% faster than parallel (2.1017x)	
cksum       	0.1404607908	0.2730315458	0.5537666727	forkrun is 94.38% faster than xargs (1.9438x)	forkrun is 294.2% faster than parallel (3.9425x)	
b2sum       	0.9427770953	2.0415424716	2.0105381005	forkrun is 116.5% faster than xargs (2.1654x)	forkrun is 113.2% faster than parallel (2.1325x)	
cksum -a sm3	2.7896410841	6.1198427142	5.4196214952	forkrun is 119.3% faster than xargs (2.1937x)	forkrun is 94.27% faster than parallel (1.9427x)	

OVERALL     	12.108118844	26.127262802	25.376266624	forkrun is 115.7% faster than xargs (2.1578x)	forkrun is 109.5% faster than parallel (2.0958x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=100000 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	0.9311795519	1.6975003222	3.9985925936	forkrun is 82.29% faster than xargs (1.8229x)	forkrun is 329.4% faster than parallel (4.2941x)	
sha256sum   	1.8351159324	3.4868565248	4.0466105120	forkrun is 90.00% faster than xargs (1.9000x)	forkrun is 120.5% faster than parallel (2.2050x)	
sha512sum   	1.3119122583	2.4506700723	4.0530509075	forkrun is 86.80% faster than xargs (1.8680x)	forkrun is 208.9% faster than parallel (3.0894x)	
sha224sum   	1.8501268775	3.4834759312	4.0482719548	forkrun is 88.28% faster than xargs (1.8828x)	forkrun is 118.8% faster than parallel (2.1881x)	
sha384sum   	1.3006792142	2.4380927310	4.0361722946	forkrun is 87.44% faster than xargs (1.8744x)	forkrun is 210.3% faster than parallel (3.1031x)	
md5sum      	1.0904605206	2.2486116213	4.0491609809	forkrun is 106.2% faster than xargs (2.0620x)	forkrun is 271.3% faster than parallel (3.7132x)	
sum -s      	0.2425358551	0.3806784931	3.9475071826	forkrun is 56.95% faster than xargs (1.5695x)	forkrun is 1527.% faster than parallel (16.275x)	
sum -r      	1.0912387626	2.2832046833	4.0396617457	forkrun is 109.2% faster than xargs (2.0923x)	forkrun is 270.1% faster than parallel (3.7019x)	
cksum       	0.2020335521	0.2793474252	3.9716679602	forkrun is 38.26% faster than xargs (1.3826x)	forkrun is 1865.% faster than parallel (19.658x)	
b2sum       	1.1331387369	2.1501205115	4.0500269463	forkrun is 89.74% faster than xargs (1.8974x)	forkrun is 257.4% faster than parallel (3.5741x)	
cksum -a sm3	3.3858764799	6.4286811669	5.4187709897	forkrun is 89.86% faster than xargs (1.8986x)	forkrun is 60.04% faster than parallel (1.6004x)	

OVERALL     	14.374297742	27.327239483	45.659494068	forkrun is 90.11% faster than xargs (1.9011x)	forkrun is 217.6% faster than parallel (3.1764x)	




||----------------------------------------------------------------- NUM_CHECKSUMS=522010 --------------------------------------------------------------------|| 

(algorithm)	(forkrun)   	(xargs)     	(parallel)  	(relative performance vs xargs)             	(relative performance vs parallel)          	
------------	------------	------------	------------	--------------------------------------------	-----------------------------------------------	
sha1sum     	2.0544042677	2.1963678787	20.364475889	forkrun is 6.910% faster than xargs (1.0691x)	forkrun is 891.2% faster than parallel (9.9125x)	
sha256sum   	3.7860651596	4.2439634919	20.819555392	forkrun is 12.09% faster than xargs (1.1209x)	forkrun is 449.8% faster than parallel (5.4989x)	
sha512sum   	2.8480596296	3.0817047512	20.570235616	forkrun is 8.203% faster than xargs (1.0820x)	forkrun is 622.2% faster than parallel (7.2225x)	
sha224sum   	3.7801971302	4.2436796802	20.82123811 	forkrun is 12.26% faster than xargs (1.1226x)	forkrun is 450.7% faster than parallel (5.5079x)	
sha384sum   	2.8302592469	3.0246466714	20.590939621	forkrun is 6.868% faster than xargs (1.0686x)	forkrun is 627.5% faster than parallel (7.2752x)	
md5sum      	2.1903204475	2.5457837296	20.496165549	forkrun is 16.22% faster than xargs (1.1622x)	forkrun is 835.7% faster than parallel (9.3576x)	
sum -s      	0.8147966897	1.1469524132	20.184076675	forkrun is 40.76% faster than xargs (1.4076x)	forkrun is 2377.% faster than parallel (24.771x)	
sum -r      	2.1114634757	2.5178578030	20.555518418	forkrun is 19.24% faster than xargs (1.1924x)	forkrun is 873.5% faster than parallel (9.7351x)	
cksum       	0.7605374195	1.1046333869	20.116428491	forkrun is 45.24% faster than xargs (1.4524x)	forkrun is 2545.% faster than parallel (26.450x)	
b2sum       	2.5062412925	2.6733824813	20.540119013	forkrun is 6.668% faster than xargs (1.0666x)	forkrun is 719.5% faster than parallel (8.1955x)	
cksum -a sm3	6.7517454306	7.8100165886	21.134002913	forkrun is 15.67% faster than xargs (1.1567x)	forkrun is 213.0% faster than parallel (3.1301x)	

OVERALL     	30.434090189	34.588988876	226.19275569	forkrun is 13.65% faster than xargs (1.1365x)	forkrun is 643.2% faster than parallel (7.4322x)	
```


***
