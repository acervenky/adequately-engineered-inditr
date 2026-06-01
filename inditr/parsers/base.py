"""
Abstract base class for all document parsers.
Parsers NEVER raise unhandled exceptions.
"""
from __future__ import annotations
import abc
from inditr.models.documents import ParsedDocument


class BaseParser(abc.ABC):
    """Abstract base for all parsers."""

    @abc.abstractmethod
    def can_parse(self, filepath: str) -> bool:
        """Return True if this parser handles the given file."""

    @abc.abstractmethod
    def parse(self, filepath: str) -> ParsedDocument:
        """
        Parse the document and return a ParsedDocument.
        MUST NOT raise exceptions — catch all errors and add to parse_errors.
        """
