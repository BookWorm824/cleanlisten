# CleanListen & CleanView

Two separate Windows apps for cleaning up media you own. Each has its own icon and
window, so you can clean an audiobook and a movie at the same time. Everything runs on your own computer;
nothing is uploaded.

## CleanListen — audiobooks

- Transcribes the audiobook and mutes swearing, mild language and God's name used as a swear.
- Flags explicit sex scenes for you to review; only the ones you approve are cut.
  Kissing and romance are left alone.
- Optional ebook cross-check (EPUB/PDF/TXT) catches words the narrator mumbles.
- Optional chapter splitting for Yoto Make Your Own cards (60-minute tracks, 5-hour cards).

Works with DRM-free audio (for example MP3s from Libro.fm). Copy-protected Audible and
Kindle files can't be used.

## CleanView — movies and TV episodes

- Mutes the same language list, listening to the dialogue channel of surround-sound movies,
  and uses the movie's subtitles (a matching .srt or a text track inside the file) to catch
  extra words. Writes cleaned subtitles into the clean copy.
- Filters you can switch on or off: sexual references, nudity, sex scenes, immodest clothing,
  sleeping around, man & woman kissing and same-sex kissing (keep / cut passionate / cut all),
  same-sex relationships, unmarried couples living or sleeping together, violence, graphic
  gore, smoking, drinking and drug use. Your choices are remembered.
- How it finds things:
  - NudeNet checks the picture twice a second for nudity.
  - CLIP (OpenAI's free image model) checks it once a second for kissing, couples in bed,
    gore, fights, weapons, smoking, drinking, drugs and revealing clothes, so scenes are
    caught even when they're silent.
  - A sound model listens for gunfire, explosions, screaming and blows.
  - The optional AI helper (Ollama running gemma3:4b on your PC) double-checks each scene
    the picture model found (who is kissing, light or passionate, is it really gore) and
    reads the dialogue for sexual references, sleeping around and relationship talk.
- Scenes are cut; flagged dialogue lines are muted. Everything is listed first with blurred
  stills and a Preview button, and only what you leave ticked is changed.
- Pick a folder of episodes to clean a whole season in one go.
- Saves "(Clean)" copies plus a report of every mute and cut. Originals are never changed.
  Uses an NVIDIA, Intel or AMD graphics card to save faster when one is available.

Works with DRM-free video (DVD and Blu-ray rips, home videos). Copy-protected purchases
from iTunes, Vudu, Movies Anywhere and streaming services can't be used. 4K HDR files come
out with flatter colours after a cut. The AI checks are good but not perfect, which is why
everything is shown to you before it's cut.

One-time downloads: the picture and sound checkers (about 250 MB) the first time CleanView
looks for scenes, and Ollama plus its AI model (about 4 GB) if the AI helper is on.

CleanView gets its own desktop and Start-menu icon the first time CleanListen updates.

The installed apps check this repository for updates each time they open.
