from enum import Enum
from typing import Annotated, TypeAlias

from ...core import open_enum_validator


class ProductName(str, Enum):
    """The PayPal product for which the customer is onboarded."""

    ALIPAY = "ALIPAY"
    BANCONTACT = "BANCONTACT"
    BLIK = "BLIK"
    EPS = "EPS"
    PPCP = "PPCP"
    EXPRESS_CHECKOUT = "EXPRESS_CHECKOUT"
    PAYMENT_METHODS = "PAYMENT_METHODS"
    ADVANCED_VAULTING = "ADVANCED_VAULTING"
    IDEAL = "IDEAL"
    MB_WAY = "MB_WAY"
    MULTIBANCO = "MULTIBANCO"
    PAYPAL_COMMERCE_PLATFORM_BUSINESS = "PAYPAL_COMMERCE_PLATFORM_BUSINESS"
    PPPLUS = "PPPLUS"
    PRZELEWY24 = "PRZELEWY24"
    SATISPAY = "SATISPAY"
    TRUSTLY = "TRUSTLY"
    WECHAT_PAY = "WECHAT_PAY"
    WEBSITE_PAYMENT_PRO = "WEBSITE_PAYMENT_PRO"
    ZETTLE = "ZETTLE"
    HYPERWALLET_PAYOUTS = "HYPERWALLET_PAYOUTS"

    __str__ = str.__str__


ProductNameOrStr: TypeAlias = Annotated[ProductName | str, open_enum_validator(ProductName)]
