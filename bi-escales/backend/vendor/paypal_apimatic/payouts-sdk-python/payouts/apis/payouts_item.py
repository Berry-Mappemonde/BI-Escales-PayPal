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
    json_decoder,
    param,
    unwrap,
)
from ..errors.payouts_item_cancel_error import PayoutsItemCancelErrorBody, payouts_item_cancel_error_mapper
from ..errors.payouts_item_get_error import PayoutsItemGetErrorBody, payouts_item_get_error_mapper
from ..models.payout_item2 import PayoutItem2
from ..server.server import Server


class PayoutsItem:
    def __init__(self, client: RawClient, server: Server, auth: AuthSchemes) -> None:
        self._with_raw_response = PayoutsItemWithRawResponse(client, server, auth)

    def payouts_item_cancel(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> PayoutItem2:
        """Cancels an unclaimed payout item, by ID. If no one claims the unclaimed item within 30 days, the API
        automatically returns the funds to the sender. Use this call to cancel the unclaimed item before the automatic
        30-day refund. You can cancel payout items with a <code>transaction_status</code> of <code>UNCLAIMED</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP ``200 OK`` status code with a JSON response body that shows payout
            item details.

        Raises:
            ApiError: Request is not well-formed, syntactically incorrect, or violates schema. Resource Not Found. An
                internal server error has occurred. ``error`` is ``Error | RawError``."""
        return unwrap(self._with_raw_response.payouts_item_cancel(payout_item_id, request_options=request_options))

    def payouts_item_get(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> PayoutItem2:
        """Shows details for a payout item, by ID. A <code>payout_item_id</code> helps you identify denied payments. If
        a payment is denied, you can use the <code>payout_item_id</code> to identify the payment even if it lacks a
        <code>transaction_id</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP <code>200 OK</code> status code and a JSON response body with a
            <code>payout_item_details</code> object, which contains data about a payout item including the transaction
            status.

        Raises:
            ApiError: Resource Not Found. An internal server error has occurred. ``error`` is ``Error | RawError``."""
        return unwrap(self._with_raw_response.payouts_item_get(payout_item_id, request_options=request_options))

    @property
    def with_raw_response(self) -> PayoutsItemWithRawResponse:
        return self._with_raw_response


class AsyncPayoutsItem:
    def __init__(self, client: AsyncRawClient, server: Server, auth: AsyncAuthSchemes) -> None:
        self._with_raw_response = AsyncPayoutsItemWithRawResponse(client, server, auth)

    async def payouts_item_cancel(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> PayoutItem2:
        """Cancels an unclaimed payout item, by ID. If no one claims the unclaimed item within 30 days, the API
        automatically returns the funds to the sender. Use this call to cancel the unclaimed item before the automatic
        30-day refund. You can cancel payout items with a <code>transaction_status</code> of <code>UNCLAIMED</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP ``200 OK`` status code with a JSON response body that shows payout
            item details.

        Raises:
            ApiError: Request is not well-formed, syntactically incorrect, or violates schema. Resource Not Found. An
                internal server error has occurred. ``error`` is ``Error | RawError``."""
        return unwrap(
            await self._with_raw_response.payouts_item_cancel(payout_item_id, request_options=request_options)
        )

    async def payouts_item_get(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> PayoutItem2:
        """Shows details for a payout item, by ID. A <code>payout_item_id</code> helps you identify denied payments. If
        a payment is denied, you can use the <code>payout_item_id</code> to identify the payment even if it lacks a
        <code>transaction_id</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            A successful request returns the HTTP <code>200 OK</code> status code and a JSON response body with a
            <code>payout_item_details</code> object, which contains data about a payout item including the transaction
            status.

        Raises:
            ApiError: Resource Not Found. An internal server error has occurred. ``error`` is ``Error | RawError``."""
        return unwrap(await self._with_raw_response.payouts_item_get(payout_item_id, request_options=request_options))

    @property
    def with_raw_response(self) -> AsyncPayoutsItemWithRawResponse:
        return self._with_raw_response


class PayoutsItemWithRawResponse(SecuredRawResponse[RawClient, Server, AuthSchemes]):
    def payouts_item_cancel(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> ApiResult[PayoutItem2, PayoutsItemCancelErrorBody]:
        """Cancels an unclaimed payout item, by ID. If no one claims the unclaimed item within 30 days, the API
        automatically returns the funds to the sender. Use this call to cancel the unclaimed item before the automatic
        30-day refund. You can cancel payout items with a <code>transaction_status</code> of <code>UNCLAIMED</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return self._client.execute(
            http_method="POST",
            url_template=self._server.default("/v1/payments/payouts-item/{payout_item_id}/cancel"),
            path_params=[param[str]("payout_item_id", payout_item_id)],
            headers=[param[UUID]("Idempotency-Key", uuid4())],
            auth_scheme=self._auth.oauth2,
            decoder=json_decoder[PayoutItem2],
            error_mapper=payouts_item_cancel_error_mapper,
            request_options=request_options,
        )

    def payouts_item_get(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> ApiResult[PayoutItem2, PayoutsItemGetErrorBody]:
        """Shows details for a payout item, by ID. A <code>payout_item_id</code> helps you identify denied payments. If
        a payment is denied, you can use the <code>payout_item_id</code> to identify the payment even if it lacks a
        <code>transaction_id</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return self._client.execute(
            http_method="GET",
            url_template=self._server.default("/v1/payments/payouts-item/{payout_item_id}"),
            path_params=[param[str]("payout_item_id", payout_item_id)],
            auth_scheme=self._auth.oauth2,
            decoder=json_decoder[PayoutItem2],
            error_mapper=payouts_item_get_error_mapper,
            request_options=request_options,
        )


class AsyncPayoutsItemWithRawResponse(SecuredRawResponse[AsyncRawClient, Server, AsyncAuthSchemes]):
    async def payouts_item_cancel(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> ApiResult[PayoutItem2, PayoutsItemCancelErrorBody]:
        """Cancels an unclaimed payout item, by ID. If no one claims the unclaimed item within 30 days, the API
        automatically returns the funds to the sender. Use this call to cancel the unclaimed item before the automatic
        30-day refund. You can cancel payout items with a <code>transaction_status</code> of <code>UNCLAIMED</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return await self._client.execute(
            http_method="POST",
            url_template=self._server.default("/v1/payments/payouts-item/{payout_item_id}/cancel"),
            path_params=[param[str]("payout_item_id", payout_item_id)],
            headers=[param[UUID]("Idempotency-Key", uuid4())],
            auth_scheme=self._auth.oauth2,
            decoder=async_json_decoder[PayoutItem2],
            error_mapper=payouts_item_cancel_error_mapper,
            request_options=request_options,
        )

    async def payouts_item_get(
        self, payout_item_id: str, *, request_options: RequestOptionsOrDict | None = None
    ) -> ApiResult[PayoutItem2, PayoutsItemGetErrorBody]:
        """Shows details for a payout item, by ID. A <code>payout_item_id</code> helps you identify denied payments. If
        a payment is denied, you can use the <code>payout_item_id</code> to identify the payment even if it lacks a
        <code>transaction_id</code>.

        Args:
            payout_item_id: The ID of the payout item to cancel.
            request_options: Per-call overrides for this one request, such as a timeout, extra headers, or its retry
                count and statuses.

        Returns:
            An ``ApiResult`` holding the deserialized response or the error body."""
        return await self._client.execute(
            http_method="GET",
            url_template=self._server.default("/v1/payments/payouts-item/{payout_item_id}"),
            path_params=[param[str]("payout_item_id", payout_item_id)],
            auth_scheme=self._auth.oauth2,
            decoder=async_json_decoder[PayoutItem2],
            error_mapper=payouts_item_get_error_mapper,
            request_options=request_options,
        )
