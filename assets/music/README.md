# Music beds

The production image generates four original instrumental beds into this
folder during its build. They rotate deterministically between Shorts, are
safe to publish, and need no third-party recording or licence.

Licensed tracks can still be placed here. They join the same deterministic
rotation and must be cleared for YouTube publication.

- Supported: `.mp3 .m4a .wav .ogg .opus .flac`
- One track is picked per Short by hashing its content id, so a re-render sounds
  identical and consecutive Shorts move through whatever is here.
- A track shorter than the Short is looped; a longer one is trimmed. Both ends
  are faded, and the bed ducks 11.5 dB whenever a word is spoken.
- The bundled originals use different tempos, arrangements and harmonic
  progressions so consecutive Shorts do not all sound alike.

**Licensing is not checked for additional files.** Only add audio that you are
allowed to publish on YouTube, and retain the licence or receipt.
