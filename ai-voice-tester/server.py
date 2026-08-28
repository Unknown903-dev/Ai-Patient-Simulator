import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


app = FastAPI()


@app.get("/")
async def health_check():
    return {"status": "ok"}

# this will be our websocket connection it will stay open while call is active
@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):

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

            elif event == "media":
                print("Received audio")

            elif event == "stop":
                print("Media stream stopped")
                break

    # handle cases where Twilio disconnects the WebSocket unexpectedly.
    except WebSocketDisconnect:
        print("WebSocket disconnected")