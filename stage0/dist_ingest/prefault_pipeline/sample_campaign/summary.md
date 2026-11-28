# Prefault pipeline campaign (fake-NUMA / dev workstation)

NOT physical-NUMA evidence; NOT production; no improvement threshold.

## continuous schedule=continuous reps=2
- **lazy**: median_e2e_Bps=262876554.8  median_overlap_summed_ns=0  median_prepared_ratio=0.0000  valid=2/2
- **serial_madvise**: median_e2e_Bps=284186802.8  median_overlap_summed_ns=0  median_prepared_ratio=1.0000  valid=2/2
- **pipeline_madvise**: median_e2e_Bps=271271181.7  median_overlap_summed_ns=4851698  median_prepared_ratio=1.0000  valid=2/2

## burst-gap schedule=burst-gap reps=2
- **lazy**: median_e2e_Bps=82674622.7  median_overlap_summed_ns=0  median_prepared_ratio=0.0000  valid=2/2
- **serial_madvise**: median_e2e_Bps=80252315.0  median_overlap_summed_ns=0  median_prepared_ratio=1.0000  valid=2/2
- **pipeline_madvise**: median_e2e_Bps=81014751.9  median_overlap_summed_ns=11508401  median_prepared_ratio=1.0000  valid=2/2
