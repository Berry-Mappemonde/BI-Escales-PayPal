from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class PurposeCode(str, Enum):
    """The purpose code. Required only for India. For more information, see the Reserve Bank Of India web site. Value
    is:<ul><li><code>P0104</code>. Cross border delivery of goods and services.</li><li><code>P0301</code>. Business
    related travel purchase.</li><li><code>P0801</code>. Hardware consulting.</li><li><code>P0802</code>. Software
    consulting.</li><li><code>P0803</code>. Data processing consulting.</li><li><code>P0805</code>. Freelance
    journalism.</li><li><code>P0806</code>. Other information services.</li><li><code>P0902</code>. Licensing
    revenues.</li><li><code>P1004</code>. Legal.</li><li><code>P1005</code>. Accounting and
    tax.</li><li><code>P1006</code>. Business and management consultancy.</li><li><code>P1007</code>. Advertising and
    market research.</li><li><code>P1008</code>. Research and development.</li><li><code>P1009</code>. Architectural
    services.</li></ul>"""

    P0104 = "P0104"
    P0301 = "P0301"
    P0801 = "P0801"
    P0802 = "P0802"
    P0803 = "P0803"
    P0805 = "P0805"
    P0806 = "P0806"
    P0902 = "P0902"
    P1004 = "P1004"
    P1005 = "P1005"
    P1006 = "P1006"
    P1007 = "P1007"
    P1008 = "P1008"
    P1009 = "P1009"

    __str__ = str.__str__


PurposeCodeOrStr: TypeAlias = Annotated[PurposeCode | str, open_enum_validator(PurposeCode)]
