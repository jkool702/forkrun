||-----------------------------------------------------------------------------------------------------------------------------------------------------------||
||------------------------------------------------------------------- RUN_TIME_IN_SECONDS -------------------------------------------------------------------||
||-----------------------------------------------------------------------------------------------------------------------------------------------------------||



||----------------------------------------------------------------- NUM_CHECKSUMS=1024 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (relative performance vs xargs)             
------------    ------------    ------------    ------------    --------------------------------------------
sha1sum         0.0456729309    0.0464633332    0.0375283706    xargs is 21.70% faster than forkrun (1.2170x)
sha256sum       0.0636937467    0.0650688052    0.0608462566    xargs is 4.679% faster than forkrun (1.0467x)
sha512sum       0.0530445794    0.0543355513    0.0488338149    xargs is 8.622% faster than forkrun (1.0862x)
sha224sum       0.0637325520    0.0645362363    0.0605668081    xargs is 5.226% faster than forkrun (1.0522x)
sha384sum       0.0528784950    0.0540880507    0.0480014042    xargs is 12.68% faster than forkrun (1.1268x)
md5sum          0.0518922211    0.0527886905    0.0453929688    xargs is 14.31% faster than forkrun (1.1431x)
sum -s          0.0324070677    0.0319480162    0.0199693751    xargs is 59.98% faster than forkrun (1.5998x)
sum -r          0.0526560881    0.0513415050    0.0454535681    xargs is 12.95% faster than forkrun (1.1295x)
cksum           0.0314581674    0.0319496770    0.0182104321    xargs is 72.74% faster than forkrun (1.7274x)
b2sum           0.0502644239    0.0482762923    0.0445421920    xargs is 8.383% faster than forkrun (1.0838x)
cksum -a sm3    0.0913342355    0.0933020048    0.0962372587    forkrun is 5.368% faster than xargs (1.0536x)

OVERALL         .58903450846    .59409816288    .52558244995    xargs is 12.07% faster than forkrun (1.1207x)




||----------------------------------------------------------------- NUM_CHECKSUMS=4096 ----------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (relative performance vs xargs)             
------------    ------------    ------------    ------------    --------------------------------------------
sha1sum         0.3946076462    0.4609839651    0.7752004444    forkrun is 96.44% faster than xargs (1.9644x)
sha256sum       0.8175196749    0.9157168448    1.5895537898    forkrun is 94.43% faster than xargs (1.9443x)
sha512sum       0.5588821618    0.6397280319    1.1047009771    forkrun is 97.66% faster than xargs (1.9766x)
sha224sum       0.7788773396    0.9105845293    1.5916879156    forkrun is 74.79% faster than xargs (1.7479x)
sha384sum       0.5509316164    0.6375886091    1.0977645448    forkrun is 99.25% faster than xargs (1.9925x)
md5sum          0.5338504523    0.6032103722    1.0632295765    forkrun is 76.26% faster than xargs (1.7626x)
sum -s          0.1191579040    0.1171845481    0.1836878144    forkrun is 56.75% faster than xargs (1.5675x)
sum -r          0.5477933373    0.5762124016    1.0882240264    forkrun is 98.65% faster than xargs (1.9865x)
cksum           0.0906571812    0.1000005323    0.1346448013    forkrun is 48.52% faster than xargs (1.4852x)
b2sum           0.4857571179    0.5060656222    0.9635763076    forkrun is 98.36% faster than xargs (1.9836x)
cksum -a sm3    1.3918623399    1.6349787553    2.9084050107    forkrun is 77.88% faster than xargs (1.7788x)

OVERALL         6.2698967720    7.1022542123    12.500675209    forkrun is 99.37% faster than xargs (1.9937x)




||----------------------------------------------------------------- NUM_CHECKSUMS=16384 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (relative performance vs xargs)             
------------    ------------    ------------    ------------    --------------------------------------------
sha1sum         0.8294137682    0.8498334434    1.6426548142    forkrun is 98.05% faster than xargs (1.9805x)
sha256sum       1.6781038043    1.6787802685    3.3623246847    forkrun is 100.3% faster than xargs (2.0036x)
sha512sum       1.1566799372    1.1676494563    2.3152547186    forkrun is 100.1% faster than xargs (2.0016x)
sha224sum       1.6698161835    1.6774970738    3.3502057306    forkrun is 100.6% faster than xargs (2.0063x)
sha384sum       1.1587085356    1.1753652471    2.3295307076    forkrun is 101.0% faster than xargs (2.0104x)
md5sum          1.1285146397    1.1274276686    2.2326214046    forkrun is 98.02% faster than xargs (1.9802x)
sum -s          0.2052094539    0.2051441231    0.3772266481    forkrun is 83.82% faster than xargs (1.8382x)
sum -r          1.1555219789    1.1499049653    2.2777994692    forkrun is 98.08% faster than xargs (1.9808x)
cksum           0.1566760531    0.1571582701    0.2741160529    forkrun is 74.95% faster than xargs (1.7495x)
b2sum           1.0238016381    1.0200777627    2.0188539209    forkrun is 97.91% faster than xargs (1.9791x)
cksum -a sm3    3.0486879860    3.0621520354    6.1473329174    forkrun is 100.7% faster than xargs (2.0075x)

OVERALL         13.211133978    13.270990314    26.327921069    forkrun is 99.28% faster than xargs (1.9928x)




||----------------------------------------------------------------- NUM_CHECKSUMS=65536 ---------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (relative performance vs xargs)             
------------    ------------    ------------    ------------    --------------------------------------------
sha1sum         0.8983310262    0.9169477828    1.6860176046    forkrun is 87.68% faster than xargs (1.8768x)
sha256sum       1.7613315845    1.8011126266    3.4487120457    forkrun is 95.80% faster than xargs (1.9580x)
sha512sum       1.2451774524    1.2827590222    2.4046379506    forkrun is 87.45% faster than xargs (1.8745x)
sha224sum       1.7743903668    1.8207778540    3.4841213741    forkrun is 96.35% faster than xargs (1.9635x)
sha384sum       1.2447860183    1.2812297397    2.3981796996    forkrun is 92.65% faster than xargs (1.9265x)
md5sum          1.2048522840    1.1698828612    2.2688686438    forkrun is 93.93% faster than xargs (1.9393x)
sum -s          0.2672509997    0.2540529900    0.3834916334    forkrun is 50.94% faster than xargs (1.5094x)
sum -r          1.2151842523    1.1936810046    2.3156951270    forkrun is 93.99% faster than xargs (1.9399x)
cksum           0.2137922889    0.2067753383    0.2818592325    forkrun is 36.31% faster than xargs (1.3631x)
b2sum           1.0987024786    1.1132130197    2.0724426553    forkrun is 86.16% faster than xargs (1.8616x)
cksum -a sm3    3.1451181651    3.2541432401    6.3329347046    forkrun is 101.3% faster than xargs (2.0135x)

OVERALL         14.068916917    14.294575479    27.076960671    forkrun is 92.45% faster than xargs (1.9245x)




||----------------------------------------------------------------- NUM_CHECKSUMS=262144 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (relative performance vs xargs)             
------------    ------------    ------------    ------------    --------------------------------------------
sha1sum         2.7121054441    2.7547051404    2.6878366572    xargs is .9029% faster than forkrun (1.0090x)
sha256sum       5.3678019252    5.4923128770    5.3820443164    forkrun is .2653% faster than xargs (1.0026x)
sha512sum       3.7749561796    3.9134757947    3.7753409479    forkrun is .0101% faster than xargs (1.0001x)
sha224sum       5.3756552729    5.5202616523    5.4080498252    forkrun is .6026% faster than xargs (1.0060x)
sha384sum       3.8087138498    3.9250146207    3.7826707308    xargs is .6884% faster than forkrun (1.0068x)
md5sum          3.6049764952    3.4885727801    3.4397013233    xargs is 1.420% faster than forkrun (1.0142x)
sum -s          0.7095353547    0.6853797287    0.6882422765    forkrun is .4176% faster than xargs (1.0041x)
sum -r          3.7011366985    3.5353159041    3.5000845046    xargs is 1.006% faster than forkrun (1.0100x)
cksum           0.5490487254    0.5426514601    0.5234957211    xargs is 3.659% faster than forkrun (1.0365x)
b2sum           3.3027966761    3.4067872436    3.2786631598    xargs is .7360% faster than forkrun (1.0073x)
cksum -a sm3    9.7818710379    10.032120044    10.091845688    forkrun is 3.168% faster than xargs (1.0316x)

OVERALL         42.688597659    43.296597246    42.557975151    xargs is .3069% faster than forkrun (1.0030x)




||----------------------------------------------------------------- NUM_CHECKSUMS=585639 --------------------------------------------------------------------|| 

(algorithm)     (forkrun -j -)  (forkrun)       (xargs)         (relative performance vs xargs)             
------------    ------------    ------------    ------------    --------------------------------------------
sha1sum         2.8125629805    3.1608094699    3.0319734397    forkrun is 7.801% faster than xargs (1.0780x)
sha256sum       5.5086681617    6.2452767149    6.0598785620    forkrun is 10.00% faster than xargs (1.1000x)
sha512sum       3.8944627129    4.4362842402    4.2948553843    forkrun is 10.28% faster than xargs (1.1028x)
sha224sum       5.4648545252    6.2202428949    6.0466325560    forkrun is 10.64% faster than xargs (1.1064x)
sha384sum       3.8904697136    4.3914331928    4.2617017852    forkrun is 9.542% faster than xargs (1.0954x)
md5sum          3.6868007304    3.6013430953    3.5500610506    xargs is 1.444% faster than forkrun (1.0144x)
sum -s          1.0446739326    0.8907164463    0.8380384459    xargs is 6.285% faster than forkrun (1.0628x)
sum -r          3.7528038242    3.7066937714    3.6429123522    xargs is 1.750% faster than forkrun (1.0175x)
cksum           0.9029722655    0.7973787747    0.7451066177    xargs is 7.015% faster than forkrun (1.0701x)
b2sum           3.3924355931    3.8110039704    3.6959464437    forkrun is 8.946% faster than xargs (1.0894x)
cksum -a sm3    9.9426834056    11.413280065    11.062789581    forkrun is 11.26% faster than xargs (1.1126x)

OVERALL         44.293387845    48.674462637    47.229896218    forkrun is 6.629% faster than xargs (1.0662x)

