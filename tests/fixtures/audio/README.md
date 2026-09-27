# Basic Pitch smoke audio fixture

`basic_pitch_smoke.wav` is derived from **Emotional piano.wav**, a 16-second piano recording by triangelx.

- Wikimedia Commons file page: https://commons.wikimedia.org/wiki/File:Emotional_piano.wav
- Original Freesound recording: https://freesound.org/people/triangelx/sounds/189175/
- License: Creative Commons CC0 1.0 Universal Public Domain Dedication. The Wikimedia file page identifies the file as CC0, and the original Freesound item shows the same license. Redistribution and modification are permitted without attribution; the author and source are credited here for traceability.
- Original format: WAV, 44,100 Hz, stereo, 16-bit PCM, 16 seconds, 2,822,444 bytes.
- Retrieved original SHA-1: `E8C449FBA4FE1EB5E67E0923B6B696F2105584C5` (matches the checksum shown in the Wikimedia file page).
- Retrieved original SHA-256: `9661F81D37C59F230B324B830AB68C0482336AF3EC117C92E73108FFB4095F15`.

The checked-in fixture is the complete recording downmixed to mono by averaging its two channels, resampled from 44,100 Hz to 22,050 Hz with `scipy.signal.resample_poly(up=1, down=2)`, and written as 16-bit PCM WAV. It is 16 seconds long with 352,800 frames.

- Fixture SHA-256: `2970C7FCA3CCC442C078EB0A4EDB2F788731E9D36F5049CC2558FA68E599366A`.
- The fixture is reserved for the optional `ml_integration` smoke test. Its input format matches the worker contract; it is not a general accuracy benchmark.
