"""
Komen AI - Voice Assistant ("Hey Komen").

Runs on the PC, listens continuously through the microphone, and wakes up
when it hears something like "Hey Komen". It replies out loud, then listens
for your actual instruction and hands it to the full agent — same brain as
main.py and telegram_bot.py, just a voice front-end.

How speech works here:
  - Listening/transcription: SpeechRecognition, using Google's free web
    speech API (no API key needed, but requires an internet connection and
    sends short audio clips to Google's servers — see README for a fully
    offline alternative).
  - Talking back: pyttsx3, which is fully offline (uses the OS's built-in
    voice engine — SAPI5 on Windows, NSSpeechSynthesizer on Mac, espeak on
    Linux).

Setup:
    pip install SpeechRecognition pyttsx3 pyaudio
    (see README.md if pyaudio fails to install)

Run:
    python voice_assistant.py
"""
import difflib
import sys

import speech_recognition as sr
import pyttsx3

import config
from agent import KomenAgent

WAKE_PHRASES = [
    "hey komen", "hey coman", "hey comen", "hey command",
    "hey comment", "hey commen", "komen ai", "hey komen ai",
]
WAKE_REPLY = "Hi, how may I help you?"
NO_COMMAND_HEARD_REPLY = "I didn't catch a command, going back to sleep."
TTS_MAX_CHARS = 500  # keep spoken replies from running on forever


def _speak(engine: pyttsx3.Engine, text: str):
    if not text:
        return
    print(f"[Komen AI speaking] {text}")
    engine.say(text[:TTS_MAX_CHARS])
    engine.runAndWait()


def _heard_wake_word(text: str) -> bool:
    """Exact substring match first, then a fuzzy check to survive mishearings
    like 'hey comment' or 'hey command' instead of 'hey komen'."""
    text = text.lower().strip()
    if any(phrase in text for phrase in WAKE_PHRASES):
        return True
    # Fuzzy fallback: compare the first two words against "hey komen"
    words = text.split()
    if len(words) >= 2:
        first_two = " ".join(words[:2])
        ratio = difflib.SequenceMatcher(None, first_two, "hey komen").ratio()
        if ratio > 0.7:
            return True
    return False


def main():
    if not config.PROVIDER_SPECS:
        print("ERROR: no LLM providers configured (set an API key, see README)")
        sys.exit(1)

    recognizer = sr.Recognizer()
    tts_engine = pyttsx3.init()
    agent = KomenAgent(verbose=True)

    try:
        mic = sr.Microphone()
    except OSError as e:
        print(f"ERROR: no working microphone found ({e}). "
              f"On Linux, make sure pyaudio and a working ALSA/PulseAudio setup are installed.")
        sys.exit(1)

    with mic as source:
        print("Calibrating for background noise... stay quiet for a second.")
        recognizer.adjust_for_ambient_noise(source, duration=1)

    print('Komen AI voice assistant is listening. Say "Hey Komen" to wake it up. Ctrl+C to stop.')

    while True:
        try:
            with mic as source:
                audio = recognizer.listen(source, timeout=None, phrase_time_limit=6)

            try:
                heard = recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                continue  # heard noise, not words — keep listening silently
            except sr.RequestError as e:
                print(f"[Komen AI] Speech recognition service error: {e}")
                continue

            print(f"[Komen AI heard] {heard}")

            if not _heard_wake_word(heard):
                continue

            _speak(tts_engine, WAKE_REPLY)

            # Listen for the actual command
            with mic as source:
                command_audio = recognizer.listen(source, timeout=6, phrase_time_limit=15)

            try:
                command_text = recognizer.recognize_google(command_audio)
            except (sr.UnknownValueError, sr.RequestError):
                _speak(tts_engine, NO_COMMAND_HEARD_REPLY)
                continue

            print(f"[Komen AI command] {command_text}")
            result = agent.run_task(command_text)
            _speak(tts_engine, result or "Done.")

        except KeyboardInterrupt:
            print("\nStopping voice assistant.")
            break
        except sr.WaitTimeoutError:
            continue  # no command heard after wake word, just resume listening


if __name__ == "__main__":
    main()
