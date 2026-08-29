import audioop
import base64
import json
import math
import os
import struct

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from google import genai

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


async def send_gemini_opening(websocket: WebSocket, stream_sid: str):
    """
    Ask Gemini Live to generate one spoken sentence,
    convert the 24 kHz PCM response into Twilio's
    8 kHz G.711 mu-law format, and send it into the call
    """

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    model = os.environ["GEMINI_LIVE_MODEL"]

    # ask gemini for an audio response and transcription
    config = {
        "response_modalities": ["AUDIO"],
        "output_audio_transcription": {},
    }

    # keep resampling state between streamed audio chunks
    resample_state = None

    print(f"Connecting to Gemini Live using {model}...")

    # open the gemini live session
    async with client.aio.live.connect(
        model=model,
        config=config,
    ) as session:

        print("Gemini Live connected")

        # ask gemini to speak our test opening line
        await session.send_client_content(
            turns={
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "You are a patient calling a doctor's office. "
                            "Say exactly: Hi, I'd like to schedule an appointment."
                        )
                    }
                ],
            },
            turn_complete=True,
        )

        print("Asked Gemini to generate opening line")

        # receive gemini streamed response
        async for response in session.receive():

            # Print the transcription so we can see what Gemini said
            if (
                response.server_content
                and response.server_content.output_transcription
            ):
                transcript = (
                    response.server_content
                    .output_transcription
                    .text
                )

                if transcript:
                    print(f"Gemini said: {transcript}")

            # response.data contains Gemini's raw 24 kHz PCM audio
            if response.data:

                # resample gemini audio from 24 kHz PCM to 8 kHz PCM
                pcm_8k, resample_state = audioop.ratecv(
                    response.data,
                    2,      # 16-bit samples = 2 bytes
                    1,      # mono
                    24000,  # gemini output sample rate
                    8000,   # twilio sample rate
                    resample_state,
                )

                # convert linear PCM into G.711 mu-law
                mulaw_audio = audioop.lin2ulaw(pcm_8k, 2)

                # twilio expects the mu-law bytes as Base64 text
                payload = base64.b64encode(mulaw_audio).decode("utf-8")

                # send this Gemini audio chunk into the live phone call
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": payload},
                    }
                )

    print("Finished sending Gemini opening line")

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

                # generate gemini speech and send it to live Twilio call
                await send_gemini_opening(websocket, stream_sid)

                # ask twilio to notify us when the Gemini audio finishes playing
                await websocket.send_json(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": "gemini-opening-finished"},
                    }
                )

                print("Sent Gemini opening audio")

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