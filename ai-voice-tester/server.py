import audioop
import base64
import json
import math
import os
import struct
import asyncio

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

load_dotenv()

app = FastAPI()


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

        # show what the person says
        "input_audio_transcription": {},

        # show what gemini says
        "output_audio_transcription": {},
    }

    print(f"Connecting Gemini Live using {model}...")

    async with client.aio.live.connect(
        model=model,
        config=config,
    ) as session:

        print("Gemini Live session connected.")

        # send the first message to gemini
        await session.send_client_content(
            turns={
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "You are a patient calling a doctor's office. "
                            "Keep your responses short and natural because "
                            "this is a real-time phone conversation. "
                            "Begin by saying: "
                            "Hi, I'd like to schedule an appointment."
                        )
                    }
                ],
            },
            turn_complete=True,
        )

        print("Opening instruction sent.")

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
                    print(f"PERSON: {text}",
                        flush=True,
                    )

            # print what gemini says
            if server_content.output_transcription:

                text = (
                    server_content
                    .output_transcription
                    .text
                )

                if text:
                    print(f"GEMINI: {text}",
                        flush=True,
                    )

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

        # wait for gemini to finish the first message
        output_state = None

        async for response in session.receive():
            output_state = await handle_gemini_response(
                response,
                output_state,
            )

        print("Gemini opening sent to phone.")

        # ask twilio to tell us when the first message is done playing
        await websocket.send_json(
            {
                "event": "mark",
                "streamSid": stream_sid,
                "mark": {"name": "gemini-opening-finished"},
            }
        )

        # send phone audio into gemini
        async def twilio_to_gemini():

            input_resample_state = None
            pcm_buffer = bytearray()

            # hold about 100 ms of audio
            gemini_chunk_size = 3200

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
                    while (len(pcm_buffer) >= gemini_chunk_size):

                        audio_chunk = bytes(
                            pcm_buffer[:gemini_chunk_size]
                        )

                        del pcm_buffer[:gemini_chunk_size]

                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=audio_chunk,
                                mime_type=(
                                    "audio/pcm;"
                                    "rate=16000"
                                ),
                            )
                        )

                # get a message when twilio finishes playing audio
                elif event == "mark":
                    mark_name = data["mark"]["name"]

                    print(f"Audio playback completed: {mark_name}")

                # stop when the phone call ends
                elif event == "stop":

                    print("Twilio media stream stopped.")

                    # send any audio still left in the buffer
                    if pcm_buffer:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=bytes(pcm_buffer),
                                mime_type=(
                                    "audio/pcm;"
                                    "rate=16000"
                                ),
                            )
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

                print(f"Gemini turn {turn_number} complete.")

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

        print("\n====================================")
        print("TWO-WAY GEMINI CALL IS LIVE")
        print("====================================\n")

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

    print("Gemini phone session closed.")

@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """this will be our websocket connection it will stay open while call is active"""

    #accept incoming websocket connections
    await websocket.accept()

    print("WebSocket connected")

    try:
        while True:
            # recieve next websocket message as text
            message = await websocket.receive_text()
            # convert to python dictionary
            data = json.loads(message)

            #every media stream message has an event field
            event = data.get("event")

            if event == "connected":
                print("Twilio media stream connected")
            
            # sent when audio stream start
            # This contains useful identifiers for the stream and phone call
            elif event == "start":
                #which active audio stream should i play this audio into
                stream_sid = data["start"]["streamSid"]

                #call SID identifies the entire phone call in twilio
                call_sid = data["start"]["callSid"]

                print(f"Stream SID: {stream_sid}")
                print(f"Call SID: {call_sid}")
                
                #use one gemini session for the whole call
                await run_gemini_call(websocket, stream_sid)

                break

            elif event == "media":
                print("Received audio")
            
            elif event == "mark":
                mark_name = data["mark"]["name"]
                print(f"Audio playback completed: {mark_name}")

            elif event == "stop":
                print("Media stream stopped")
                break

    # handle cases where Twilio disconnects the WebSocket unexpectedly.
    except WebSocketDisconnect:
        print("WebSocket disconnected")