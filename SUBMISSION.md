# Fablet

**Your curiosity, brought to life.** Fablet is a native iPhone audiobook studio for commissioning and listening to personalized audio documentaries.

## Hackathon demo

1. Run the **Fablet** scheme on an iPhone simulator.
2. Open **Library** and play **Locally narrated sample**. The 70.7-second sample is original text narrated locally with macOS speech synthesis; it is not a Convex production.
3. Pause or seek in the player.
4. Open **Create**, enter a topic, and submit it. In demo mode this saves a local queued record; it does not generate audio.

## Technology

SwiftUI, AVFoundation/AVPlayer, MediaPlayer, Convex, Auth0, Python, FFmpeg, and S3-compatible object storage.

The live backend, account authentication, storage credentials, and production worker are not yet connected end to end. Do not claim that a newly queued demo job produced the prerecorded sample.
