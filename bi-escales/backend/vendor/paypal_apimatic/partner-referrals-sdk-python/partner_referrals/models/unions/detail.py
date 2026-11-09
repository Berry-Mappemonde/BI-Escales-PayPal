from __future__ import annotations

from typing import TypeAlias

from ..invalid_array_length import InvalidArrayLength, InvalidArrayLengthDict
from ..invalid_parameter_syntax import InvalidParameterSyntax, InvalidParameterSyntaxDict
from ..invalid_parameter_value import InvalidParameterValue, InvalidParameterValueDict
from ..invalid_string_length import InvalidStringLength, InvalidStringLengthDict

Detail: TypeAlias = InvalidStringLength | InvalidParameterSyntax | InvalidParameterValue | InvalidArrayLength

DetailDict: TypeAlias = (
    InvalidStringLengthDict | InvalidParameterSyntaxDict | InvalidParameterValueDict | InvalidArrayLengthDict
)
