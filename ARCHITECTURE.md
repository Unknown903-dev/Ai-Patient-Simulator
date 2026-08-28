### Twilio

Twilio was selected as the telephony provider after comparing Twilio,
Plivo, Telnyx, and SignalWire.

The main reason for selecting Twilio was integration risk rather than
the lowest per minute cost. Twilio provides mature Python support,
outbound PSTN calling, bidirectional Media Streams, call recording,
and extensive documentation. For more info visit Discusisons.

### Development Strategy

The first milestone was intentionally limited to verifying that Python
could successfully originate a call through Twilio before introducing
streaming audio or AI components.

# Architecture

Twilio is used as the telephony layer because it provides outbound PSTN calling, bidirectional Media Streams, call recording support, and mature Python tooling. The application uses FastAPI to host a WebSocket endpoint that receives live telephone audio from Twilio and can send audio back into the active call. During local development, Cloudflare Tunnel exposes the local WebSocket server through a secure public `wss://` endpoint, avoiding the need to deploy permanent infrastructure while the voice system is still being developed.

The system is being built incrementally so that each layer can be validated
independently. The first milestone verified outbound PSTN calling. The second
verified both directions of the realtime audio path: phone audio can reach the
Python application, and Python-generated G.711 μ-law audio can be played back
through Twilio. This isolates telephony and networking issues before introducing the realtime AI patient model, making later debugging easier and reducing integration risk.