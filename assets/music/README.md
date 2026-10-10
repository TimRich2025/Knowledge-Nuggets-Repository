# Music beds

Drop licensed audio files here and the renderer will use them. When this folder
is empty, the renderer generates an original ambient bed locally so the Short
still has background sound without relying on a third-party recording.

- Supported: `.mp3 .m4a .wav .ogg .opus .flac`
- One track is picked per Short by hashing its content id, so a re-render sounds
  identical and consecutive Shorts move through whatever is here.
- A track shorter than the Short is looped; a longer one is trimmed. Both ends
  are faded, and the bed ducks 11.5 dB whenever a word is spoken.
- Two or three tracks are enough to stop the channel sounding repetitive; more
  is better.

**Licensing is not checked anywhere in this pipeline.** Only put audio here that
you are allowed to publish on YouTube, and keep the licence or receipt for each
file somewhere you can find it. Music that is free to listen to is not
automatically free to publish under a video.
