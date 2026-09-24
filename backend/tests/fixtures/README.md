# Test fixtures

* `soundscape_30s.flac`: first 30 seconds of `birdnet_analyzer/example/soundscape.wav`
  from BirdNET-Analyzer (https://github.com/birdnet-team/BirdNET-Analyzer,
  MIT-licensed repository). Used to pin BirdNET adapter output shape and a
  small set of expected species. Synthetic fixtures (tones, silence, noise,
  corrupt bytes, MP3/M4A transcodes) are generated at test time in
  `tests/conftest.py` and are not committed.
