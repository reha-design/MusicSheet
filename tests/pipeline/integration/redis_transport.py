"""Test-only scan cadence; use Kombu's real ACK and Redis restore algorithm."""
from kombu.transport.redis import Channel, QoS, Transport


class VerificationRedisQoS(QoS):
    def restore_visible(self, start=0, num=10, interval=1):
        # Kombu's event-loop timer runs every 10s. Its default interval=10
        # suppresses nine scans, exceeding our bounded live observation.
        return super().restore_visible(start=start, num=num, interval=interval)


class VerificationRedisChannel(Channel):
    QoS = VerificationRedisQoS


class VerificationRedisTransport(Transport):
    Channel = VerificationRedisChannel
