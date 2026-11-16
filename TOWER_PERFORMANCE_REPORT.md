# Tower expressive mix: verification and handoff

The original master is preserved at `outputs/tower_revised/master_performance_fixed.mp3`.
Cached comparison assets are in `outputs/tower_expressive_experiment_recovered_20261116T003930247029Z/`:

- `baseline_unchanged.mp3`: byte-identical baseline; SHA-256 `cc847381f53342319e24a152b6a17f2cd410c8f4559dd154ae7c0bac4664b6d8`.
- `mix_only.mp3`: original speech, revised mix.
- `performance_and_mix_verified.mp3`: retained regenerated dialogue and reaction, revised mix, rendered again with the bounded renderer; SHA-256 `29cb809ab6fbdbe65719b11380026b559a976e3d513e9e3fa4d3074beca647fe`.

These generated outputs are ignored by Git and remain local. No new provider calls were made for the verified render. Intermediate stems, timelines, cue sheets, ASR evidence and the earlier technical report remain in the output directory. The original master hash was checked before and after rendering.

## Objective measurements

FFmpeg `loudnorm` **input** readings are of the encoded masters. RMS is measured on the complete master over ASR-derived windows, includes pauses, and the Snape window includes the impact. Boundaries differ between performances, so values are not matched samples or subjective acting scores.

| Master | Integrated LUFS | True peak dBTP | Dumbledore RMS dBFS | Snape RMS dBFS | Reaction RMS dBFS |
|---|---:|---:|---:|---:|---:|
| Baseline | -16.82 | -1.88 | -18.7 | -16.8 | -20.8 |
| Mix only | -17.32 | -2.00 | -20.9 | -15.7 | -23.2 |
| Performance and mix, verified | -17.53 | -1.95 | -22.5 | -16.0 | -23.0 |

The verified performance has a 6.5 dB difference between the Dumbledore and Snape master windows, versus 1.9 dB in the baseline, but that comparison includes different speech and impact timing. Its pre-master voice-minus-background RMS is +3.1 dB during the Dumbledore window, +8.8 dB in the spell window before the impact, and +3.0 dB during the reaction. These linear bus measurements are not isolated post-loudnorm master tracks and do not establish intelligibility. The verified master passed basic format, sample-peak and planned-silence checks; its final MP3 true peak is 0.05 dB above the requested -2 dBTP target.

## Provenance and QA limits

- The regenerated dialogue stem's cache key matches the saved screenplay, locked cast, and v4 inputs: Dumbledore was directed `restrained`/`soft`, and Snape `restrained`/`normal`. The proposed later `pleading`/`projected` direction was **not** used to generate that stem. This corrects any contrary interpretation of the earlier experiment. The saved narration and dialogue voice metadata match the locked registry; narrator and Dumbledore share a registry voice. Provider segment alignment for the new block passes bounds and voice-ID checks, but cannot prove audible speaker consistency.
- Retained stem ASR reviews report no differences or suspected repetitions. The earlier performance-and-mix master ASR found no differences or repetitions; it is bound to the earlier master, not the newly rendered file. On mix-only, Whisper omitted the incantation while the secondary transcription included it. ASR and impact timing require human verification. The verified master has not undergone a new master transcription or a human listen.
- The prior mixes share authored ducking and gain settings, not necessarily identical time envelopes: word-timestamp placement, timing differences and the shared reaction start influence the comparison. The impact uses an approximate word timestamp. No standalone human breath was verified or added. Artistic delivery, narration intelligibility, acoustic discontinuities, mono/headphone translation and final suitability remain unverified; these files are not publication-ready.
- The current renderer's spatial setting applies to a whole contextual dialogue block. Per-turn positions are reported unresolved when they cannot be represented; distance direction currently changes gain, not frequency-dependent distance filtering. Acoustic environment references remain metadata, and reflections are explicitly opt-in. No position was invented for this Tower mix. Gain offsets are authored, not derived from short-term level measurement, and final master `loudnorm` can affect dynamics. Scheduled ducking uses whole speech-item intervals. Explicit mix item indices must refer to the final timeline order.
- Full regression suite: 65 passed. The renderer now bounds FFmpeg padding by samples and duration; the old unbounded graph hung during testing. Spatial placement retains content from both channels rather than dropping the opposite channel.

Official ElevenLabs documentation states v4 supports audio tags and Stability/Similarity, but not Style or Speed; tag responsiveness varies. See https://elevenlabs.io/docs/overview/capabilities/text-to-speech/eleven-v4 and https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert.