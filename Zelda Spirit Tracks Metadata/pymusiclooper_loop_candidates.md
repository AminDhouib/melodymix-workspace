# Spirit Tracks PyMusicLooper Candidate Pass

Generated from MP3/YouTube-derived local source audio using PyMusicLooper as a candidate generator.
This report does not authorize deletion or replacement by itself; waveform review and listening remain required.

Run settings: `uvx --python 3.11 --from pymusiclooper`, WAV cache `.render-work\pymusiclooper-cache`, top `10`, minimum loop duration `10.0` seconds.

Classification guide:

- `strong_pml_candidate`: best PyMusicLooper score >= 0.99.
- `usable_pml_candidate_review`: score >= 0.90.
- `weak_pml_candidate_review`: score >= 0.75.
- `poor_pml_candidate`: score below 0.75.
- `no_pml_candidates`: PyMusicLooper did not return loop points.

## Counts

| Scope | Classification | Count |
|---|---|---:|
| All | strong_pml_candidate | 43 |
| All | usable_pml_candidate_review | 8 |
| All | poor_pml_candidate | 4 |
| All | no_pml_candidates | 2 |
| Uploaded | strong_pml_candidate | 25 |
| Uploaded | usable_pml_candidate_review | 3 |
| Uploaded | poor_pml_candidate | 2 |

## Best Candidate Per Track

| Uploaded | Order | Track | Title | Waveform Class | PML Class | Best Start | Best End | Best Len | Score |
|---|---:|---:|---|---|---|---:|---:|---:|---:|
| True | 2 | 24 | Ghost Zelda | full_track_review_unique_tail | strong_pml_candidate | 7.982833333333334 | 21.684604166666666 | 13.701770833333333 | 0.998088 |
| True | 3 | 25 | Zelda Wondering | full_track_review_unique_tail | strong_pml_candidate | 19.402125 | 119.25308333333334 | 99.85095833333334 | 0.999321 |
| True | 4 | 26 | The Spirit Flute | manual_loop_point_review | strong_pml_candidate | 32.3851875 | 49.7175625 | 17.332375 | 0.999188 |
| True | 5 | 28 | Inside a Cave | full_track_review_unique_tail | strong_pml_candidate | 42.1359375 | 106.15320833333334 | 64.01727083333334 | 0.995691 |
| True | 6 | 29 | The Ominous Broken Tower | full_track_review_unique_tail | poor_pml_candidate | 5.729 | 17.865979166666666 | 12.136979166666666 | 0.733483 |
| True | 8 | 32 | Zelda in a Panic | full_track_review_unique_tail | strong_pml_candidate | 21.439229166666667 | 101.43920833333334 | 79.99997916666668 | 0.999687 |
| True | 12 | 38 | Zelda Possesses a Phantom | full_track_review_unique_tail | strong_pml_candidate | 20.158625 | 47.32814583333333 | 27.16952083333333 | 0.999455 |
| True | 16 | 42 | Selecting a Rail Route | full_track_review_unique_tail | strong_pml_candidate | 11.412895833333334 | 25.334104166666666 | 13.921208333333333 | 0.991530 |
| True | 17 | 44 | Battle on the Tracks | manual_loop_point_review | strong_pml_candidate | 4.489520833333334 | 25.365229166666666 | 20.875708333333332 | 0.997274 |
| True | 21 | 48 | Whittleton | manual_loop_point_review | strong_pml_candidate | 38.197875 | 80.67302083333334 | 42.475145833333336 | 0.993733 |
| True | 22 | 49 | The Lost Woods | manual_loop_point_review | usable_pml_candidate_review | 25.290375 | 47.18985416666667 | 21.89947916666667 | 0.969877 |
| True | 27 | 54 | Sanctuary | full_track_review_unique_tail | strong_pml_candidate | 44.810770833333336 | 103.60825 | 58.79747916666666 | 0.998703 |
| True | 30 | 57 | Forest, Snow and Ocean Temple | ambiguous_boundary_review | strong_pml_candidate | 17.936333333333334 | 78.37575 | 60.43941666666666 | 0.996527 |
| True | 35 | 63 | Mini Boss (Dungeon) | full_track_review_unique_tail | strong_pml_candidate | 23.0091875 | 71.019125 | 48.00993750000001 | 0.996627 |
| True | 36 | 62 | Dungeon Gauntlet | full_track_review_unique_tail | strong_pml_candidate | 27.2879375 | 45.294020833333335 | 18.006083333333333 | 0.998742 |
| True | 39 | 68 | The Force Gem Awakens | full_track_review_unique_tail | usable_pml_candidate_review | 10.124916666666667 | 22.92 | 12.795083333333334 | 0.919517 |
| True | 40 | 69 | Restoring the Spirit Tracks | full_track_review_unique_tail | poor_pml_candidate | 11.01875 | 28.319875 | 17.301125 | 0.504856 |
| True | 42 | 71 | Dark Trains Approaching | full_track_review_unique_tail | strong_pml_candidate | 13.732041666666667 | 32.09739583333333 | 18.365354166666663 | 0.990529 |
| True | 43 | 72 | Sword Training | full_track_review_no_clean_waveform_match | usable_pml_candidate_review | 10.718416666666666 | 28.844083333333334 | 18.125666666666667 | 0.988789 |
| True | 44 | 73 | Intense Sword Training | full_track_review_unique_tail | strong_pml_candidate | 12.672354166666667 | 29.9754375 | 17.303083333333333 | 0.997703 |
| True | 45 | 74 | Catching a Rabbit | full_track_review_unique_tail | strong_pml_candidate | 13.28875 | 40.722875 | 27.434125 | 0.992596 |
| True | 46 | 75 | Cursed Overworld | full_track_review_unique_tail | strong_pml_candidate | 24.224854166666667 | 96.96927083333334 | 72.74441666666667 | 0.996048 |
| True | 47 | 76 | Anouki Village | full_track_review_unique_tail | strong_pml_candidate | 18.854479166666668 | 71.8211875 | 52.96670833333333 | 0.998074 |
| True | 51 | 80 | The Great Eye in the Dark | full_track_review_unique_tail | strong_pml_candidate | 9.045125 | 70.015875 | 60.970749999999995 | 0.994351 |
| True | 53 | 83 | Beedle's Air Shop | full_track_review_no_clean_waveform_match | strong_pml_candidate | 11.230625 | 75.78595833333334 | 64.55533333333334 | 0.997952 |
| True | 54 | 84 | Mini Boss (Tower of Spirits) | manual_loop_point_review | strong_pml_candidate | 8.789479166666666 | 164.83197916666666 | 156.0425 | 0.996484 |
| True | 56 | 86 | Linebeck III | full_track_review_unique_tail | strong_pml_candidate | 10.5645625 | 44.85727083333333 | 34.29270833333333 | 0.996510 |
| True | 60 | 91 | The Wise One | full_track_review_no_clean_waveform_match | strong_pml_candidate | 35.22975 | 111.611 | 76.38125 | 0.996970 |
| True | 65 | 96 | Pirate Attack! | full_track_review_unique_tail | strong_pml_candidate | 18.9219375 | 31.477875 | 12.555937500000002 | 0.990273 |
| True | 67 | 98 | Underwater | full_track_review_unique_tail | strong_pml_candidate | 18.00825 | 132.168375 | 114.160125 | 0.998345 |
| False | 68 | 99 | Approaching Phytops | full_track_review_unique_tail | strong_pml_candidate | 8.688520833333333 | 69.66389583333333 | 60.97537499999999 | 0.994939 |
| False | 69 | 100 | Phytops, Barbed Menace | full_track_review_unique_tail | usable_pml_candidate_review | 21.472666666666665 | 100.73560416666666 | 79.26293749999999 | 0.989164 |
| False | 70 | 101 | Whip Race | full_track_review_no_clean_waveform_match | strong_pml_candidate | 6.971 | 54.98679166666667 | 48.01579166666667 | 0.995159 |
| False | 71 | 102 | Byrne | manual_loop_point_review | strong_pml_candidate | 43.391333333333336 | 107.80410416666666 | 64.41277083333333 | 0.998075 |
| False | 72 | 103 | Goron Village | manual_loop_point_review | strong_pml_candidate | 33.78175 | 89.61235416666666 | 55.83060416666666 | 0.998031 |
| False | 73 | 104 | Lokomo Song: Embrose | full_track_review_unique_tail | usable_pml_candidate_review | 7.755125 | 18.43625 | 10.681125000000002 | 0.960547 |
| False | 74 | 105 | Get the Key! | full_track_review_unique_tail | strong_pml_candidate | 15.350895833333333 | 28.747916666666665 | 13.397020833333332 | 0.992323 |
| False | 75 | 106 | Fire and Sand Temple | full_track_review_no_clean_waveform_match | strong_pml_candidate | 53.815020833333335 | 98.82291666666667 | 45.007895833333336 | 0.999393 |
| False | 76 | 108 | Tower of Spirits (Staircase) | full_track_review_unique_tail | strong_pml_candidate | 2.112125 | 40.51766666666666 | 38.405541666666664 | 0.992361 |
| False | 78 | 111 | Resurrection of the Demon King | full_track_review_unique_tail | no_pml_candidates |  |  |  |  |
| False | 79 | 112 | Fleeing by Demon Train | full_track_review_unique_tail | strong_pml_candidate | 12.199854166666666 | 45.547666666666665 | 33.347812499999996 | 0.998430 |
| False | 80 | 113 | Lokomo Song: Rael | full_track_review_unique_tail | usable_pml_candidate_review | 4.972875 | 20.628458333333334 | 15.655583333333334 | 0.989393 |
| False | 81 | 114 | Skeldritch, Ancient Demon | full_track_review_unique_tail | strong_pml_candidate | 28.690041666666666 | 107.95770833333333 | 79.26766666666666 | 0.990083 |
| False | 84 | 117 | Fighting Dark Link | full_track_review_unique_tail | strong_pml_candidate | 22.003208333333333 | 92.4071875 | 70.40397916666667 | 0.994917 |
| False | 85 | 120 | Before the Final Battle | full_track_review_unique_tail | strong_pml_candidate | 73.076625 | 130.67822916666665 | 57.60160416666665 | 0.999796 |
| False | 86 | 121 | The Revival's Completion | full_track_review_no_clean_waveform_match | strong_pml_candidate | 13.8451875 | 32.43960416666667 | 18.594416666666667 | 0.994699 |
| False | 87 | 123 | The Unenterable Body | full_track_review_unique_tail | usable_pml_candidate_review | 9.781270833333334 | 49.514541666666666 | 39.733270833333336 | 0.987155 |
| False | 88 | 124 | Byrne Comes to the Rescue | full_track_review_unique_tail | strong_pml_candidate | 18.3755 | 70.63491666666667 | 52.25941666666667 | 0.992818 |
| False | 90 | 126 | Byrne's Death | full_track_review_unique_tail | poor_pml_candidate | 11.775645833333334 | 25.056125 | 13.280479166666668 | 0.548263 |
| False | 94 | 130 | Malladus in Cole's Body | full_track_review_unique_tail | no_pml_candidates |  |  |  |  |
| False | 95 | 132 | Link and Zelda's Duet | full_track_review_unique_tail | poor_pml_candidate | 19.5885625 | 35.8394375 | 16.250875000000004 | 0.612504 |
| False | 96 | 134 | Saying Goodbye | manual_loop_point_review | strong_pml_candidate | 62.54035416666667 | 140.38558333333333 | 77.84522916666666 | 0.998707 |
| False | 98 | 137 | Battle Mode | full_track_review_no_clean_waveform_match | strong_pml_candidate | 27.278458333333333 | 70.72710416666666 | 43.44864583333333 | 0.994740 |
| False | 99 | 138 | Battle Mode (Linebeck Remix) | full_track_review_unique_tail | strong_pml_candidate | 13.2270625 | 25.696 | 12.468937500000001 | 0.995113 |
| False | 101 | 140 | Ready, Set, Battle! | full_track_review_unique_tail | strong_pml_candidate | 15.477520833333333 | 42.8378125 | 27.360291666666665 | 0.995097 |
| False | 103 | 142 | Spotted! (Battle Phantoms) | full_track_review_unique_tail | usable_pml_candidate_review | 31.45339583333333 | 64.99295833333333 | 33.5395625 | 0.989148 |
| False | 104 | 143 | Battle Mode Results | full_track_review_unique_tail | strong_pml_candidate | 5.49375 | 20.501416666666668 | 15.007666666666667 | 0.994848 |
