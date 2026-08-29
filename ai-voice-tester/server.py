import audioop
import base64
import json
import math
import os
import struct
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI()


def log(message: str) -> None:
    """show the time for each event"""
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    print(f"[{timestamp}] {message}", flush=True)


@app.get("/")
async def health_check():
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



async def run_gemini_call(websocket: WebSocket, stream_sid: str):

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.environ["GEMINI_LIVE_MODEL"]

    config = {
        "response_modalities": ["AUDIO"],

        "system_instruction": (
            "You are Alex Smith, a patient calling a doctor's office to "
            "schedule an appointment about knee pain. Your date of birth is "
            "January 1, 1990. Keep your responses short and natural because "
            "this is a real-time phone conversation. Wait for the office to "
            "finish its greeting or ask you a question before speaking. Do "
            "not respond to recording disclosures or automated language-menu "
            "instructions."
        ),

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

        # handle messages coming from gemini
        async def handle_gemini_response(
            response,
            output_state,
        ):

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

            # print what gemini says
            if server_content.output_transcription:

                text = (
                    server_content
                    .output_transcription
                    .text
                )

                if text:
                    log(f"GEMINI: {text}")

            # get audio made by gemini
            if server_content.model_turn:

                for part in server_content.model_turn.parts:

                    if not (
                        part.inline_data
                        and part.inline_data.data
                    ):
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
                    await websocket.send_json(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": payload},
                        }
                    )
            return output_state

        # send phone audio into gemini
        async def twilio_to_gemini():

            input_resample_state = None
            pcm_buffer = bytearray()

            # remember if the office is speaking and how long it is quiet
            activity_active = False
            silence_ms = 0.0

            # phone lines have noise so louder audio counts as speech
            speech_rms_threshold = 500

            # end the turn after this much quiet audio
            end_of_speech_silence_ms = 600.0

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
                            log(f"VAD speech started (RMS={frame_rms})")

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
                        activity_active = False
                        silence_ms = 0.0
                        log("VAD speech ended after 600 ms silence")

                # get a message when twilio finishes playing audio
                elif event == "mark":
                    mark_name = data["mark"]["name"]

                    log(f"Audio playback completed: {mark_name}")

                # stop when the phone call ends
                elif event == "stop":

                    log("Twilio media stream stopped.")

                    # send any audio still left in the buffer
                    await send_buffered_audio(force=True)

                    if activity_active:
                        await session.send_realtime_input(
                            activity_end=types.ActivityEnd()
                        )

                    # tell gemini the phone audio has ended
                    await session.send_realtime_input(
                        audio_stream_end=True
                    )

                    return

        # send gemini audio back into the phone call
        async def gemini_to_twilio():

            output_resample_state = None
            turn_number = 1

            while True:
                # listen for the next message from gemini
                async for response in session.receive():

                    output_resample_state = (
                        await handle_gemini_response(
                            response,
                            output_resample_state,
                        )
                    )

                # gemini finished one turn

                log(f"Gemini turn {turn_number} complete.")

                # ask twilio to tell us when the audio is done playing
                await websocket.send_json(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": (f"gemini-turn-{turn_number}")},
                    }
                )

                turn_number += 1

                # reset the audio change state for the next turn
                output_resample_state = None

        # run phone audio and gemini audio at the same time
        phone_task = asyncio.create_task(twilio_to_gemini())

        gemini_task = asyncio.create_task(gemini_to_twilio())

        log("TWO-WAY GEMINI CALL IS LIVE")

        # wait until one side of the call stops
        done, pending = await asyncio.wait(
            [phone_task, gemini_task,],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # stop any task that is still running
        for task in pending:
            task.cancel()

        # wait for stopped tasks to finish
        for task in pending:
            try:
                await task

            except asyncio.CancelledError:
                pass

        # show any error that happened
        for task in done:
            if task.cancelled():
                continue

            exception = task.exception()

            if exception:
                raise exception

    log("Gemini phone session closed.")

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

                log(f"Stream SID: {stream_sid}")
                log(f"Call SID: {call_sid}")
                
                #use one gemini session for the whole call
                await run_gemini_call(websocket, stream_sid)

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
        log("WebSocket disconnected")
