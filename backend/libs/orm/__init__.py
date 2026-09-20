"""Imports every model so SQLAlchemy can resolve cross-table ForeignKeys.

A mapper only sees tables that are registered in Base.metadata. A handler that
imports just one model (say Processes) would fail at query time with
NoReferencedTableError because Processes declares ForeignKey("banks.id") and
the banks table was never registered. Importing the package pulls all of them
in, so any `from libs.orm.x import Y` is enough.

Order follows FK dependencies for readability; SQLAlchemy resolves them lazily.
"""
from libs.orm.base import Base
from libs.orm.users import Users
from libs.orm.banks import Banks
from libs.orm.bank_rates import BankRates
from libs.orm.bearer_tokens import BearerTokens
from libs.orm.forms import Forms
from libs.orm.processes import Processes
from libs.orm.files import Files
from libs.orm.signatures import Signatures

__all__ = [
    "Base",
    "Users",
    "Banks",
    "BankRates",
    "BearerTokens",
    "Forms",
    "Processes",
    "Files",
    "Signatures",
]
