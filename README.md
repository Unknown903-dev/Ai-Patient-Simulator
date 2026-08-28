# call-automation

# AI Patient Voice Tester

Automated Python voice bot for testing a healthcare AI phone agent.

## Current Status

- [x] Outbound Twilio call working
- [ ] Bidirectional audio streaming
- [ ] Realtime patient agent
- [ ] Call recording
- [ ] Transcription
- [ ] Automated evaluation
- [ ] 10+ test scenarios

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
