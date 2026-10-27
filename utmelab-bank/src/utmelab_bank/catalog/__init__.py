"""The WAEC catalog compiler."""

from .model import Subtopic, Syllabus, Topic
from .parse import ParseError, parse
from .pdf import Line, normalise, read_lines
from .profiles import Profile, profile_for

__all__ = [
    "Line",
    "ParseError",
    "Profile",
    "Subtopic",
    "Syllabus",
    "Topic",
    "normalise",
    "parse",
    "profile_for",
    "read_lines",
]
