"""Explicit browser origin and backend Host; forwarded headers are never trusted."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network
import re
from urllib.parse import urlsplit

_PRIVATE = tuple(IPv4Network(value) for value in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


@dataclass(frozen=True)
class OriginPolicy:
    origin: str
    host: str
    secure: bool

    @classmethod
    def validate(cls, origin, backend_host=None):
        try:
            parsed = urlsplit(origin)
            if not isinstance(origin, str) or parsed.path or parsed.query or parsed.fragment or parsed.username:
                raise ValueError()
            if backend_host is None:
                if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                        or not parsed.port or origin != f'http://127.0.0.1:{parsed.port}'):
                    raise ValueError()
                return cls(origin, parsed.netloc, False)
            if (parsed.scheme != 'https' or parsed.port or not parsed.hostname
                    or origin != f'https://{parsed.hostname}'
                    or len(parsed.hostname) > 253
                    or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+', parsed.hostname)):
                raise ValueError()
            address, port = backend_host.split(':')
            if port != '8080' or not any(IPv4Address(address) in network for network in _PRIVATE):
                raise ValueError()
            return cls(origin, backend_host, True)
        except (TypeError, AttributeError, ValueError):
            raise ValueError('Invalid presenter origin or backend Host configuration.') from None
