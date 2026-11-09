from __future__ import annotations

from functools import cached_property
from types import TracebackType
from uuid import UUID, uuid4

from typing_extensions import Self

from .auth import AsyncAuthSchemes, Oauth2Scope
from .base_client import DEFAULT_TIMEOUT, BasePartnerReferralsClient
from .core import (
    OPERATING_SYSTEM,
    PYTHON_RUNTIME,
    ApiResult,
    AsyncAnySchemes,
    AsyncClientCredentialsTokenSource,
    AsyncHttpClient,
    AsyncHttpx2Client,
    AsyncOAuth2Scheme,
    AsyncRawClient,
    AsyncTokenSource,
    ClientCredentials,
    ClientCredentialsOrDict,
    LoggingOptionsOrDict,
    RequestOptionsOrDict,
    RetryOptionsOrDict,
    SecuredRawResponse,
    async_json_decoder,
    client_secret_basic,
    json_body,
    no_auth,
    param,
    unwrap,
)
from .errors.partner_referrals_create_error import (
    PartnerReferralsCreateErrorBody,
    partner_referrals_create_error_mapper,
)
from .errors.partner_referrals_read_error import PartnerReferralsReadErrorBody, partner_referrals_read_error_mapper
from .models.create_referral_data_response import CreateReferralDataResponse
from .models.customer_data import CustomerData, CustomerDataDict
from .models.referral_data_response import ReferralDataResponse
from .server.environment import Environment
from .server.server import Server


class AsyncPartnerReferralsClient(BasePartnerReferralsClient[AsyncRawClient]):
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
                param[str]("User-Agent", "PartnerReferralsClient/2.5 Python"),
                param[str]("X-APIMatic-Lang", "Python"),
                param[str]("X-APIMatic-Package-Version", "2.5"),
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
    def with_raw_response(self) -> AsyncApiWithRawResponse:
        return AsyncApiWithRawResponse(self._raw_client, self._server, self._auth)

    async def partner_referrals_create(
        self, body: CustomerData | CustomerDataDict, *, request_options: RequestOptionsOrDict | None = None
    ) -> CreateReferralDataResponse:
        """Creates a partner referral that is shared by the partner or API caller. The partner referral is used to
        onboard the seller, and contains the seller's personal, business, financial and operations.

        Args:
            body: The request body.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP ``201 Created`` status code and a JSON response body that contains a
            `HATEOAS link </docs/api/overview/#hateoas-links>`__ to show the referral data and an ``action_url`` to
            which you redirect the customer in a browser to complete the signup process. The ``partner_referral_id``
            token is appended to the URL.

        Raises:
            ApiError: Request is not well-formed, syntactically incorrect, or violates schema. The API call is not
                authorized. Authorization failed due to insufficient permissions or missing scopes on the caller
                account. The caller is not a business account or the account is closed or locked. An internal server
                error has occurred. ``error`` is ``V2CustomerPartnerReferrals400Error1 |
                V2CustomerPartnerReferrals401Error1 | V2CustomerPartnerReferrals403Error1 |
                V2CustomerPartnerReferrals422Error1 | InternalServerError | RawError``."""
        return unwrap(await self.with_raw_response.partner_referrals_create(body, request_options=request_options))

    async def partner_referrals_read(
        self, partner_referral_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> ReferralDataResponse:
        """Shows details by ID for referral data that was shared by the partner or API caller.

        Args:
            partner_referral_id: The ID of the partner-referrals data for which to show details.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP ``200 OK`` status code and a JSON response body that shows referral
            data.

        Raises:
            ApiError: The API call is not authorized. Authorization failed due to insufficient permissions or missing
                scopes on the caller Account. An internal server error has occurred. ``error`` is
                ``V2CustomerPartnerReferrals401Error1 | V2CustomerPartnerReferrals403Error1 | InternalServerError |
                RawError``."""
        return unwrap(
            await self.with_raw_response.partner_referrals_read(partner_referral_id, request_options=request_options)
        )

    async def aclose(self) -> None:
        await self._raw_client.http_client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, exc_tb: TracebackType | None
    ) -> None:
        await self.aclose()


class AsyncApiWithRawResponse(SecuredRawResponse[AsyncRawClient, Server, AsyncAuthSchemes]):
    async def partner_referrals_create(
        self, body: CustomerData | CustomerDataDict, *, request_options: RequestOptionsOrDict | None = None
    ) -> ApiResult[CreateReferralDataResponse, PartnerReferralsCreateErrorBody]:
        """Creates a partner referral that is shared by the partner or API caller. The partner referral is used to
        onboard the seller, and contains the seller's personal, business, financial and operations.

        Args:
            body: The request body.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return await self._client.execute(
            http_method="POST",
            url_template=self._server.default("/v2/customer/partner-referrals"),
            headers=[param[UUID]("Idempotency-Key", uuid4())],
            body=json_body[CustomerData | CustomerDataDict](body),
            auth_scheme=self._auth.oauth2,
            decoder=async_json_decoder[CreateReferralDataResponse],
            error_mapper=partner_referrals_create_error_mapper,
            request_options=request_options,
        )

    async def partner_referrals_read(
        self, partner_referral_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> ApiResult[ReferralDataResponse, PartnerReferralsReadErrorBody]:
        """Shows details by ID for referral data that was shared by the partner or API caller.

        Args:
            partner_referral_id: The ID of the partner-referrals data for which to show details.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return await self._client.execute(
            http_method="GET",
            url_template=self._server.default("/v2/customer/partner-referrals/{partner_referral_id}"),
            path_params=[param[str]("partner_referral_id", partner_referral_id)],
            auth_scheme=AsyncAnySchemes(self._auth.oauth2, self._auth.oauth2),
            decoder=async_json_decoder[ReferralDataResponse],
            error_mapper=partner_referrals_read_error_mapper,
            request_options=request_options,
        )


AsyncClient = AsyncPartnerReferralsClient
