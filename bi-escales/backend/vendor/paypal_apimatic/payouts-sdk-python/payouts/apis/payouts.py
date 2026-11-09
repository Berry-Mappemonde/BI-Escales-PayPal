from __future__ import annotations

from uuid import UUID, uuid4

from ..auth import AsyncAuthSchemes, AuthSchemes
from ..core import (
    ApiResult,
    AsyncRawClient,
    RawClient,
    RequestOptionsOrDict,
    SecuredRawResponse,
    async_json_decoder,
    json_body,
    json_decoder,
    param,
    unwrap,
)
from ..errors.payouts_get_error import PayoutsGetErrorBody, payouts_get_error_mapper
from ..errors.payouts_post_error import PayoutsPostErrorBody, payouts_post_error_mapper
from ..models.create_payout_request import CreatePayoutRequest, CreatePayoutRequestDict
from ..models.create_payout_response import CreatePayoutResponse
from ..models.payout_batch import PayoutBatch
from ..server.server import Server


class Payouts:
    def __init__(self, client: RawClient, server: Server, auth: AuthSchemes) -> None:
        self._with_raw_response = PayoutsWithRawResponse(client, server, auth)

    def payouts_get(
        self,
        id_: str,
        *,
        fields: str | None = None,
        page: int | None = 1,
        page_size: int | None = None,
        total_required: bool | None = False,
        request_options: RequestOptionsOrDict | None = None,
    ) -> PayoutBatch:
        """Shows the latest status of a batch payout. Includes the transaction status and other data for individual
        payout items.

        Args:
            id_: The ID of the payout for which to show details.
            fields: Shows details for only the specified fields.
            page: A non-zero integer representing the page of the results.
            page_size: The maximum number of results to return at one time. Value is a non-negative, non-zero integer.
                If the user chooses pagination, the maximum page is ``1000``.
            total_required: Indicates whether to show the total items and total pages count in the response.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP ``200 OK`` status code and a JSON response body that shows batch
            payout details.

        Raises:
            ApiError: Resource Not Found. An internal server error has occurred. ``error`` is ``Error | RawError``."""
        return unwrap(
            self._with_raw_response.payouts_get(
                id_,
                fields=fields,
                page=page,
                page_size=page_size,
                total_required=total_required,
                request_options=request_options,
            ),
        )

    def payouts_post(
        self,
        *,
        pay_pal_request_id: str | None = None,
        body: CreatePayoutRequest | CreatePayoutRequestDict | None = None,
        request_options: RequestOptionsOrDict | None = None,
    ) -> CreatePayoutResponse:
        """Creates a batch payout. In the JSON request body, pass a ``sender_batch_header`` and an ``items`` array. The
        ``sender_batch_header`` defines how to handle the payout. The ``items`` array defines the payout items.<br/>You
        can make payouts to one or more recipients.<blockquote><strong>Notes:</strong> <ul><li><p>PayPal does not
        process duplicate payouts. If you specify a <code>sender_batch_id</code> that was used in the last 30 days, the
        API rejects the request with an error message that shows the duplicate <code>sender_batch_id</code> and includes
        a HATEOAS link to the original payout with the same <code>sender_batch_id</code>.</p><p>If you receive an HTTP
        <code>5<i>nn</i></code> status code, you can safely retry the request with the same
        <code>sender_batch_id</code>.</p></li><li><p>The Payouts API does not support build notation (BN) codes. In a
        future Payouts release, you can optionally provide BN codes in the <code>PayPal-Partner-Attribution-Id</code>
        request header.</p><p>For information about the <code>PayPal-Partner-Attribution-Id</code> header, see <a
        href="/api/rest/requests/#http-request-headers">HTTP request headers</a>. To learn about or request a BN code,
        contact your partner manager or see <a href="https://www.paypal.com/us/webapps/mpp/partner-program">PayPal
        Partner Program</a>.</p></li></ul></blockquote>

        Args:
            pay_pal_request_id: The server stores keys for 30 days.
            body: The request body.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP <code>201 Created</code> status code and a JSON response body that
            shows the ID for the payout and payout details. To show payout status, use the <code>payout_batch_id</code>
            value that appears in the response. If the initial scan that checks for syntax errors, missing or duplicated
            keywords, and more succeeds, the <code>batch_status</code> is <code>PENDING</code>. The initial scan checks
            for syntax errors and missing or duplicated keywords. The API does not immediately validate some payout item
            values, such as the receiver phone numbers.

        Raises:
            ApiError: Request is not well-formed, syntactically incorrect, or violates schema. Authorization failed due
                to insufficient permissions. An internal server error has occurred. ``error`` is ``Error |
                RawError``."""
        return unwrap(
            self._with_raw_response.payouts_post(
                pay_pal_request_id=pay_pal_request_id, body=body, request_options=request_options
            ),
        )

    @property
    def with_raw_response(self) -> PayoutsWithRawResponse:
        return self._with_raw_response


class AsyncPayouts:
    def __init__(self, client: AsyncRawClient, server: Server, auth: AsyncAuthSchemes) -> None:
        self._with_raw_response = AsyncPayoutsWithRawResponse(client, server, auth)

    async def payouts_get(
        self,
        id_: str,
        *,
        fields: str | None = None,
        page: int | None = 1,
        page_size: int | None = None,
        total_required: bool | None = False,
        request_options: RequestOptionsOrDict | None = None,
    ) -> PayoutBatch:
        """Shows the latest status of a batch payout. Includes the transaction status and other data for individual
        payout items.

        Args:
            id_: The ID of the payout for which to show details.
            fields: Shows details for only the specified fields.
            page: A non-zero integer representing the page of the results.
            page_size: The maximum number of results to return at one time. Value is a non-negative, non-zero integer.
                If the user chooses pagination, the maximum page is ``1000``.
            total_required: Indicates whether to show the total items and total pages count in the response.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP ``200 OK`` status code and a JSON response body that shows batch
            payout details.

        Raises:
            ApiError: Resource Not Found. An internal server error has occurred. ``error`` is ``Error | RawError``."""
        return unwrap(
            await self._with_raw_response.payouts_get(
                id_,
                fields=fields,
                page=page,
                page_size=page_size,
                total_required=total_required,
                request_options=request_options,
            ),
        )

    async def payouts_post(
        self,
        *,
        pay_pal_request_id: str | None = None,
        body: CreatePayoutRequest | CreatePayoutRequestDict | None = None,
        request_options: RequestOptionsOrDict | None = None,
    ) -> CreatePayoutResponse:
        """Creates a batch payout. In the JSON request body, pass a ``sender_batch_header`` and an ``items`` array. The
        ``sender_batch_header`` defines how to handle the payout. The ``items`` array defines the payout items.<br/>You
        can make payouts to one or more recipients.<blockquote><strong>Notes:</strong> <ul><li><p>PayPal does not
        process duplicate payouts. If you specify a <code>sender_batch_id</code> that was used in the last 30 days, the
        API rejects the request with an error message that shows the duplicate <code>sender_batch_id</code> and includes
        a HATEOAS link to the original payout with the same <code>sender_batch_id</code>.</p><p>If you receive an HTTP
        <code>5<i>nn</i></code> status code, you can safely retry the request with the same
        <code>sender_batch_id</code>.</p></li><li><p>The Payouts API does not support build notation (BN) codes. In a
        future Payouts release, you can optionally provide BN codes in the <code>PayPal-Partner-Attribution-Id</code>
        request header.</p><p>For information about the <code>PayPal-Partner-Attribution-Id</code> header, see <a
        href="/api/rest/requests/#http-request-headers">HTTP request headers</a>. To learn about or request a BN code,
        contact your partner manager or see <a href="https://www.paypal.com/us/webapps/mpp/partner-program">PayPal
        Partner Program</a>.</p></li></ul></blockquote>

        Args:
            pay_pal_request_id: The server stores keys for 30 days.
            body: The request body.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP <code>201 Created</code> status code and a JSON response body that
            shows the ID for the payout and payout details. To show payout status, use the <code>payout_batch_id</code>
            value that appears in the response. If the initial scan that checks for syntax errors, missing or duplicated
            keywords, and more succeeds, the <code>batch_status</code> is <code>PENDING</code>. The initial scan checks
            for syntax errors and missing or duplicated keywords. The API does not immediately validate some payout item
            values, such as the receiver phone numbers.

        Raises:
            ApiError: Request is not well-formed, syntactically incorrect, or violates schema. Authorization failed due
                to insufficient permissions. An internal server error has occurred. ``error`` is ``Error |
                RawError``."""
        return unwrap(
            await self._with_raw_response.payouts_post(
                pay_pal_request_id=pay_pal_request_id, body=body, request_options=request_options
            ),
        )

    @property
    def with_raw_response(self) -> AsyncPayoutsWithRawResponse:
        return self._with_raw_response


class PayoutsWithRawResponse(SecuredRawResponse[RawClient, Server, AuthSchemes]):
    def payouts_get(
        self,
        id_: str,
        *,
        fields: str | None = None,
        page: int | None = 1,
        page_size: int | None = None,
        total_required: bool | None = False,
        request_options: RequestOptionsOrDict | None = None,
    ) -> ApiResult[PayoutBatch, PayoutsGetErrorBody]:
        """Shows the latest status of a batch payout. Includes the transaction status and other data for individual
        payout items.

        Args:
            id_: The ID of the payout for which to show details.
            fields: Shows details for only the specified fields.
            page: A non-zero integer representing the page of the results.
            page_size: The maximum number of results to return at one time. Value is a non-negative, non-zero integer.
                If the user chooses pagination, the maximum page is ``1000``.
            total_required: Indicates whether to show the total items and total pages count in the response.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return self._client.execute(
            http_method="GET",
            url_template=self._server.default("/v1/payments/payouts/{id}"),
            path_params=[param[str]("id", id_)],
            query_params=[
                param[str | None]("fields", fields),
                param[int | None]("page", page),
                param[int | None]("page_size", page_size),
                param[bool | None]("total_required", total_required),
            ],
            auth_scheme=self._auth.oauth2,
            decoder=json_decoder[PayoutBatch],
            error_mapper=payouts_get_error_mapper,
            request_options=request_options,
        )

    def payouts_post(
        self,
        *,
        pay_pal_request_id: str | None = None,
        body: CreatePayoutRequest | CreatePayoutRequestDict | None = None,
        request_options: RequestOptionsOrDict | None = None,
    ) -> ApiResult[CreatePayoutResponse, PayoutsPostErrorBody]:
        """Creates a batch payout. In the JSON request body, pass a ``sender_batch_header`` and an ``items`` array. The
        ``sender_batch_header`` defines how to handle the payout. The ``items`` array defines the payout items.<br/>You
        can make payouts to one or more recipients.<blockquote><strong>Notes:</strong> <ul><li><p>PayPal does not
        process duplicate payouts. If you specify a <code>sender_batch_id</code> that was used in the last 30 days, the
        API rejects the request with an error message that shows the duplicate <code>sender_batch_id</code> and includes
        a HATEOAS link to the original payout with the same <code>sender_batch_id</code>.</p><p>If you receive an HTTP
        <code>5<i>nn</i></code> status code, you can safely retry the request with the same
        <code>sender_batch_id</code>.</p></li><li><p>The Payouts API does not support build notation (BN) codes. In a
        future Payouts release, you can optionally provide BN codes in the <code>PayPal-Partner-Attribution-Id</code>
        request header.</p><p>For information about the <code>PayPal-Partner-Attribution-Id</code> header, see <a
        href="/api/rest/requests/#http-request-headers">HTTP request headers</a>. To learn about or request a BN code,
        contact your partner manager or see <a href="https://www.paypal.com/us/webapps/mpp/partner-program">PayPal
        Partner Program</a>.</p></li></ul></blockquote>

        Args:
            pay_pal_request_id: The server stores keys for 30 days.
            body: The request body.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return self._client.execute(
            http_method="POST",
            url_template=self._server.default("/v1/payments/payouts"),
            headers=[
                param[str | None]("PayPal-Request-Id", pay_pal_request_id), param[UUID]("Idempotency-Key", uuid4())
            ],
            body=json_body[CreatePayoutRequest | CreatePayoutRequestDict | None](body),
            auth_scheme=self._auth.oauth2,
            decoder=json_decoder[CreatePayoutResponse],
            error_mapper=payouts_post_error_mapper,
            request_options=request_options,
        )


class AsyncPayoutsWithRawResponse(SecuredRawResponse[AsyncRawClient, Server, AsyncAuthSchemes]):
    async def payouts_get(
        self,
        id_: str,
        *,
        fields: str | None = None,
        page: int | None = 1,
        page_size: int | None = None,
        total_required: bool | None = False,
        request_options: RequestOptionsOrDict | None = None,
    ) -> ApiResult[PayoutBatch, PayoutsGetErrorBody]:
        """Shows the latest status of a batch payout. Includes the transaction status and other data for individual
        payout items.

        Args:
            id_: The ID of the payout for which to show details.
            fields: Shows details for only the specified fields.
            page: A non-zero integer representing the page of the results.
            page_size: The maximum number of results to return at one time. Value is a non-negative, non-zero integer.
                If the user chooses pagination, the maximum page is ``1000``.
            total_required: Indicates whether to show the total items and total pages count in the response.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return await self._client.execute(
            http_method="GET",
            url_template=self._server.default("/v1/payments/payouts/{id}"),
            path_params=[param[str]("id", id_)],
            query_params=[
                param[str | None]("fields", fields),
                param[int | None]("page", page),
                param[int | None]("page_size", page_size),
                param[bool | None]("total_required", total_required),
            ],
            auth_scheme=self._auth.oauth2,
            decoder=async_json_decoder[PayoutBatch],
            error_mapper=payouts_get_error_mapper,
            request_options=request_options,
        )

    async def payouts_post(
        self,
        *,
        pay_pal_request_id: str | None = None,
        body: CreatePayoutRequest | CreatePayoutRequestDict | None = None,
        request_options: RequestOptionsOrDict | None = None,
    ) -> ApiResult[CreatePayoutResponse, PayoutsPostErrorBody]:
        """Creates a batch payout. In the JSON request body, pass a ``sender_batch_header`` and an ``items`` array. The
        ``sender_batch_header`` defines how to handle the payout. The ``items`` array defines the payout items.<br/>You
        can make payouts to one or more recipients.<blockquote><strong>Notes:</strong> <ul><li><p>PayPal does not
        process duplicate payouts. If you specify a <code>sender_batch_id</code> that was used in the last 30 days, the
        API rejects the request with an error message that shows the duplicate <code>sender_batch_id</code> and includes
        a HATEOAS link to the original payout with the same <code>sender_batch_id</code>.</p><p>If you receive an HTTP
        <code>5<i>nn</i></code> status code, you can safely retry the request with the same
        <code>sender_batch_id</code>.</p></li><li><p>The Payouts API does not support build notation (BN) codes. In a
        future Payouts release, you can optionally provide BN codes in the <code>PayPal-Partner-Attribution-Id</code>
        request header.</p><p>For information about the <code>PayPal-Partner-Attribution-Id</code> header, see <a
        href="/api/rest/requests/#http-request-headers">HTTP request headers</a>. To learn about or request a BN code,
        contact your partner manager or see <a href="https://www.paypal.com/us/webapps/mpp/partner-program">PayPal
        Partner Program</a>.</p></li></ul></blockquote>

        Args:
            pay_pal_request_id: The server stores keys for 30 days.
            body: The request body.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return await self._client.execute(
            http_method="POST",
            url_template=self._server.default("/v1/payments/payouts"),
            headers=[
                param[str | None]("PayPal-Request-Id", pay_pal_request_id), param[UUID]("Idempotency-Key", uuid4())
            ],
            body=json_body[CreatePayoutRequest | CreatePayoutRequestDict | None](body),
            auth_scheme=self._auth.oauth2,
            decoder=async_json_decoder[CreatePayoutResponse],
            error_mapper=payouts_post_error_mapper,
            request_options=request_options,
        )
