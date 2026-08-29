import audioop
import base64
import json
import math
import os
import shutil
import struct
import asyncio
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from google import genai
from google.genai import types
from twilio.request_validator import RequestValidator

from scenarios import DEFAULT_SCENARIO, build_system_instruction, get_scenario

load_dotenv()

app = FastAPI()
CALL_ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts" / "calls"
twilio_request_validator = RequestValidator(
    os.environ["TWILIO_AUTH_TOKEN"]
)


def log(message: str) -> None:
    """show the time for each event"""
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    print(f"[{timestamp}] {message}", flush=True)


def get_call_artifact_directory(call_sid: str) -> Path:
    # find the folder for this call and make it when needed
    # stop unsafe folder names from being used
    if not call_sid or not call_sid.isalnum():
        raise ValueError("invalid call sid")

    call_directory = CALL_ARTIFACTS_DIR / call_sid
    call_directory.mkdir(parents=True, exist_ok=True)
    return call_directory


def merge_call_metadata(call_sid: str, updates: dict) -> Path:
    # add new details without losing what is already saved
    call_directory = get_call_artifact_directory(call_sid)
    metadata_path = call_directory / "metadata.json"
    metadata = {}

    # load the old details before adding the new ones
    if metadata_path.exists():
        with metadata_path.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)

    metadata.setdefault("call_sid", call_sid)
    metadata.update(updates)

    temporary_path = metadata_path.with_suffix(".json.part")
    with temporary_path.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, ensure_ascii=False)
        metadata_file.write("\n")
    temporary_path.replace(metadata_path)

    return metadata_path


class CallTranscript:
    def __init__(self, call_sid: str, scenario_name: str):
        # keep transcript details together for one call
        self.call_sid = call_sid
        self.scenario_name = scenario_name
        self.call_directory = get_call_artifact_directory(call_sid)
        self.started_at = time.monotonic()
        self.events = []
        self.buffers = {
            "OFFICE": "",
            "PATIENT": "",
        }
        self.buffer_started_at = {
            "OFFICE": None,
            "PATIENT": None,
        }
        self.office_flush_task = None

    def add_fragment(self, speaker: str, text: str) -> None:
        # join small text parts into one natural sentence
        fragment = " ".join(text.split())

        # skip empty text parts
        if not fragment:
            return

        # remember when this person started talking
        if self.buffer_started_at[speaker] is None:
            self.buffer_started_at[speaker] = (
                time.monotonic() - self.started_at
            )

        current_text = self.buffers[speaker]
        no_space_before = ".,!?;:)]}'’"

        # add a space unless this part starts with punctuation
        if current_text and fragment[0] not in no_space_before:
            current_text += " "

        self.buffers[speaker] = current_text + fragment

        # give late office text more time before saving the turn
        if (
            speaker == "OFFICE"
            and self.office_flush_task is not None
            and not self.office_flush_task.done()
        ):
            self.schedule_office_flush()

    async def delayed_office_flush(self) -> None:
        # wait for late office text before saving the turn
        try:
            await asyncio.sleep(0.75)
            self.flush("OFFICE")
        except asyncio.CancelledError:
            pass
        finally:
            # clear this task only when it is still the newest one
            if self.office_flush_task is asyncio.current_task():
                self.office_flush_task = None

    def schedule_office_flush(self) -> None:
        # restart the wait for the latest office text
        if (
            self.office_flush_task is not None
            and not self.office_flush_task.done()
        ):
            self.office_flush_task.cancel()

        self.office_flush_task = asyncio.create_task(
            self.delayed_office_flush()
        )

    async def cancel_office_flush(self) -> None:
        # stop a delayed office flush before the call ends
        pending_task = self.office_flush_task
        self.office_flush_task = None

        # do nothing when there is no delayed flush
        if pending_task is None:
            return

        # cancel a task that is still waiting
        if not pending_task.done():
            pending_task.cancel()

        try:
            await pending_task
        except asyncio.CancelledError:
            pass

    def flush(self, speaker: str) -> None:
        # save one finished sentence for this person
        text = self.buffers[speaker].strip()

        # do nothing when there is no text to save
        if not text:
            return

        elapsed_seconds = self.buffer_started_at[speaker]
        self.events.append(
            {
                "speaker": speaker,
                "elapsed_seconds": elapsed_seconds,
                "text": text,
            }
        )
        self.buffers[speaker] = ""
        self.buffer_started_at[speaker] = None

    def flush_all(self) -> None:
        # keep any text left when the call ends
        self.flush("OFFICE")
        self.flush("PATIENT")

    def format_timestamp(self, elapsed_seconds: float) -> str:
        # show time from the start of the call
        total_milliseconds = round(elapsed_seconds * 1000)
        minutes, remaining_milliseconds = divmod(
            total_milliseconds,
            60000,
        )
        seconds, milliseconds = divmod(remaining_milliseconds, 1000)
        return f"{minutes:02d}:{seconds:02d}.{milliseconds:03d}"

    def save(self) -> Path:
        # write the whole transcript at the end of the call
        self.flush_all()
        transcript_path = self.call_directory / "transcript.txt"
        temporary_path = transcript_path.with_suffix(".txt.part")
        lines = [
            f"Scenario: {self.scenario_name}",
            f"Call SID: {self.call_sid}",
            "",
        ]

        for event in self.events:
            timestamp = self.format_timestamp(event["elapsed_seconds"])
            lines.append(
                f"[{timestamp}] {event['speaker']}: {event['text']}"
            )

        with temporary_path.open("w", encoding="utf-8") as transcript_file:
            transcript_file.write("\n".join(lines))
            transcript_file.write("\n")
        temporary_path.replace(transcript_path)

        merge_call_metadata(
            self.call_sid,
            {"transcript_file": "transcript.txt"},
        )
        return transcript_path


def optional_integer(value: str):
    # turn number text into a number when possible
    # leave missing values empty
    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return value


def recording_media_url(recording_url: str, channels) -> str:
    # make a safe twilio mp3 link for the saved recording
    parsed_url = urlsplit(recording_url)
    hostname = (parsed_url.hostname or "").lower()
    account_path = f"/Accounts/{os.environ['TWILIO_ACCOUNT_SID']}/"

    # only send the account login to a matching twilio link
    if not (
        parsed_url.scheme == "https"
        and (
            hostname == "api.twilio.com"
            or (
                hostname.startswith("api.")
                and hostname.endswith(".twilio.com")
            )
        )
        and parsed_url.username is None
        and parsed_url.password is None
        and account_path in parsed_url.path
    ):
        raise ValueError("invalid twilio recording url")

    media_path = parsed_url.path
    # add the mp3 ending when twilio leaves it out
    if not media_path.lower().endswith(".mp3"):
        media_path = f"{media_path}.mp3"

    query_values = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
    # ask twilio to keep both sides in separate channels
    if channels == 2:
        query_values["RequestedChannels"] = "2"

    return urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            media_path,
            urlencode(query_values),
            parsed_url.fragment,
        )
    )


def download_recording(recording_url: str, destination: Path) -> None:
    # download the recording with the twilio account login
    credentials = base64.b64encode(
        (
            f"{os.environ['TWILIO_ACCOUNT_SID']}:"
            f"{os.environ['TWILIO_AUTH_TOKEN']}"
        ).encode("utf-8")
    ).decode("ascii")
    download_request = UrlRequest(
        recording_url,
        headers={"Authorization": f"Basic {credentials}"},
    )
    temporary_path = destination.with_suffix(".mp3.part")

    try:
        with urlopen(download_request, timeout=60) as response:
            with temporary_path.open("wb") as recording_file:
                shutil.copyfileobj(response, recording_file)
        temporary_path.replace(destination)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


@app.get("/")
async def health_check():
    return {"status": "ok"}


@app.post("/recording-status")
async def recording_status(request: Request):
    # handle recording updates sent by twilio
    body = await request.body()
    form_values = parse_qs(
        body.decode("utf-8"),
        keep_blank_values=True,
    )
    callback = {
        key: values[-1]
        for key, values in form_values.items()
    }

    signature = request.headers.get("X-Twilio-Signature", "")
    request_url = str(request.url)

    # stop requests that were not signed by twilio
    if not twilio_request_validator.validate(
        request_url,
        callback,
        signature,
    ):
        log("invalid twilio recording callback signature")
        raise HTTPException(status_code=403, detail="forbidden")

    call_sid = callback.get("CallSid", "")
    recording_sid = callback.get("RecordingSid", "")
    status = callback.get("RecordingStatus", "").lower()

    try:
        call_directory = get_call_artifact_directory(call_sid)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    log(f"recording callback received for {call_sid}")

    # save the result when twilio could not make a recording
    if status == "absent":
        merge_call_metadata(
            call_sid,
            {
                "recording_sid": recording_sid,
                "recording_status": "absent",
                "recording_error_code": callback.get("ErrorCode", ""),
            },
        )
        log(f"recording absent for {call_sid}")
        return {"status": "ok"}

    # skip updates that do not need more work
    if status != "completed":
        return {"status": "ignored"}

    recording_url = callback.get("RecordingUrl", "")
    # stop when twilio does not send a download link
    if not recording_url:
        raise HTTPException(status_code=400, detail="missing recording url")

    recording_channels = optional_integer(
        callback.get("RecordingChannels", "")
    )
    recording_metadata = {
        "recording_sid": recording_sid,
        "recording_status": "completed",
        "recording_duration_seconds": optional_integer(
            callback.get("RecordingDuration", "")
        ),
        "recording_channels": recording_channels,
        "recording_start_time": callback.get("RecordingStartTime", ""),
        "recording_source": callback.get("RecordingSource", ""),
        "recording_track": callback.get("RecordingTrack", ""),
    }
    merge_call_metadata(call_sid, recording_metadata)

    destination = call_directory / "recording.mp3"
    try:
        media_url = recording_media_url(recording_url, recording_channels)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        await asyncio.to_thread(
            download_recording,
            media_url,
            destination,
        )
    except Exception as error:
        log(f"recording download failed for {call_sid}")
        raise HTTPException(
            status_code=502,
            detail="recording download failed",
        ) from error

    merge_call_metadata(
        call_sid,
        {"recording_file": "recording.mp3"},
    )
    log(f"recording completed {recording_sid}")
    log(f"recording saved to {destination}")
    return {"status": "ok"}



def generate_test_tone(
    frequency: int = 440,
    duration: float = 1.0,
    sample_rate: int = 8000,
) -> str:
    """
    generate a simple tone and return it as Base64 encoded
    G.711 μ-law audio that twilio can play.
    """

    pcm_audio = bytearray()

    total_samples = int(sample_rate * duration)

    for sample_index in range(total_samples):
        # generate a sine wave between -1 and 1.
        value = math.sin(
            2 * math.pi * frequency * sample_index / sample_rate
        )

        # convert it to signed 16-bit PCM.
        sample = int(value * 10000)

        pcm_audio.extend(struct.pack("<h", sample))

    # convert 16-bit PCM into G.711 μ-law.
    mulaw_audio = audioop.lin2ulaw(bytes(pcm_audio), 2)

    # twilio expects the μ-law bytes to be base64 encoded.
    return base64.b64encode(mulaw_audio).decode("utf-8")



async def run_gemini_call(
    websocket: WebSocket,
    stream_sid: str,
    call_sid: str,
    scenario_name: str,
    scenario: dict,
):
    # keep one transcript from the start to the end of the call
    transcript = CallTranscript(call_sid, scenario_name)

    try:
        return await run_gemini_session(
            websocket,
            stream_sid,
            scenario,
            transcript,
        )
    finally:
        try:
            await transcript.cancel_office_flush()
            transcript_path = transcript.save()
            log(f"transcript saved to {transcript_path}")
        except Exception as error:
            log(f"transcript save failed for {call_sid} {error}")


async def run_gemini_session(
    websocket: WebSocket,
    stream_sid: str,
    scenario: dict,
    transcript: CallTranscript,
):
    # run the existing live audio session

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.environ["GEMINI_LIVE_MODEL"]

    config = {
        "response_modalities": ["AUDIO"],

        "system_instruction": build_system_instruction(scenario),

        "tools": [
            {
                "function_declarations": [
                    {
                        "name": "finish_call",
                        "description": (
                            "report that the patient goal is fully resolved "
                            "or that the office cannot help any further"
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reason": {
                                    "type": "string",
                                    "description": (
                                        "a short result such as appointment "
                                        "scheduled or question answered"
                                    ),
                                }
                            },
                            "required": ["reason"],
                        },
                    }
                ]
            }
        ],

        # show what the person says
        "input_audio_transcription": {},

        # show what gemini says
        "output_audio_transcription": {},

        # turn off gemini speech checks so we can mark each turn ourselves
        "realtime_input_config": {
            "automatic_activity_detection": {
                "disabled": True,
            }
        },
    }

    log(f"Connecting Gemini Live using {model}...")

    async with client.aio.live.connect(
        model=model,
        config=config,
    ) as session:

        log("Gemini Live session connected.")

        websocket_send_lock = asyncio.Lock()
        gemini_playback_pending = False
        pending_playback_mark = None
        finalizing_call = False
        final_goodbye_audio_sent = False
        final_goodbye_mark_pending = False
        final_goodbye_mark = "final-goodbye-finished"
        drop_current_gemini_audio = False
        gemini_generation_active = False

        async def send_to_twilio(message: dict):
            # keep websocket writes in order across both audio tasks
            async with websocket_send_lock:
                await websocket.send_json(message)

        # handle messages coming from gemini
        async def handle_gemini_response(
            response,
            output_state,
        ):

            nonlocal gemini_playback_pending
            nonlocal final_goodbye_audio_sent
            nonlocal gemini_generation_active

            server_content = response.server_content

            if not server_content:
                return output_state

            # print what the person says
            if server_content.input_transcription:

                text = (
                    server_content
                    .input_transcription
                    .text
                )

                if text:
                    log(f"PERSON: {text}")
                    transcript.add_fragment("OFFICE", text)

            # print what gemini says
            if server_content.output_transcription:

                text = (
                    server_content
                    .output_transcription
                    .text
                )

                if text:
                    log(f"GEMINI: {text}")
                    transcript.add_fragment("PATIENT", text)

            # get audio made by gemini
            if server_content.model_turn:

                for part in server_content.model_turn.parts:

                    if not (
                        part.inline_data
                        and part.inline_data.data
                    ):
                        continue

                    gemini_generation_active = True

                    if drop_current_gemini_audio:
                        continue

                    pcm_24k = part.inline_data.data

                    # change gemini audio from 24 khz to 8 khz
                    pcm_8k, output_state = audioop.ratecv(
                        pcm_24k,
                        2,
                        1,
                        24000,
                        8000,
                        output_state,
                    )

                    # change pcm audio into mulaw audio
                    mulaw_8k = audioop.lin2ulaw(
                        pcm_8k,
                        2,
                    )

                    # turn the audio into base64 for twilio
                    payload = base64.b64encode(
                        mulaw_8k
                    ).decode("utf-8")

                    # send gemini audio into the phone call
                    await send_to_twilio(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": payload},
                        }
                    )
                    gemini_playback_pending = True

                    if finalizing_call:
                        final_goodbye_audio_sent = True
            return output_state

        async def handle_tool_call(response):
            nonlocal finalizing_call
            nonlocal final_goodbye_audio_sent
            nonlocal final_goodbye_mark_pending

            if not response.tool_call:
                return

            function_responses = []

            for function_call in response.tool_call.function_calls:
                if function_call.name == "finish_call":
                    reason = str(
                        (function_call.args or {}).get(
                            "reason",
                            "scenario resolved",
                        )
                    )
                    finalizing_call = True
                    final_goodbye_audio_sent = False
                    final_goodbye_mark_pending = False
                    log(f"scenario complete and reason {reason}")
                    result = {
                        "status": "accepted",
                        "instruction": (
                            "give one short natural goodbye now"
                        ),
                    }
                else:
                    result = {"error": "unknown function"}

                function_responses.append(
                    types.FunctionResponse(
                        id=function_call.id,
                        name=function_call.name,
                        response=result,
                    )
                )

            await session.send_tool_response(
                function_responses=function_responses
            )

        # send phone audio into gemini
        async def twilio_to_gemini():

            nonlocal gemini_playback_pending
            nonlocal pending_playback_mark
            nonlocal finalizing_call
            nonlocal final_goodbye_audio_sent
            nonlocal final_goodbye_mark_pending
            nonlocal drop_current_gemini_audio
            nonlocal gemini_generation_active

            input_resample_state = None
            pcm_buffer = bytearray()

            # remember if the office is speaking and how long it is quiet
            activity_active = False
            silence_ms = 0.0

            # phone lines have noise so louder audio counts as speech
            speech_rms_threshold = 500

            # end the turn after this much quiet audio
            end_of_speech_silence_ms = scenario.get(
                "end_of_speech_silence_ms",
                600.0,
            )

            # hold about 100 ms of audio
            gemini_chunk_size = 3200

            async def send_buffered_audio(force: bool = False):
                # send full chunks or send everything when the turn ends
                while len(pcm_buffer) >= gemini_chunk_size or (
                    force and pcm_buffer
                ):
                    chunk_size = min(len(pcm_buffer), gemini_chunk_size)
                    audio_chunk = bytes(pcm_buffer[:chunk_size])
                    del pcm_buffer[:chunk_size]

                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_chunk,
                            mime_type="audio/pcm;rate=16000",
                        )
                    )

            while True:

                message = await websocket.receive_text()
                data = json.loads(message)
                event = data.get("event")

                # get audio from the phone call
                if event == "media":

                    payload = (data["media"]["payload"])

                    # change base64 into raw mulaw audio
                    mulaw_8k = base64.b64decode(payload)

                    # change mulaw audio into pcm audio
                    pcm_8k = audioop.ulaw2lin(
                        mulaw_8k,
                        2,
                    )

                    frame_duration_ms = (
                        len(pcm_8k) / 2 / 8000 * 1000
                    )
                    frame_rms = audioop.rms(pcm_8k, 2)

                    # tell gemini when the office starts speaking
                    if frame_rms >= speech_rms_threshold:
                        silence_ms = 0.0

                        if not activity_active:
                            await session.send_realtime_input(
                                activity_start=types.ActivityStart()
                            )
                            activity_active = True
                            #log(f"VAD speech started (RMS={frame_rms})")

                            if finalizing_call or final_goodbye_mark_pending:
                                finalizing_call = False
                                final_goodbye_audio_sent = False
                                final_goodbye_mark_pending = False
                                if gemini_generation_active:
                                    drop_current_gemini_audio = True
                                log(
                                    "call ending cancelled because office "
                                    "kept speaking"
                                )

                            if gemini_playback_pending:
                                await send_to_twilio(
                                    {
                                        "event": "clear",
                                        "streamSid": stream_sid,
                                    }
                                )
                                gemini_playback_pending = False
                                pending_playback_mark = None
                                if gemini_generation_active:
                                    drop_current_gemini_audio = True
                                log("office interrupted gemini playback")

                    elif activity_active:
                        silence_ms += frame_duration_ms

                    # change phone audio from 8 khz to 16 khz

                    (pcm_16k, input_resample_state) = audioop.ratecv(
                        pcm_8k,
                        2,
                        1,
                        8000,
                        16000,
                        input_resample_state,
                    )

                    pcm_buffer.extend(pcm_16k)

                    # send audio to gemini when enough is ready
                    await send_buffered_audio()

                    if (
                        activity_active
                        and silence_ms >= end_of_speech_silence_ms
                    ):
                        # send all speech before telling gemini the turn is done
                        await send_buffered_audio(force=True)
                        await session.send_realtime_input(
                            activity_end=types.ActivityEnd()
                        )
                        transcript.schedule_office_flush()
                        activity_active = False
                        silence_ms = 0.0
                        """log(
                            f"VAD speech ended after "
                            f"{end_of_speech_silence_ms:.0f} ms silence"
                        )"""

                # get a message when twilio finishes playing audio
                elif event == "mark":
                    mark_name = data["mark"]["name"]

                    log(f"Audio playback completed: {mark_name}")

                    if mark_name == pending_playback_mark:
                        gemini_playback_pending = False
                        pending_playback_mark = None

                    if (
                        mark_name == final_goodbye_mark
                        and final_goodbye_mark_pending
                        and finalizing_call
                    ):
                        final_goodbye_mark_pending = False
                        log("final goodbye playback completed")
                        log("intentional call end")
                        await transcript.cancel_office_flush()
                        transcript.flush("OFFICE")
                        return "intentional_call_end"

                # stop when the phone call ends
                elif event == "stop":

                    log("twilio stop")

                    # send any audio still left in the buffer
                    await send_buffered_audio(force=True)

                    if activity_active:
                        await session.send_realtime_input(
                            activity_end=types.ActivityEnd()
                        )

                    await transcript.cancel_office_flush()
                    transcript.flush("OFFICE")
                    return "twilio_stop"

        # send gemini audio back into the phone call
        async def gemini_to_twilio():

            nonlocal pending_playback_mark
            nonlocal final_goodbye_mark_pending
            nonlocal drop_current_gemini_audio
            nonlocal gemini_generation_active

            output_resample_state = None
            turn_number = 1

            while True:
                # listen for the next message from gemini
                received_response = False

                async for response in session.receive():

                    received_response = True

                    await handle_tool_call(response)

                    output_resample_state = (
                        await handle_gemini_response(
                            response,
                            output_resample_state,
                        )
                    )

                if not received_response:
                    raise RuntimeError("gemini receive stream ended")

                # gemini finished one turn

                log(f"Gemini turn {turn_number} complete.")
                transcript.flush("PATIENT")

                # allow audio from the next gemini turn after an interruption
                drop_current_gemini_audio = False
                gemini_generation_active = False

                if gemini_playback_pending:
                    if finalizing_call and final_goodbye_audio_sent:
                        mark_name = final_goodbye_mark
                        final_goodbye_mark_pending = True
                        log("waiting for final goodbye playback")
                    else:
                        mark_name = f"gemini-turn-{turn_number}"

                    pending_playback_mark = mark_name

                    # ask twilio when the queued audio is done playing
                    await send_to_twilio(
                        {
                            "event": "mark",
                            "streamSid": stream_sid,
                            "mark": {"name": mark_name},
                        }
                    )

                turn_number += 1

                # reset the audio change state for the next turn
                output_resample_state = None

        # run phone audio and gemini audio at the same time
        phone_task = asyncio.create_task(twilio_to_gemini())

        gemini_task = asyncio.create_task(gemini_to_twilio())

        log("TWO-WAY GEMINI CALL IS LIVE")

        # wait for twilio to stop or for an unrecoverable gemini error
        done, pending = await asyncio.wait(
            [phone_task, gemini_task,],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # stop the other direction after the call has reached an end state
        for task in pending:
            task.cancel()

        # wait for stopped tasks to finish
        for task in pending:
            try:
                await task

            except asyncio.CancelledError:
                pass

        # show any error that happened
        call_end_reason = None

        for task in done:
            if task.cancelled():
                continue

            exception = task.exception()

            if exception:
                raise exception

            if task is phone_task:
                call_end_reason = task.result()

    log("Gemini phone session closed.")
    return call_end_reason

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """this will be our websocket connection it will stay open while call is active"""

    #accept incoming websocket connections
    await websocket.accept()

    log("WebSocket connected")

    try:
        while True:
            # recieve next websocket message as text
            message = await websocket.receive_text()
            # convert to python dictionary
            data = json.loads(message)

            #every media stream message has an event field
            event = data.get("event")

            if event == "connected":
                log("Twilio media stream connected")
            
            # sent when audio stream start
            # This contains useful identifiers for the stream and phone call
            elif event == "start":
                #which active audio stream should i play this audio into
                stream_sid = data["start"]["streamSid"]

                #call SID identifies the entire phone call in twilio
                call_sid = data["start"]["callSid"]

                custom_parameters = data["start"].get(
                    "customParameters",
                    {},
                )
                scenario_name = custom_parameters.get(
                    "scenario",
                    DEFAULT_SCENARIO,
                )
                scenario = get_scenario(scenario_name)

                #log(f"Stream SID: {stream_sid}")
                #log(f"Call SID: {call_sid}")
                log(f"scenario selected {scenario_name}")
                
                #use one gemini session for the whole call
                call_end_reason = await run_gemini_call(
                    websocket,
                    stream_sid,
                    call_sid,
                    scenario_name,
                    scenario,
                )

                if call_end_reason == "intentional_call_end":
                    await websocket.close(code=1000)

                break

            elif event == "media":
                log("Received audio")
            
            elif event == "mark":
                mark_name = data["mark"]["name"]
                log(f"Audio playback completed: {mark_name}")

            elif event == "stop":
                log("Media stream stopped")
                break

    # handle cases where Twilio disconnects the WebSocket unexpectedly.
    except WebSocketDisconnect:
        log("websocket disconnect")
