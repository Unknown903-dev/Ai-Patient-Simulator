import argparse
import os

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect

from scenarios import DEFAULT_SCENARIO, SCENARIOS


load_dotenv()

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
twilio_number = os.environ["TWILIO_PHONE_NUMBER"]
test_number = os.environ["TEST_PHONE_NUMBER"]
media_stream_url = os.environ["MEDIA_STREAM_URL"]

client = Client(account_sid, auth_token)


def make_test_call(scenario_name: str):
    # create the twiml for the outbound call
    response = VoiceResponse()

    # connect the phone call to our websocket server
    connect = Connect()
    stream = connect.stream(url=media_stream_url)

    # tell the websocket server which patient scenario to use
    stream.parameter(name="scenario", value=scenario_name)

    response.append(connect)

    # start the outbound phone call
    call = client.calls.create(
        to=test_number,
        from_=twilio_number,
        twiml=str(response),
    )

    print(str(response))
    print(f"Scenario: {scenario_name}")
    print("Call started successfully")
    print(f"Call SID: {call.sid}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "scenario",
        nargs="?",
        default=DEFAULT_SCENARIO,
        choices=sorted(SCENARIOS),
    )
    args = parser.parse_args()

    make_test_call(args.scenario)