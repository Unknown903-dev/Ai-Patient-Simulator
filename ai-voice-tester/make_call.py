import os

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect


load_dotenv()

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
twilio_number = os.environ["TWILIO_PHONE_NUMBER"]
test_number = os.environ["TEST_PHONE_NUMBER"]
media_stream_url = os.environ["MEDIA_STREAM_URL"]

client = Client(account_sid, auth_token)


def make_test_call():
    # Create TwiML instructions for what Twilio should do
    # after the remote phone answers
    response = VoiceResponse()

    # <Connect><Stream> creates a bidirectional Media Stream
    # between the phone call and our WebSocket server.
    connect = Connect()
    connect.stream(url=media_stream_url)

    response.append(connect)

    # Start the outbound phone call.
    call = client.calls.create(
        to=test_number,
        from_=twilio_number,
        twiml=str(response),
    )

    print(str(response))

    print("Call started successfully.")
    print(f"Call SID: {call.sid}")

if __name__ == "__main__":
    make_test_call()