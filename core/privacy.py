"""Privacy helpers (Spec §4): IPs must never appear unmasked in logs,
reports or exported JSON. Masking keeps enough structure for diagnosis
(same first two octets ⇒ likely same ISP/network) without exposing the
full address."""

import ipaddress


def mask_ip(ip: str) -> str:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return "<masked>"                     # never leak a raw unknown string
    if addr.version == 4:
        parts = ip.split(".")
        return f"{parts[0]}.{parts[1]}.x.x"
    # IPv6: keep the first 2 groups only.
    groups = ip.split(":")
    return groups[0] + ":" + (groups[1] or "x") + "::x"
