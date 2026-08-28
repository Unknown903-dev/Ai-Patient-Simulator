import audioop
import base64
import json
import math
import struct
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


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
                #which active audio stream should I play this audio into
                stream_sid = data["start"]["streamSid"]

                #call SID identifies the entire phone call in Twilio.
                call_sid = data["start"]["callSid"]

                print(f"Stream SID: {stream_sid}")
                print(f"Call SID: {call_sid}")

                #one seconf test tone
                tone_payload = generate_test_tone()

                #send tone in acitve twillo call
                await websocket.send_json(
                    {
                        "event": "media",
                        "streamSid": stream_sid,
                        "media": {"payload": tone_payload},
                    }
                )
                await websocket.send_json(
                    {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": "test-tone-finished"},
                    }
                )

                print("Sent test tone")

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