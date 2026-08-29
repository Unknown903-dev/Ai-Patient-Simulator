import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect

from scenarios import DEFAULT_SCENARIO, SCENARIOS


CALL_ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts" / "calls"


def build_recording_callback_url(stream_url: str) -> str:
    # use the same public host for recording updates
    parsed_url = urlparse(stream_url)
    callback_scheme = {
        "wss": "https",
        "ws": "http",
    }.get(parsed_url.scheme.lower())

    # stop when the stream link cannot make a callback link
    if callback_scheme is None or not parsed_url.netloc:
        raise ValueError(
            "MEDIA_STREAM_URL must use ws or wss and include a host"
        )

    return urlunparse(
        (
            callback_scheme,
            parsed_url.netloc,
            "/recording-status",
            "",
            "",
            "",
        )
    )


def save_initial_call_metadata(call_sid: str, scenario_name: str) -> Path:
    # save the call details before the recording is ready
    call_directory = CALL_ARTIFACTS_DIR / call_sid
    call_directory.mkdir(parents=True, exist_ok=True)
    metadata_path = call_directory / "metadata.json"

    metadata = {}
    # keep any call details that were already saved
    if metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)

    metadata["call_sid"] = call_sid
    metadata["scenario"] = scenario_name
    metadata.setdefault(
        "created_at",
        datetime.now(timezone.utc).isoformat(),
    )
    metadata.setdefault("recording_status", "pending")

    temporary_path = metadata_path.with_suffix(".json.part")
    with temporary_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, ensure_ascii=False)
        metadata_file.write("\n")
    temporary_path.replace(metadata_path)

    return metadata_path


load_dotenv()

account_sid = os.environ["TWILIO_ACCOUNT_SID"]
auth_token = os.environ["TWILIO_AUTH_TOKEN"]
twilio_number = os.environ["TWILIO_PHONE_NUMBER"]
test_number = os.environ["TEST_PHONE_NUMBER"]
media_stream_url = os.environ["MEDIA_STREAM_URL"]
recording_callback_url = build_recording_callback_url(media_stream_url)

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
        record=True,
        recording_channels="dual",
        recording_status_callback=recording_callback_url,
        recording_status_callback_event=["completed", "absent"],
        recording_status_callback_method="POST",
    )

    metadata_path = save_initial_call_metadata(call.sid, scenario_name)

    print(str(response))
    print(f"Scenario: {scenario_name}")
    print("Call started successfully")
    print(f"Call SID: {call.sid}")
    print(f"Recording callback: {recording_callback_url}")
    print(f"Call metadata: {metadata_path}")


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
    