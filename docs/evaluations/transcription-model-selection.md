# W05 transcription comparison

MAESTRO v3 test subset: 12 fixed 30-second inputs; CPU fresh-process execution.
Dataset: CC-BY-NC-SA-4.0. Piano checkpoint: Qiuqiang Kong, Zenodo 4034264, CC-BY-4.0.

Summary SHA256: `55a54fa1d7d2a970de1c8a27ed758e64e6707579dfd760061be773f9b764f992`
Manifest SHA256: `b3f664dd3c6372216712d3916639df017182c291d4e0f797b35aae3e51c7dfb9`

Status: **selected_for_subset**; winner: piano_amt; reason: onset_accuracy.
Product status: selected_pending_integration. ByteDance requires selected_pending_integration before product use.
Accuracy uses first runs only; repetitions and diagnostics never replace a failed first run.
This small classical piano subset does not establish YouTube/mixed-instrument/full-song performance.

Host: Windows; CPU: Intel64 Family 6 Model 151 Stepping 2_ GenuineIntel.
Logical cores: 24; RAM bytes: 68572536832.

| Candidate | Package version | Worker Python | Backend | Source commit | Checkpoint SHA256 | Lock SHA256 |
|---|---|---|---|---|---|---|
| basic_pitch | 0.4.0 | 3.12.13 | onnx_cpu 1.30.0 | `049dc8a01a170c2370d7b246ec1c2067e060c3bf` | `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec` | `2d7d8128b0809d4ea759b6fc0d8ea6ba413a596c5aff864bc823b145a443597c` |
| piano_amt | 0.0.6 | 3.12.13 | torch_cpu 2.10.0+cpu | `0226e74cbc805660e34bbd6a8fed2083890ebb88` | `c3fa9730725bf4a762f1c14bc80cd5986eacda01b026f5a4a2525cd607876141` | `3c97296a2ae6af71230cc79117d2b1df4d35ed20c764618fb94235133708b6e5` |

Piano: CPU float32, torch intra/inter-op threads 1/1. Basic Pitch: ONNX CPU, upstream thread defaults (not assumed equal).

| Candidate | Started / scheduled | Success | Raw failure rate | Model-only failures / denominator | Not run |
|---|---:|---:|---:|---:|---:|
| basic_pitch | 36 / 36 | 36 | 0 | 0 / 36 | 0 |
| piano_amt | 36 / 36 | 36 | 0 | 0 / 36 | 0 |

Gates: none.

| Candidate | State counts | excluded_infrastructure | excluded_unresolved | CPU excluded scheduled / diagnostics |
|---|---|---:|---:|---|
| basic_pitch | success=36 | 0 | 0 | 0 / 0 |
| piano_amt | success=36 | 0 | 0 | 0 / 0 |

CPU excludes unsuccessful and unstarted scheduled slots; every diagnostic and preflight is also excluded.

| Slot | Candidate | Status | Attribution | Error code | Diagnostic for |
|---|---|---|---|---|---|

| Preflight slot | Candidate | Status | Attribution | Error code | Elapsed sec |
|---|---|---|---|---|---:|
| preflight-basic_pitch-0 | basic_pitch | success | none | none | 4.7653658 |
| preflight-basic_pitch-1 | basic_pitch | success | none | none | 2.316158 |
| preflight-piano_amt-0 | piano_amt | success | none | none | 99.342728 |
| preflight-piano_amt-1 | piano_amt | success | none | none | 72.186464 |

Diagnostics excluded from accuracy/reliability/speed denominators: 0.
Generic worker exit3/4 does not identify a model cause; unresolved failures block automatic selection.
Unverified size-limited artifacts: 0; contents were preserved and not hashed.

| Candidate | Metric | macro F1 (success-only) | micro precision / recall / F1 | TP / FP / FN | Empty reference excluded |
|---|---|---:|---|---:|---:|
| basic_pitch | key_release | 0.11645255 | 0.10453353 / 0.087957125 / 0.095531587 | 279 / 2390 / 2893 | 0 |
| basic_pitch | onset | 0.69268867 | 0.73772949 / 0.62074401 / 0.67419962 | 1969 / 700 / 1203 | 0 |
| basic_pitch | sustain | 0.22277753 | 0.21880854 / 0.18411097 / 0.19996576 | 584 / 2085 / 2588 | 0 |
| piano_amt | key_release | 0.37055895 | 0.37602091 / 0.36286255 / 0.36932456 | 1151 / 1910 / 2021 | 0 |
| piano_amt | onset | 0.97003636 | 0.97811173 / 0.94388398 / 0.96069309 | 2994 / 67 / 178 | 0 |
| piano_amt | sustain | 0.82887344 | 0.82195361 / 0.79319042 / 0.8073159 | 2516 / 545 / 656 | 0 |

| Candidate | CPU valid samples | Median sec | p95 sec (nearest rank) |
|---|---:|---:|---:|
| basic_pitch | 36 | 2.5193666 | 2.7366448 |
| piano_amt | 36 | 72.499053 | 73.552422 |

| Candidate | Reference | Operational recall TP / planned reference | recall |
|---|---|---:|---:|
| basic_pitch | key_release | 279 / 3172 | 0.087957125 |
| basic_pitch | sustain | 584 / 3172 | 0.18411097 |
| piano_amt | key_release | 1151 / 3172 | 0.36286255 |
| piano_amt | sustain | 2516 / 3172 | 0.79319042 |

basic_pitch individual seconds: 2.4774737, 2.4094382, 2.4864177, 2.6282096, 2.5313341, 2.5114027, 2.5203682, 2.5309738, 2.4596316, 2.5147239, 2.5514739, 2.7366448, 2.3535234, 2.5072196, 2.6477864, 3.2563716, 2.5492226, 2.5376408, 2.4661539, 2.5783374, 2.6550098, 2.5235984, 2.5560521, 2.4688172, 2.586173, 2.4411577, 2.5370187, 2.5581245, 2.5419791, 2.5183649, 1.9176419, 1.9532402, 2.1418631, 2.0926505, 2.2172616, 2.1983856.
basic_pitch individual RTF (elapsed/30): 0.082582457, 0.080314607, 0.08288059, 0.087606987, 0.084377803, 0.083713423, 0.084012273, 0.084365793, 0.08198772, 0.08382413, 0.08504913, 0.091221493, 0.07845078, 0.083573987, 0.088259547, 0.10854572, 0.084974087, 0.084588027, 0.08220513, 0.08594458, 0.088500327, 0.084119947, 0.085201737, 0.082293907, 0.086205767, 0.081371923, 0.08456729, 0.085270817, 0.084732637, 0.083945497, 0.063921397, 0.065108007, 0.071395437, 0.069755017, 0.07390872, 0.07327952.

piano_amt individual seconds: 72.824911, 73.837501, 72.992908, 73.046818, 72.349553, 72.808404, 73.026668, 72.781918, 72.542575, 72.585637, 73.462095, 72.468372, 72.356977, 72.31655, 72.241242, 72.288248, 73.362042, 72.517715, 72.500247, 72.752536, 73.552422, 72.496146, 73.208082, 71.773408, 73.161055, 73.037114, 72.029079, 72.275441, 72.49786, 71.368858, 67.46716, 67.639873, 69.07505, 69.305825, 69.304024, 69.574808.
piano_amt individual RTF (elapsed/30): 2.427497, 2.46125, 2.4330969, 2.4348939, 2.4116518, 2.4269468, 2.4342223, 2.4260639, 2.4180858, 2.4195212, 2.4487365, 2.4156124, 2.4118992, 2.4105517, 2.4080414, 2.4096083, 2.4454014, 2.4172572, 2.4166749, 2.4250845, 2.4517474, 2.4165382, 2.4402694, 2.3924469, 2.4387018, 2.4345705, 2.4009693, 2.4091814, 2.4165953, 2.3789619, 2.2489053, 2.2546624, 2.3025017, 2.3101942, 2.3101341, 2.3191603.

Paired nonempty recordings: 12; bootstrap PCG64 seed20261005,10000 paired samples.
Onset difference 95% CI: [0.238872068492375, 0.31815857791061847]; sustain difference 95% CI: [0.5401297989159547, 0.6713266811526922].
Input preparation seconds: 7.1911484; execution includes process startup, cleanup and output validation.
CPU measurements are not warm inference or pure neural-network compute time. Linux/CUDA support requires separate evidence.

| Candidate | Recording SHA256 | First precision/recall/F1: onset; sustain; key-release | velocity MAE / pairs | Censored predicted / key / sustain | Determinism |
|---|---|---|---|---|---|
| basic_pitch | `02b7b27f16cc8d61f930ddf8f9cad4449a1617007b52cde336f0723fdf59a1d7` | 0.80254777 / 0.73255814 / 0.76595745; 0.29617834 / 0.27034884 / 0.28267477; 0.070063694 / 0.063953488 / 0.066869301 | null / 252 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `04b13c9a8aaf03806ec705281a45de2a1df89d86c91b3546d3f26093a8d4e4f7` | 0.73232323 / 0.93548387 / 0.82152975; 0.36868687 / 0.47096774 / 0.41359773; 0.36868687 / 0.47096774 / 0.41359773 | null / 145 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `05558a9d411d5d5430a8fc617c22cff238d7fa13461a81f8207e147002bd4d37` | 0.77985075 / 0.6656051 / 0.71821306; 0.067164179 / 0.057324841 / 0.06185567; 0.03358209 / 0.02866242 / 0.030927835 | null / 209 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `08b32ca3d73cfcd31ff37dcdc576d6b2d8c8e3e78a4aa0075c630e340f38cdfe` | 0.68145161 / 0.36819172 / 0.47807638; 0.18951613 / 0.10239651 / 0.13295615; 0.092741935 / 0.050108932 / 0.065063649 | null / 169 | 0 / 0 / 2 | deterministic_observed |
| basic_pitch | `08f2eb8b969ffae1d86e6dc9eb8a4f551598d0cf63fe9a04c20ab720917e8998` | 0.67179487 / 0.76608187 / 0.71584699; 0.23589744 / 0.26900585 / 0.25136612; 0.087179487 / 0.099415205 / 0.092896175 | null / 131 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `0da861e67151c7d384f9678de3b2e31c5acdc2fe759d2a234493423153da654c` | 0.74285714 / 0.80829016 / 0.77419355; 0.16190476 / 0.1761658 / 0.16873449; 0.16190476 / 0.1761658 / 0.16873449 | null / 156 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `0e1a9b29c06edb8d35777bdfb42cbaec449c055c90d9e3833b3d5821c11ff1a6` | 0.82914573 / 0.74324324 / 0.78384798; 0.14572864 / 0.13063063 / 0.13776722; 0.12562814 / 0.11261261 / 0.11876485 | null / 165 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `0e48121f5d29105649e24746a81c352915ba49721b7d01a8ad044b6024f27fca` | 0.58 / 0.78378378 / 0.66666667; 0.28 / 0.37837838 / 0.32183908; 0.12 / 0.16216216 / 0.13793103 | null / 58 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `0f6abcad32f34cacadef4e66c025546e823760952e53bc026cefb1f82bba3eb5` | 0.5648855 / 0.90243902 / 0.69483568; 0.2519084 / 0.40243902 / 0.30985915; 0.10687023 / 0.17073171 / 0.1314554 | null / 74 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `0fe64d212bd5310431032584b6471a33086b1421184b1fcc9bb412b286acd327` | 0.63467492 / 0.56473829 / 0.59766764; 0.21671827 / 0.19283747 / 0.20408163; 0.068111455 / 0.060606061 / 0.064139942 | null / 205 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `0fee9ae07e0a76500e44f462ad1e363160354f8e9f9a8f7678326e9843faa809` | 0.89433962 / 0.44299065 / 0.5925; 0.18867925 / 0.093457944 / 0.125; 0.022641509 / 0.011214953 / 0.015 | null / 237 | 0 / 0 / 0 | deterministic_observed |
| basic_pitch | `11250fff243bdf89e5bbcbb9dc2ad6bbee92f2f25fec4fa1af5b55e8a50d6b5d` | 0.7706422 / 0.64615385 / 0.70292887; 0.28899083 / 0.24230769 / 0.26359833; 0.10091743 / 0.084615385 / 0.092050209 | null / 168 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `02b7b27f16cc8d61f930ddf8f9cad4449a1617007b52cde336f0723fdf59a1d7` | 0.99117647 / 0.97965116 / 0.98538012; 0.88823529 / 0.87790698 / 0.88304094; 0.47647059 / 0.47093023 / 0.47368421 | 2.5578635 / 337 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `04b13c9a8aaf03806ec705281a45de2a1df89d86c91b3546d3f26093a8d4e4f7` | 0.9625 / 0.99354839 / 0.97777778; 0.86875 / 0.89677419 / 0.88253968; 0.86875 / 0.89677419 / 0.88253968 | 2.2272727 / 154 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `05558a9d411d5d5430a8fc617c22cff238d7fa13461a81f8207e147002bd4d37` | 0.99358974 / 0.98726115 / 0.99041534; 0.8974359 / 0.89171975 / 0.89456869; 0.82692308 / 0.82165605 / 0.82428115 | 2.416129 / 310 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `08b32ca3d73cfcd31ff37dcdc576d6b2d8c8e3e78a4aa0075c630e340f38cdfe` | 0.95098039 / 0.8453159 / 0.89504037; 0.54656863 / 0.48583878 / 0.51441753; 0.049019608 / 0.043572985 / 0.046136101 | 4.621134 / 388 | 0 / 0 / 2 | deterministic_observed |
| piano_amt | `08f2eb8b969ffae1d86e6dc9eb8a4f551598d0cf63fe9a04c20ab720917e8998` | 0.97633136 / 0.96491228 / 0.97058824; 0.85207101 / 0.84210526 / 0.84705882; 0.19526627 / 0.19298246 / 0.19411765 | 2.5636364 / 165 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `0da861e67151c7d384f9678de3b2e31c5acdc2fe759d2a234493423153da654c` | 0.98963731 / 0.98963731 / 0.98963731; 0.81865285 / 0.81865285 / 0.81865285; 0.51295337 / 0.51295337 / 0.51295337 | 1.9633508 / 191 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `0e1a9b29c06edb8d35777bdfb42cbaec449c055c90d9e3833b3d5821c11ff1a6` | 0.99103139 / 0.9954955 / 0.99325843; 0.82959641 / 0.83333333 / 0.83146067; 0.62331839 / 0.62612613 / 0.6247191 | 2.6334842 / 221 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `0e48121f5d29105649e24746a81c352915ba49721b7d01a8ad044b6024f27fca` | 0.97368421 / 1 / 0.98666667; 0.81578947 / 0.83783784 / 0.82666667; 0.13157895 / 0.13513514 / 0.13333333 | 3.0405405 / 74 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `0f6abcad32f34cacadef4e66c025546e823760952e53bc026cefb1f82bba3eb5` | 1 / 1 / 1; 0.92682927 / 0.92682927 / 0.92682927; 0.15853659 / 0.15853659 / 0.15853659 | 1.7560976 / 82 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `0fe64d212bd5310431032584b6471a33086b1421184b1fcc9bb412b286acd327` | 0.95783133 / 0.87603306 / 0.91510791; 0.81927711 / 0.74931129 / 0.78273381; 0.015060241 / 0.013774105 / 0.014388489 | 3.9937107 / 318 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `0fee9ae07e0a76500e44f462ad1e363160354f8e9f9a8f7678326e9843faa809` | 0.98816568 / 0.9364486 / 0.96161228; 0.87968442 / 0.83364486 / 0.85604607; 0.47928994 / 0.45420561 / 0.46641075 | 3.011976 / 501 | 0 / 0 / 0 | deterministic_observed |
| piano_amt | `11250fff243bdf89e5bbcbb9dc2ad6bbee92f2f25fec4fa1af5b55e8a50d6b5d` | 0.97683398 / 0.97307692 / 0.97495183; 0.88416988 / 0.88076923 / 0.88246628; 0.11583012 / 0.11538462 / 0.11560694 | 2.9644269 / 253 | 0 / 0 / 0 | deterministic_observed |

Raw slot states, all matching pair indices/sorted inputs, censor counts, normalized hashes and individual repeat scores remain in the verified ledger.
Preflight inputs and four fresh smoke runs are excluded from the 36-slot denominators; session budget includes their execution and diagnostics.
The report changes no product provider or fallback configuration. Only an installed, verified, integrated provider can be used for fallback.
