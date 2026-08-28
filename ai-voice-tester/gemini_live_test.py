import asyncio
import os
import sys

import sounddevice as sd
from google import genai


MODEL = "gemini-3.1-flash-live-preview"

# test prompt gemini will recieve
PROMPT = "Hi, I'd like to schedule an appointment."

# Gemini Live audio output is:
# - 24,000 Hz
# - mono
# - 16-bit signed PCM
OUTPUT_SAMPLE_RATE = 24000
OUTPUT_CHANNELS = 1
OUTPUT_DTYPE = "int16"


async def main():
    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        print("ERROR: GEMINI_API_KEY environment variable is not set.")
        print("\nWindows PowerShell:")
        print('\n$env:GEMINI_API_KEY="YOUR_API_KEY"')
        print("macOS/Linux:")
        print('export GEMINI_API_KEY="YOUR_API_KEY"')
        sys.exit(1)

    
    # create a client auth with the api ket and pass it to sdk
    client = genai.Client(api_key=api_key)

    config = {
        # tell gemini generate audio response
        "response_modalities": ["AUDIO"],

        # gives us text showing what Gemini is saying
        "output_audio_transcription": {},
    }

    print(f"Connecting to Gemini Live using {MODEL}...")

    # this will be used to hear the audio through computer 

    #create raw audio output stream using mac default output
    speaker = sd.RawOutputStream(
        samplerate=OUTPUT_SAMPLE_RATE,
        channels=OUTPUT_CHANNELS,
        dtype=OUTPUT_DTYPE,
    )

    try:
        speaker.start()

        print("Computer audio output opened successfully.")

        # open a live session
        async with client.aio.live.connect(
            model=MODEL,
            config=config,
        ) as session:

            print("Gemini Live session connected successfully.")

            #send a prompt to active session
            await session.send_client_content(
                turns={
                    "role": "user",
                    "parts": [{"text": PROMPT}],
                },
                # tell gemini that user is done talking
                turn_complete=True,
            )

            print("Prompt sent. Waiting for Gemini...")

            # get streamed messages from gemini
            async for response in session.receive():
                
                # extract the main server generated conten tfrom the response
                server_content = response.server_content

                if not server_content:
                    continue

                # check wether gemini has produced part of a model response
                if server_content.model_turn:
                    
                    # a model turn can contain muiltiple pieces of content
                    # so go through each one
                    for part in server_content.model_turn.parts:
                        
                        #check if has any inline binary audio data
                        if part.inline_data and part.inline_data.data:
                            
                            #extract raw pcm audio bytes
                            audio_chunk = part.inline_data.data

                            print("Received audio chunk: {len(audio_chunk)} bytes")

                            # this is what makes gemini audible through your computer.
                            speaker.write(audio_chunk)

                # check wether gemini provided a transcription of the generated speech
                if server_content.output_transcription:
                    
                    #get the transcription
                    text = server_content.output_transcription.text

                    # text was provided print it and prevent output buffering from delaying it
                    if text:
                        print(f"Gemini said: {text}",
                            flush=True,
                        )

                # check if gemini is done with there turn
                if server_content.turn_complete:
                    print("Gemini finished speaking.")
                    break

    # handle ctr c and not displaying a large traceback
    except KeyboardInterrupt:
        print("\nStopped by user.")
    # get unexpected errors
    except Exception as e:
        print("\nERROR:")
        print(type(e).__name__, str(e))

    finally:
        try:
            #stop sending audio and release the audio device resource
            speaker.stop()
            speaker.close()
        except Exception:
            pass

        print("Audio output closed.")


if __name__ == "__main__":
    asyncio.run(main())