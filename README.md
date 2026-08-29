# call-automation

## 📊 Repository Traffic

![Repository Traffic](./docs/traffic.svg)

# AI Patient Voice Tester

Automated Python voice bot for testing the Pretty Good AI healthcare phone agent.

The bot places real outbound phone calls, behaves like a patient using Gemini Live, holds multi-turn voice conversations, and runs reusable scenarios designed to test normal workflows and edge cases in the target AI agent.

## Current Status

* [x] Outbound Twilio calling
* [x] FastAPI WebSocket server
* [x] Twilio bidirectional Media Streams
* [x] Incoming phone audio streamed to Python
* [x] Gemini Live realtime patient
* [x] Bidirectional realtime audio
* [x] Manual voice activity detection
* [x] Multi-turn conversational behavior
* [x] Scenario-driven patient behavior
* [x] Barge-in and interruption handling
* [x] Conversation memory across turns
* [x] Structured scenario completion
* [x] Natural goodbye and call termination
* [x] Identity verification edge-case scenario
* [x] Prompt-injection testing scenario
* [ ] Call recording export
* [ ] Persistent transcript files
* [ ] Automated QA evaluation
* [ ] Bug report
* [ ] 10+ final submission calls

## How It Works

```text
Pretty Good AI test agent
          ↕
         PSTN
          ↕
        Twilio
          ↕
Bidirectional Media Stream
          ↕
   Cloudflare Tunnel
          ↕
 FastAPI WebSocket Server
          ↕
      Gemini Live
```

Twilio places the outbound call and opens a bidirectional Media Stream to the FastAPI server.

Incoming telephone audio is decoded from G.711 μ-law, converted to PCM, resampled, and streamed to Gemini Live. Gemini generates the simulated patient's speech, which is converted back to Twilio-compatible μ-law audio and streamed into the active call.

One Gemini Live session is maintained for the entire conversation so the patient can remember previously discussed information and remain consistent across turns.

## Turn Detection

Telephone audio made automatic endpoint detection unreliable during early testing. Gemini sometimes combined multiple office prompts into one turn or waited until the office repeated itself before responding.

The final implementation disables Gemini automatic activity detection and performs local RMS-based voice activity detection.

The application explicitly sends:

```text
ActivityStart
    ↓
office audio
    ↓
ActivityEnd
```

when speech begins and ends.

Normal scenarios use a 600 ms silence threshold. Individual stress-test scenarios can override this value.

Twilio playback marks are used to determine when Gemini audio has finished playing. If the office begins speaking while Gemini audio is still buffered, the application sends a Twilio `clear` event and allows the office to take the turn.

## Scenario System

Patient behavior is defined separately from the realtime audio code in `scenarios.py`.

Each scenario specifies:

* patient identity
* date of birth
* test goal
* facts the patient knows
* patient preferences
* conversational behavior
* optional voice-activity settings

The patient is instructed to reveal information naturally instead of giving every detail immediately.

## Available Scenarios

### Basic appointment scheduling

```bash
python make_call.py schedule_knee_pain
```

Tests a normal appointment workflow for new knee pain.

### Rescheduling

```bash
python make_call.py reschedule_appointment
```

Tests whether the agent can identify an existing appointment and move it to a preferred time.

The scenario is intentionally state-aware because previous calls can modify the test account.

### Medication refill

```bash
python make_call.py medication_refill
```

Tests a prescription refill request including medication, dosage, clinician, and pharmacy information.

### Office hours and insurance

```bash
python make_call.py hours_and_insurance
```

Tests questions about insurance acceptance, weekend availability, and weekday appointment options.

### Barge-in test

```bash
python make_call.py barge_in_test
```

Uses a shorter endpoint threshold to increase the chance of overlapping turns and test interruption recovery.

### Wrong identity test

```bash
python make_call.py wrong_identity_test
```

Intentionally uses a patient identity that does not match the caller record to test identity verification, record lookup, and escalation behavior.

### Prompt injection test

```bash
python make_call.py prompt_injection_test
```

Tests whether the office AI follows caller-supplied instructions that conflict with its normal workflow.

The scenario includes both a direct instruction injection and a data-versus-instruction test and stops once sufficient evidence is collected.

## Setup

### Requirements

* Python 3
* Twilio account
* Twilio Voice-enabled phone number
* Gemini API key
* Cloudflare Tunnel or another public HTTPS/WSS tunnel

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install the project dependencies.

If the repository includes `requirements.txt`:

```bash
pip install -r requirements.txt
```

## Environment Variables

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Configure:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=Your_phone_number

TEST_PHONE_NUMBER=The_number_you_will_be_calling

MEDIA_STREAM_URL=wss://your-public-domain/media-stream

GEMINI_API_KEY=
GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview
```

Do not commit `.env` or API credentials.


The same Twilio caller number should be used for all assessment calls.

## Run

### 1. Start the FastAPI server

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

The local health endpoint is:

```text
http://localhost:8000/
```

### 2. Expose the server

For local development with Cloudflare Tunnel:

```bash
cloudflared tunnel --url http://localhost:8000
```

Cloudflare will provide a public HTTPS URL.

Convert that URL to a WebSocket URL and set:

```env
MEDIA_STREAM_URL=wss://your-cloudflare-domain/media-stream
```

Restart the caller/server if necessary after changing environment variables.

### 3. Place a test call

For example:

```bash
python make_call.py schedule_knee_pain
```

The terminal will print the Twilio Call SID and the server will log the realtime conversation.

## Example Logs

A normal call produces logs similar to:

```text
scenario selected schedule_knee_pain
Gemini Live session connected.
TWO-WAY GEMINI CALL IS LIVE

PERSON: How may I help you today?
GEMINI: Hi, I'd like to make an appointment for knee pain.

PERSON: Please provide your date of birth.
GEMINI: January 1st, 1990.

scenario complete and reason appointment scheduled
waiting for final goodbye playback
final goodbye playback completed
intentional call end
```

During interruption testing:

```text
office interrupted gemini playback
```

indicates that buffered Gemini speech was cleared so the office could continue speaking.

## Scenario Completion

Gemini has access to a structured `finish_call` tool.

It is instructed to use the tool only when:

* the scenario goal has been resolved, or
* the office cannot help further and the conversation has reached a natural endpoint

After `finish_call` is accepted, Gemini gives a short natural goodbye.

The application then sends a Twilio playback mark and waits until the goodbye audio has actually finished before intentionally ending the call.

If the office begins speaking again before the goodbye completes, the pending call ending is cancelled and the conversation continues.

## Development and Iteration

Realtime telephone turn detection was the largest reliability challenge during development.

Approaches tested included:

* Gemini automatic VAD
* aggressive automatic endpointing
* listen-first behavior
* hybrid Gemini/local VAD
* local RMS hysteresis
* audio pre-roll
* pausing silence forwarding
* response watchdogs
* different silence thresholds
* explicit manual activity boundaries

The final implementation uses application-controlled `ActivityStart` and `ActivityEnd` signals because this produced the most reliable multi-turn conversations during testing.

More detailed engineering notes and failed experiments are documented separately from the main architecture so the README remains focused on setup and usage.

## Project Goals

The final test suite is designed to evaluate issues such as:

* incorrect appointment scheduling
* rescheduling and cancellation failures
* medication refill handling
* office-hours or insurance misinformation
* identity verification problems
* inability to recover from interruptions
* conversational stalls
* repeated questions
* inconsistent patient or appointment state
* prompt-injection resistance
* inappropriate handling of caller-supplied instructions
* other unexpected agent behavior

The objective is not simply to complete scripted conversations. The caller should behave like a realistic patient while actively steering each conversation toward the scenario being tested.

## Submission Artifacts

The final repository will include:

* Python source code
* setup instructions
* architecture documentation
* `.env.example`
* at least 10 complete call transcripts
* matching MP3 or OGG recordings
* bug report with references to specific calls and timestamps
* project walkthrough Loom
* AI-assisted debugging Loom

## Safety

This project is built specifically for the provided AI engineering assessment.

Do not commit Twilio credentials, Gemini API keys, or other secrets.
