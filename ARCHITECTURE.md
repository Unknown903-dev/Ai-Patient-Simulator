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