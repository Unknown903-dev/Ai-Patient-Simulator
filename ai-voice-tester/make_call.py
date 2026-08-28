import os

from dotenv import load_dotenv
from twilio.rest import Client


load_dotenv()

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
twilio_number = os.environ["TWILIO_PHONE_NUMBER"]
test_number = os.environ["TEST_PHONE_NUMBER"]

client = Client(account_sid, auth_token)


def make_test_call():
    call = client.calls.create(
        to=test_number,
        from_=twilio_number,
        twiml="""
        <Response>
            <Say>Hello. This is an automated test call.</Say>
        </Response>
        """,
    )

    print("Call started successfully.")
    print(f"Call SID: {call.sid}")


if __name__ == "__main__":
    make_test_call()