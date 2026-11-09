from __future__ import annotations

from functools import cached_property
from types import TracebackType

from typing_extensions import Self

from .apis.payouts import AsyncPayouts
from .apis.payouts_item import AsyncPayoutsItem
from .auth import AsyncAuthSchemes, Oauth2Scope
from .base_client import DEFAULT_TIMEOUT, BasePayoutsClient
from .core import (
    OPERATING_SYSTEM,
    PYTHON_RUNTIME,
    AsyncClientCredentialsTokenSource,
    AsyncHttpClient,
    AsyncHttpx2Client,
    AsyncOAuth2Scheme,
    AsyncRawClient,
    AsyncTokenSource,
    ClientCredentials,
    ClientCredentialsOrDict,
    LoggingOptionsOrDict,
    RetryOptionsOrDict,
    client_secret_basic,
    no_auth,
    param,
)
from .server.environment import Environment


class AsyncPayoutsClient(BasePayoutsClient[AsyncRawClient]):
    def __init__(
        self,
        *,
        environment: Environment = "production",
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retry_options: int | RetryOptionsOrDict | None = None,
        logging_options: LoggingOptionsOrDict | None = None,
        custom_async_http_client: AsyncHttpClient | None = None,
        oauth2: ClientCredentialsOrDict[Oauth2Scope] | None = None,
        oauth2_token_source: AsyncTokenSource[ClientCredentials[Oauth2Scope]] | None = None,
    ) -> None:
        super().__init__(
            environment=environment,
            base_url=base_url,
            timeout=timeout,
            retry_options=retry_options,
            logging_options=logging_options,
        )
        self._raw_client = AsyncRawClient(
            http_client=(
                custom_async_http_client if custom_async_http_client is not None else AsyncHttpx2Client(timeout=timeout)
            ),
            retry_options=self._retry_options,
            logging_options=self._logging_options,
            global_headers=[
                param[str]("User-Agent", "PayoutsClient/1.9 Python"),
                param[str]("X-APIMatic-Lang", "Python"),
                param[str]("X-APIMatic-Package-Version", "1.9"),
                param[str]("X-APIMatic-Gen-Version", "4.0.0"),
                param[str]("X-APIMatic-OS", OPERATING_SYSTEM),
                param[str]("X-APIMatic-Runtime", PYTHON_RUNTIME),
            ],
        )
        self._auth = AsyncAuthSchemes(
            oauth2=(
                AsyncOAuth2Scheme(
                    credentials=ClientCredentials[Oauth2Scope].coerce(oauth2),
                    source=(
                        oauth2_token_source
                        if oauth2_token_source is not None
                        else AsyncClientCredentialsTokenSource[Oauth2Scope](
                            client=self._raw_client,
                            token_url=self._server.default("/v1/oauth2/token"),
                            placement=client_secret_basic,
                        )
                    ),
                )
                if oauth2 is not None
                else no_auth
            ),
        )

    @cached_property
    def payouts(self) -> AsyncPayouts:
        return AsyncPayouts(self._raw_client, self._server, self._auth)

    @cached_property
    def payouts_item(self) -> AsyncPayoutsItem:
        return AsyncPayoutsItem(self._raw_client, self._server, self._auth)

    async def aclose(self) -> None:
        await self._raw_client.http_client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        await self.aclose()


AsyncClient = AsyncPayoutsClient
