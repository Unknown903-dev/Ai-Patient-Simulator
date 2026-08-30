# Architecture

## Overview

The project is an automated patient that places real outbound calls to a healthcare office agent. Twilio handles the PSTN call and bidirectional media stream, FastAPI bridges the realtime connection, and one Gemini Live session acts as the patient for the entire conversation.

```text
make_call.py
    |
    | creates outbound call and selects scenario
    v
Twilio Voice <----> target office agent
    |
    | bidirectional G.711 mu-law media stream
    v
FastAPI /media-stream
    |
    | manual activity boundaries and audio conversion
    v
Gemini Live patient
```

During local development, Cloudflare Tunnel exposes the FastAPI HTTPS and WebSocket endpoints. `MEDIA_STREAM_URL` identifies the public `/media-stream` endpoint. The same public host is used to derive the `/recording-status` callback URL.

## Main Components

### `make_call.py`

The caller validates the requested scenario through the choices in `scenarios.py`, builds TwiML, and starts an outbound Twilio call. The selected scenario is attached to the media stream as a custom parameter.

Calls are created with recording enabled, dual recording channels, and `completed` and `absent` recording status events. Initial metadata is written as soon as Twilio returns the Call SID.

### `server.py`

The FastAPI service provides three endpoints:

- `GET /` for a basic health response
- `WebSocket /media-stream` for Twilio audio and playback events
- `POST /recording-status` for Twilio recording callbacks

The media stream start event supplies both the Stream SID and Call SID. The server uses the Stream SID for realtime playback and the Call SID to associate recording metadata and transcripts with the correct call.

### `scenarios.py`

Scenarios remain separate from realtime audio handling. Each scenario defines:

- caller identity and date of birth
- goal
- known facts
- preferences
- behavioral constraints
- an optional end-of-speech silence override

`build_system_instruction` combines the selected scenario with shared conversation, memory, completion, and goodbye rules. The server does not require scenario-specific branches.

## Realtime Audio Path

### Office To Gemini

Twilio sends 8 kHz G.711 mu-law audio. The server:

1. decodes base64 media payloads
2. converts mu-law to signed PCM
3. measures RMS for manual speech detection
4. resamples the audio from 8 kHz to 16 kHz
5. sends active speech to Gemini in approximately 40 ms chunks

Inactive audio is not forwarded to Gemini. About 100 ms of local pre-roll is retained and sent once with the next `ActivityStart` so the beginning of speech is preserved.

### Gemini To Office

Gemini returns 24 kHz PCM audio. The server resamples it to 8 kHz, converts it to G.711 mu-law, base64 encodes it, and sends Twilio media events over the active WebSocket.

Both directions remain active concurrently for the life of the call.

## Manual Turn Detection

Gemini automatic activity detection is disabled. The server uses a local RMS threshold of 500 and explicitly sends:

```text
ActivityStart
    |
    v
active office audio
    |
    v
ActivityEnd
```

The normal end-of-speech silence threshold is 1200 ms. Scenarios can override it; `barge_in_test` uses 450 ms to exercise interruption behavior.

Diagnostic logs include office turn numbers, speech-start RMS, silence checkpoints, silence resets, bytes sent, Gemini acknowledgements, and stall warnings. These logs help distinguish an audio-boundary problem from a model response problem without changing turn behavior.

## Interruption Handling

Each Gemini response is tracked through generation and Twilio playback state. If the office begins speaking while Gemini audio is buffered or playing, the server:

1. sends Gemini `ActivityStart`
2. sends Twilio `clear` to discard buffered patient audio
3. drops remaining audio from the interrupted Gemini response
4. keeps the same Gemini session alive
5. lets the office finish and allows Gemini to respond normally

The clear event is used only when Gemini playback is actually pending. Ordinary office turns do not clear Twilio audio.

## Scenario Completion And Call Lifecycle

Gemini receives a structured `finish_call` tool. It calls the tool only when the scenario goal is resolved or the office cannot help further and the conversation has naturally ended.

After the tool call:

1. Gemini generates one short goodbye
2. the server sends the final audio to Twilio
3. the server sends a named playback mark
4. the call remains active until Twilio reports that mark as played
5. the server intentionally closes the call

If the office speaks before the goodbye finishes, the pending end is cancelled, buffered Gemini audio is cleared when necessary, and the conversation continues.

A completed Gemini response turn does not terminate the phone call. Normal terminal conditions are Twilio `stop`, WebSocket disconnect, an unrecoverable session error, or completion of the intentional final-goodbye mark.

## Transcript Persistence

Gemini Live supplies both transcription directions:

- input audio transcription becomes `OFFICE`
- output audio transcription becomes `PATIENT`

Small streaming fragments are accumulated in memory. Patient text is normally flushed when a Gemini response turn completes. Office text is flushed with a 0.75 second transcript-only debounce after manual `ActivityEnd`, allowing late transcription fragments to join the same utterance.

The transcript clock uses monotonic elapsed time from the start of the Gemini call session. Before saving, remaining partial buffers are flushed and completed events are sorted by elapsed time. The file is written atomically as UTF-8.

## Recording And Artifact Storage

During a live run the application initially associates artifacts with the Twilio Call SID. The final reviewed repository anonymizes those directories with sequential artifact numbers:

```text
ai-voice-tester/artifacts/calls/<artifact_number>/
```

The completed directory normally contains:

```text
recording.mp3
transcript.txt
```

The recording callback accepts URL-encoded Twilio form data. Its `X-Twilio-Signature` is validated against the externally visible request URL and the same parsed form values used for callback processing. Invalid callbacks return HTTP 403 and are not processed.

Completed recordings are downloaded from Twilio with account authentication. Requested dual-channel parameters and MP3 handling are preserved. An `absent` callback stores its status and optional Twilio error code without attempting a download.

Runtime metadata and transcript writes use temporary files followed by atomic replacement. Runtime metadata supports call processing but is removed from the final published artifact set together with Twilio identifiers.

## Evidence And Review Scope

The saved artifacts support manual review and reproduction of office-agent behavior. Confirmed and observed findings are documented in [`ai-voice-tester/bug.md`](./ai-voice-tester/bug.md).

Findings are evaluated from the saved recordings transcripts and metadata. Transcripts are derived from streaming speech recognition, so uncertain proper names or wording are verified against the corresponding dual-channel recording before being treated as definitive evidence.
