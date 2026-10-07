# Gate 4.5 / Gate 4.6 — Reduced Planning Network Scientific Audit

Conclusion: **PASS** for reconstructed `candidate_12_v2`

The original rectangular candidates remain in this report as an audit baseline and retain the Gate 4.5 failure findings. Gate 4.6 replaces the production construction with a deterministic Texas-constrained seeded regionalization. The reconstructed 12-node model passes the documented criteria; Gate 5 has not been started.

## Candidate comparison

| Candidate | Nodes | Interfaces | Assigned lines | Unassigned lines | Fraction | ≥230 kV represented | Plants | Generators | Nameplate MW | Isolated | Leaves | Max degree | Area imbalance | Generation imbalance | Transmission-density imbalance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| grid_08 | 8 | 9 | 7769 | 0 | 1.000 | 634 | 1404 | 2179 | 172,206.9 | 0 | 1 | 3 | 1.00× | 263.25× | 2287.00× |
| grid_12 | 12 | 16 | 7769 | 0 | 1.000 | 634 | 1404 | 2179 | 172,206.9 | 1 | 0 | 5 | 1.00× | 82.43× | 85.91× |
| grid_20 | 20 | 24 | 7769 | 0 | 1.000 | 634 | 1404 | 2179 | 172,206.9 | 3 | 1 | 4 | 1.00× | 3478.57× | 1216.00× |
| candidate_12_v2 | 12 | 20 | 5164 | 2605 | 0.665 | 524 | 1401 | 2171 | 172,206.9 | 0 | 2 | 6 | 19.33× | 10.44× | 13.33× |

## 12-node audit

### Node-level findings

| ID | Label | Anchor | Extent | Lines | Length km | Plants | Generators | MW | Interfaces | Flags |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| PANHANDLE | Panhandle | [-101.8, 35.4] | [-102.727875419403, 33.7653344200453, -99.1450235018485, 37.915011904873] | 227 | 4,508.2 | 42 | 21 | 5,168.8 | 3 | — |
| HIGH_PLAINS | High Plains | [-102.7, 33.7] | [-104.240643788556, 32.5615569936619, -99.180716101819, 35.3102863078757] | 219 | 3,400.9 | 24 | 19 | 3,731.5 | 3 | — |
| PERMIAN | Permian Basin | [-102.3, 31.6] | [-106.178416186473, 29.747458201443, -100.543096211501, 33.0336577804482] | 228 | 4,134.9 | 162 | 231 | 17,012.0 | 3 | — |
| NORTHWEST | Northwest Texas | [-104.0, 34.1] | [-106.849546000562, 31.408987616043, -105.15857735835, 32.5194010275105] | 95 | 747.9 | 0 | 0 | 0.0 | 1 | — |
| NORTH | North Texas | [-97.4, 33.5] | [-101.843412467853, 32.4198921430995, -95.0416575897899, 34.6837357169695] | 843 | 7,982.2 | 123 | 214 | 12,359.5 | 4 | very large geographic extent |
| NORTH_CENTRAL | North Central Texas | [-97.6, 32.1] | [-99.5388237997144, 30.251285988974, -95.3464400283894, 33.3713040004737] | 539 | 6,893.5 | 179 | 223 | 26,866.8 | 5 | generation dominated |
| EAST | East Texas | [-94.9, 32.3] | [-96.9606808289661, 30.2666681590054, -93.1876627436275, 33.9877315197886] | 523 | 6,867.8 | 71 | 66 | 11,937.7 | 3 | — |
| WEST_CENTRAL | West Central Texas | [-100.0, 32.0] | [-102.289080141234, 29.9879660495113, -97.717076509752, 34.3737772854436] | 285 | 6,981.5 | 139 | 122 | 18,341.0 | 6 | generation dominated |
| CENTRAL_HIGHLANDS | Central Highlands | [-99.0, 30.7] | [-101.53549230851, 28.8668461559953, -96.7480506201294, 32.1916361503233] | 505 | 6,651.7 | 82 | 123 | 7,263.9 | 4 | — |
| HOUSTON_GULF | Houston / Gulf | [-95.4, 29.8] | [-98.0005561694257, 27.9358040180875, -93.1876627436275, 31.9800319522638] | 1266 | 11,342.0 | 293 | 683 | 38,974.6 | 4 | generation dominated |
| SOUTH_TEXAS | South Texas | [-98.2, 28.4] | [-100.849385035108, 26.3435975581872, -96.0503225803405, 30.4099442897194] | 513 | 8,192.9 | 175 | 266 | 20,614.0 | 3 | generation dominated |
| RIO_GRANDE | Rio Grande | [-98.5, 26.5] | [-99.5209957503793, 25.8877078402876, -97.2996522400441, 27.8501736293759] | 161 | 2,000.6 | 111 | 203 | 9,838.4 | 1 | — |

### Corridor-level findings

| Interface | Regions | Supporting geometries | Voltage classes | High-voltage count | Geographic evidence extent | Flags |
| --- | --- | ---: | --- | ---: | --- | --- |
| CENTRAL_HIGHLANDS__HOUSTON_GULF | CENTRAL_HIGHLANDS ↔ HOUSTON_GULF | 5 | {'115–229 kV': 2, '230+ kV': 3, 'below 115 kV': 0, 'unknown': 0} | 3 | [-97.3327821099976, 29.8964213501584, -96.9892728892063, 30.299246439523] | — |
| CENTRAL_HIGHLANDS__NORTH_CENTRAL | CENTRAL_HIGHLANDS ↔ NORTH_CENTRAL | 10 | {'115–229 kV': 3, '230+ kV': 5, 'below 115 kV': 2, 'unknown': 0} | 5 | [-98.3870049302102, 30.3994543199062, -97.1493412600752, 31.4131269497084] | — |
| CENTRAL_HIGHLANDS__SOUTH_TEXAS | CENTRAL_HIGHLANDS ↔ SOUTH_TEXAS | 13 | {'115–229 kV': 5, '230+ kV': 7, 'below 115 kV': 1, 'unknown': 0} | 7 | [-100.778801179276, 29.1984721794556, -97.6738682693624, 30.020492930179] | geographically diffuse support |
| CENTRAL_HIGHLANDS__WEST_CENTRAL | CENTRAL_HIGHLANDS ↔ WEST_CENTRAL | 8 | {'115–229 kV': 4, '230+ kV': 4, 'below 115 kV': 0, 'unknown': 0} | 4 | [-100.88095070042, 30.6370777996816, -98.8183359596756, 31.6570749991986] | geographically diffuse support |
| EAST__HOUSTON_GULF | EAST ↔ HOUSTON_GULF | 6 | {'115–229 kV': 2, '230+ kV': 4, 'below 115 kV': 0, 'unknown': 0} | 4 | [-96.046304020164, 30.9244756802826, -93.4365441833676, 31.521636131713] | geographically diffuse support |
| EAST__NORTH | EAST ↔ NORTH | 8 | {'115–229 kV': 1, '230+ kV': 6, 'below 115 kV': 1, 'unknown': 0} | 6 | [-96.1290884006292, 32.6901006403474, -95.625140969473, 33.6457939304776] | — |
| EAST__NORTH_CENTRAL | EAST ↔ NORTH_CENTRAL | 12 | {'115–229 kV': 1, '230+ kV': 5, 'below 115 kV': 4, 'unknown': 2} | 5 | [-96.566086889679, 31.2615350004242, -96.0183026198252, 32.571050859884] | — |
| HIGH_PLAINS__PANHANDLE | HIGH_PLAINS ↔ PANHANDLE | 8 | {'115–229 kV': 3, '230+ kV': 5, 'below 115 kV': 0, 'unknown': 0} | 5 | [-102.529195280373, 33.919963979946, -100.426697120683, 34.7204188700081] | — |
| HIGH_PLAINS__PERMIAN | HIGH_PLAINS ↔ PERMIAN | 1 | {'115–229 kV': 0, '230+ kV': 1, 'below 115 kV': 0, 'unknown': 0} | 1 | [-101.660030150025, 32.7934603598268, -101.660030150025, 32.7934603598268] | — |
| HIGH_PLAINS__WEST_CENTRAL | HIGH_PLAINS ↔ WEST_CENTRAL | 5 | {'115–229 kV': 2, '230+ kV': 2, 'below 115 kV': 0, 'unknown': 1} | 2 | [-101.41532377305, 32.815318145234, -100.248642439842, 33.948591340232] | — |
| HOUSTON_GULF__NORTH_CENTRAL | HOUSTON_GULF ↔ NORTH_CENTRAL | 2 | {'115–229 kV': 0, '230+ kV': 2, 'below 115 kV': 0, 'unknown': 0} | 2 | [-96.3658570682614, 30.8847242230123, -96.2748819483595, 31.0301587346342] | — |
| HOUSTON_GULF__SOUTH_TEXAS | HOUSTON_GULF ↔ SOUTH_TEXAS | 6 | {'115–229 kV': 2, '230+ kV': 3, 'below 115 kV': 1, 'unknown': 0} | 3 | [-97.214812449602, 28.6435796293355, -96.1730260598689, 29.6784824699407] | — |
| NORTHWEST__PERMIAN | NORTHWEST ↔ PERMIAN | 2 | {'115–229 kV': 2, '230+ kV': 0, 'below 115 kV': 0, 'unknown': 0} | 0 | [-105.812730999861, 31.7477140004011, -105.166113999515, 31.9233779999394] | — |
| NORTH_CENTRAL__WEST_CENTRAL | NORTH_CENTRAL ↔ WEST_CENTRAL | 10 | {'115–229 kV': 7, '230+ kV': 1, 'below 115 kV': 1, 'unknown': 1} | 1 | [-99.0877552200806, 31.6161250899908, -98.7199769997014, 32.7644340598229] | — |
| NORTH__NORTH_CENTRAL | NORTH ↔ NORTH_CENTRAL | 13 | {'115–229 kV': 4, '230+ kV': 6, 'below 115 kV': 2, 'unknown': 1} | 6 | [-98.6482894598994, 32.657403719555, -96.5116874902924, 33.0176755294044] | — |
| NORTH__PANHANDLE | NORTH ↔ PANHANDLE | 4 | {'115–229 kV': 4, '230+ kV': 0, 'below 115 kV': 0, 'unknown': 0} | 0 | [-99.7234373199881, 34.18308127062, -99.4736418208189, 34.3205240304097] | — |
| NORTH__WEST_CENTRAL | NORTH ↔ WEST_CENTRAL | 13 | {'115–229 kV': 6, '230+ kV': 7, 'below 115 kV': 0, 'unknown': 0} | 7 | [-101.313724660158, 32.8916175798063, -98.4659808897672, 34.1830932896816] | geographically diffuse support |
| PANHANDLE__WEST_CENTRAL | PANHANDLE ↔ WEST_CENTRAL | 3 | {'115–229 kV': 2, '230+ kV': 1, 'below 115 kV': 0, 'unknown': 0} | 1 | [-101.313724660158, 33.919963979946, -100.248642439842, 33.948591340232] | — |
| PERMIAN__WEST_CENTRAL | PERMIAN ↔ WEST_CENTRAL | 12 | {'115–229 kV': 4, '230+ kV': 5, 'below 115 kV': 2, 'unknown': 1} | 5 | [-102.099470980613, 30.6370777996816, -100.88095070042, 32.815318145234] | geographically diffuse support |
| RIO_GRANDE__SOUTH_TEXAS | RIO_GRANDE ↔ SOUTH_TEXAS | 5 | {'115–229 kV': 3, '230+ kV': 2, 'below 115 kV': 0, 'unknown': 0} | 2 | [-99.4542311698823, 27.2644644495985, -97.7745445300813, 27.595966130561] | — |

## Partition artifacts and stability

- Legacy rectangular baseline transitions: `{'2': 1, '3': 1}`. These are retained for traceability only.
- The reconstructed model uses Texas-footprint cells and a fixed-seed spatial assignment. A deterministic +0.01° coordinate perturbation changed `27` of `5044` sampled geometry-point assignments, with no empty region.
- Weak interfaces supported by one public geometry without high-voltage evidence: `none`. A single 230+ kV geometry with at least 5 km of path in each adjacent region is retained as strong evidence under the documented rule.
- Public lines outside the Texas boundary asset remain unassigned rather than being forced into a planning region; this preserves the Gate 2 bounding-box limitation without extending planning regions outside Texas.

## 8 vs 12 vs 20

The 8-node model over-aggregates distinct areas and the 20-node model adds complexity without additional source representation. The reconstructed 12-node model has all regions populated with transmission evidence, stable geographic IDs/labels, Texas-constrained cells, and materially lower generation and density imbalance than the rectangular 12-node baseline. The remaining imbalance is concentrated in real public infrastructure patterns such as Houston/Gulf and major West/Central generation areas rather than an empty rectangle.

## Comparison with the existing teaching network

The existing scenario has 32 synthetic buses and 48 representative corridors, with authored headroom, period profiles, congestion, recourse, and scoring. It is more pedagogically structured than the public-derived candidate. The reconstructed model adds traceability and geographic context but still has no teaching limits, load allocation, or calibrated headroom. A future migration must preserve the old model's multiple connection choices, bottlenecks, generator tradeoffs, and binding diagnostics.

## Gate 4.6 result

The reconstructed `candidate_12_v2` receives **PASS** under the documented Gate 4.5 criteria: 12 populated contiguous Texas-constrained planning regions; no weak interface lacking high-voltage evidence; deterministic stable IDs and labels; reproducible source mappings; no teaching capacities; and no inferred electrical connectivity.

Gate 5 may now be considered, but has not been started in this pass.
