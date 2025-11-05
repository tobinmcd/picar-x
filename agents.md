# Picar-X Agents Guide

This repository bundles the low-level `picarx` Python package together with higher-level GPT-driven assistants located under `gpt_examples/`. Use this guide to configure and operate the conversational agents that control the Picar-X hardware.

## Repository Landmarks
- `picarx/`: Motor, servo, sensor, TTS/STT shims that re-export hardware helpers from `robot_hat`.
- `gpt_examples/gpt_car.py`: Primary GPT agent that fuses vision, speech, and motion control.
- `gpt_examples/openai_helper.py`: Wrapper around the OpenAI Assistants API for dialogue, transcription, and speech synthesis.
- `gpt_examples/preset_actions.py`: Library of movement macros that the assistant can trigger.
- `example/`: Stand-alone scripts that showcase specific behaviors without LLM integration.

## Prerequisites
- Install SunFounder runtime dependencies (`robot-hat`, `vilib`, `sunfounder_controller`, etc.) following the docs linked in `README.md`.
- Python packages for GPT integration (install with `sudo pip3 ... --break-system-packages` when not in a venv):
  - `openai`
  - `openai-whisper`
  - `SpeechRecognition`
  - `sox` (and system packages `python3-pyaudio`, `sox`)
- Ensure the Robot HAT speaker switch is enabled (`pinctrl set 20 op dh` or `robot-hat enable_speaker`), as the GPT agent will attempt to play audio.

## Configure API Credentials
1. Generate an OpenAI API key and create an Assistant tailored to the Picar-X (see `gpt_examples/README.md` for prompt suggestions).
2. Populate `gpt_examples/keys.py` with:
   - `OPENAI_API_KEY`
   - `OPENAI_ASSISTANT_ID`
3. Optionally customize assistant behavior:
   - `gpt_examples/gpt_car.py`: `LANGUAGE`, `TTS_VOICE`, `VOICE_INSTRUCTIONS`, and `VOLUME_DB`.
   - `gpt_examples/preset_actions.py`: adjust or add motion macros referenced by assistant responses.

## Running the GPT Car Agent
- Voice-first mode with camera streaming (default):
  ```bash
  sudo python3 gpt_examples/gpt_car.py
  ```
- Keyboard-driven conversations:
  ```bash
  sudo python3 gpt_examples/gpt_car.py --keyboard
  ```
- Disable image capture if bandwidth or camera access is an issue:
  ```bash
  sudo python3 gpt_examples/gpt_car.py --keyboard --no-img
  ```
- Expected runtime behavior:
  - Initializes `Picarx()` to reset servos, motors, and sensors.
  - Starts Vilib streaming when `--no-img` is not supplied; snapshots are sent with each prompt for visual context.
  - Manages audio capture through `speech_recognition` and sends clips to Whisper (either via OpenAI helper or direct API call).
  - Converts assistant replies into actionable JSON (e.g., `{"actions": ["shake_head"], "answer": "Hi!"}`); actions are dispatched to the matching helpers in `preset_actions.py`.
  - Uses `robot_hat.Music` for TTS playback and LED status signals to reflect thinking/action phases.

## Voice Pipeline Notes
- Whisper transcription can run via two paths:
  - `OpenAiHelper.stt()` sends recorded audio to `whisper-1`.
  - `OpenAiHelper.speech_recognition_stt()` leverages `SpeechRecognition`’s Whisper API client; configure `LANGUAGE` to bias recognition.
- TTS output is post-processed with `sox` to boost volume; ensure `sox` is installed and accessible.
- Audio playback and microphone access typically require `sudo`, hence all example commands run with elevated privileges.

## Extending or Troubleshooting
- Adding new motions: create a function in `gpt_examples/preset_actions.py` that accepts a `Picarx` instance, then reference its string key inside the assistant prompt and action dispatch block.
- Custom prompts: adjust the Assistant description in the OpenAI dashboard to teach the agent when to issue `actions` versus pure dialogue.
- Vision tuning: modify Vilib initialization in `gpt_examples/gpt_car.py` (flip settings, streaming targets) or skip camera usage with `--no-img`.
- Diagnostics:
  - Watch stdout logs for `user` / assistant exchanges emitted by `openai_helper.chat_print`.
  - Hardware issues (no sound, servo errors) usually surface during `Picarx()` initialization or `Music.sound_play()` calls; confirm Robot HAT drivers and permissions.

## Alternative Entry Points
- `example/` scripts provide deterministic behaviors (line tracking, obstacle avoidance, etc.) when you need to test hardware without GPT involvement.
- `picarx.voice_assistant.VoiceAssistant` re-exports the Robot HAT assistant class for building custom pipelines if you prefer not to use the bundled GPT workflow.
