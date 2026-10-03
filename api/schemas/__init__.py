"""The shapes that cross the wire.

These lived in main.py, which meant the file that assembles the application also
defined its public contract. They are separate because they change for different
reasons: a field is added here when the frontend needs something, and main.py
changes when the service is wired differently.
"""

from .ask import AskRequest, AskResponse, Citation, Turn

__all__ = ["AskRequest", "AskResponse", "Citation", "Turn"]
