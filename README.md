# call-automation

# AI Patient Voice Tester

Automated Python voice bot for testing a healthcare AI phone agent.

## Current Status

- [x] Outbound Twilio calling
- [x] FastAPI WebSocket server
- [x] Twilio bidirectional Media Streams
- [x] Incoming phone audio streamed to Python
- [x] Python audio streamed back through Twilio
- [ ] Realtime AI patient agent
- [ ] Scenario engine
- [ ] Natural turn-taking and interruption handling
- [ ] Call recording
- [ ] Transcription
- [ ] Automated QA evaluation
- [ ] 10+ final test calls

## Development Architecture

During local development, Cloudflare Tunnel exposes the local FastAPI
WebSocket server to Twilio.

```text
Pretty Good AI
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
    Python


## Setup

### Requirements

- Python 3.x
- Twilio account with a Voice-enabled number

### Environment Variables

Copy `.env.example` to `.env`:

```env
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=
TEST_PHONE_NUMBER=
MEDIA_STREAM_URL=
```

What the patient need to answer or can call about

They need to know who you are 
Your date of birth 


- General questions
    - Anything about the clinic
- Clinic info 
    - Address 
    - Hours
    - Provider details
        - Info about doctors names and specialty and care they offer
    - Services
        - Types of care they offer 
- Medication refill
    - Medication name
    - Confirm pharmacy 
- Booking 
    - Help book
    - Reschedule
    - Cancel
    - Schedule
- Patient cases
    - Question, concern request, billing or treatment clinic team will review
- Insurance
    - Update 
    - Issues 
