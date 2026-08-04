from .base import BaseParser
from .form16_parser import Form16ParserMixin
from .ais_parser import AISParserMixin
from .indian_stocks_parser import IndianStocksParserMixin
from .mutual_funds_parser import MutualFundsParserMixin
from .us_assets_parser import USAssetsParserMixin
from .vda_parser import VDAParserMixin

class DocumentParser(
    BaseParser,
    Form16ParserMixin,
    AISParserMixin,
    IndianStocksParserMixin,
    MutualFundsParserMixin,
    USAssetsParserMixin,
    VDAParserMixin
):
    """
    Unified DocumentParser subclassing all domain-specific mixins.
    Provides standard backward compatibility with the legacy parser interface.
    """
    pass
