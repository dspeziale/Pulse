"""Pulse — Proxy nmap esterno (host Windows).

Esegue nmap NATIVO sull'host (Npcap) per conto dell'agent Probe, che gira in un
container Docker Desktop (Windows/WSL2) dietro NAT e non raggiunge la LAN fisica.
Canale protetto da mTLS + token Bearer; l'argv ricevuto e' SEMPRE ri-validato con
la stessa whitelist dell'agent (``pulse_probe.nmap_scan.assert_safe_argv``).
"""

__version__ = "1.0.0"
